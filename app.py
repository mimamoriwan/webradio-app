import streamlit as st
import google.generativeai as genai
from openai import OpenAI
import requests
from bs4 import BeautifulSoup
import time
import os
import hashlib
import re
from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs
import yt_dlp
import firebase_admin
from firebase_admin import credentials, firestore, storage

# ---------------------------
# 基本設定
# ---------------------------
st.set_page_config(page_title="WebRadio", page_icon="📻")

# ★設定エリア（バケット名はそのまま）
BUCKET_NAME = "webradio-app1.firebasestorage.app" 

# ---------------------------
# APIキーとFirebase設定の読み込み（ここがクラウド用！）
# ---------------------------
# 1. APIキーを「金庫（Secrets）」から読み込む
gemini_key = st.secrets.get("GEMINI_API_KEY", "")
openai_key = st.secrets.get("OPENAI_API_KEY", "")

# 2. Firebaseの鍵も「金庫」から読み込む
# （クラウド上ではファイルではなく、設定データとして読み込みます）
if not firebase_admin._apps:
    try:
        # secretsにfirebase情報があるか確認
        if "firebase" in st.secrets:
            # クラウド用：secretsから辞書形式で作る
            key_dict = dict(st.secrets["firebase"])
            cred = credentials.Certificate(key_dict)
        else:
            # ローカル用：もしファイルがあればそっちを使う（開発用）
            if os.path.exists("firebase_key.json"):
                cred = credentials.Certificate("firebase_key.json")
            else:
                cred = None
        
        if cred:
            firebase_admin.initialize_app(cred, {
                'storageBucket': BUCKET_NAME
            })
    except Exception as e:
        st.error(f"Firebaseの接続設定エラー: {e}")

# 接続できていればDBなどを用意
if firebase_admin._apps:
    db = firestore.client()
    bucket = storage.bucket()
else:
    st.warning("⚠️ Firebase設定が見つかりません。Secretsを設定してください。")

# ---------------------------
# サイドバー（入力欄は削除済み！）
# ---------------------------
with st.sidebar:
    st.header("⚙️ 番組設定")
    
    # APIキーの入力欄は削除しました。
    # 代わりに、キーが正しく読み込めているかチェックだけします。
    if not gemini_key or not openai_key:
        st.error("⚠️ APIキーが設定されていません。管理者はStreamlit CloudのSecretsを設定してください。")

    language = st.selectbox("放送言語", ["日本語", "英語", "中国語"], index=0)
    
    style_options = {
        "standard": "🎙️ 標準（ニュース番組風）",
        "jk": "🎀 女子高生の放課後トーク（JK）",
        "comedian": "🤣 お笑い芸人のラジオ（ボケとツッコミ）",
        "okayama": "🍑 岡山弁の女子アナ（ローカル番組）",
        "university": "🏫 大学生の学食トーク（タメ口）"
    }
    style_key = st.selectbox("番組の雰囲気", options=list(style_options.keys()), format_func=lambda x: style_options[x])
    
    st.markdown("---")
    st.caption("※2回目以降はキャッシュを使用するため無料です")

# ---------------------------
# 以下、ロジック部分は変更なし
# ---------------------------
def generate_cache_key(url, style, lang):
    unique_string = f"{url}_{style}_{lang}"
    return hashlib.md5(unique_string.encode()).hexdigest()

def check_cache(cache_key):
    if not firebase_admin._apps: return None
    doc_ref = db.collection('radios').document(cache_key)
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    return None

def save_to_cache(cache_key, audio_data, url, style, lang, title):
    if not firebase_admin._apps: return None
    blob = bucket.blob(f"audio/{cache_key}.mp3")
    blob.upload_from_string(audio_data, content_type="audio/mp3")
    blob.make_public()
    audio_url = blob.public_url

    doc_ref = db.collection('radios').document(cache_key)
    doc_ref.set({
        'url': url,
        'style': style,
        'language': lang,
        'title': title,
        'audio_url': audio_url,
        'created_at': firestore.SERVER_TIMESTAMP
    })
    return audio_url

def get_style_config(style_key, language):
    config = {
        "prompt_role": f"【役割設定】A:メインMC B:アシスタント 口調:{language}の標準的ニュース",
        "voice_a": "echo", "voice_b": "nova"
    }
    if style_key == "jk":
        config = {"prompt_role": "【役割】A:JK1 B:JK2 口調:タメ口、若者言葉", "voice_a": "shimmer", "voice_b": "nova"}
    elif style_key == "comedian":
        config = {"prompt_role": "【役割】A:ボケ B:ツッコミ(関西弁) 口調:深夜ラジオ", "voice_a": "echo", "voice_b": "onyx"}
    elif style_key == "okayama":
        config = {"prompt_role": "【役割】A,B:岡山弁のアナウンサー", "voice_a": "echo", "voice_b": "nova"}
    elif style_key == "university":
        config = {"prompt_role": "【役割】A:男子大学生 B:女子大学生 口調:学食トーク", "voice_a": "fable", "voice_b": "alloy"}
    return config

def transcribe_with_whisper(video_url, api_key):
    client = OpenAI(api_key=api_key)
    output_filename = "temp_audio.mp3"
    if os.path.exists(output_filename): os.remove(output_filename)
    ydl_opts = {'format':'bestaudio/best','postprocessors':[{'key':'FFmpegExtractAudio','preferredcodec':'mp3'}],'outtmpl':'temp_audio','quiet':True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([video_url])
        if not os.path.exists(output_filename):
            for f in os.listdir('.'):
                if f.startswith("temp_audio"): output_filename = f; break
        with open(output_filename, "rb") as f: transcript = client.audio.transcriptions.create(model="whisper-1", file=f, response_format="text")
        if os.path.exists(output_filename): os.remove(output_filename)
        return transcript
    except Exception as e: return f"Error: {e}"

def get_video_id(url):
    parsed = urlparse(url)
    if "youtube.com" in parsed.netloc: return parse_qs(parsed.query).get("v", [None])[0]
    elif "youtu.be" in parsed.netloc: return parsed.path[1:]
    return None

def fetch_content(url, openai_api_key):
    if "youtube.com" in url or "youtu.be" in url:
        video_id = get_video_id(url)
        if not video_id: return "Error"
        try:
            ts = YouTubeTranscriptApi.get_transcript(video_id, languages=['ja','en'])
            return f"【YouTube(字幕)】\n{' '.join([t['text'] for t in ts])[:5000]}..."
        except:
            if not openai_api_key: return "【YouTube】字幕なし(要OpenAIキー)"
            return f"【YouTube(音声)】\n{transcribe_with_whisper(url, openai_api_key)[:5000]}..."
    else:
        try:
            res = requests.get(url, timeout=10)
            res.encoding = res.apparent_encoding
            soup = BeautifulSoup(res.text, 'html.parser')
            title = soup.title.string if soup.title else "Web記事"
            return f"【Web記事：{title}】\n{' '.join([p.text for p in soup.find_all('p')])[:5000]}..."
        except: return f"Error: {url}"

# ---------------------------
# メイン画面
# ---------------------------
st.title("📻 WebRadio Maker (Cloud版)")
st.write("生成された音声はクラウドに保存され、**2回目以降は無料**で再生されます。")

url_input = st.text_input("記事または動画のURL (1つ入力)", placeholder="https://...")

if st.button("🎙️ 番組を再生する"):
    if not gemini_key or not openai_key:
        st.error("⚠️ APIキーが設定されていません。")
    elif not url_input:
        st.warning("URLを入力してください")
    else:
        # キャッシュチェック
        style_config = get_style_config(style_key, language)
        cache_key = generate_cache_key(url_input, style_key, language)
        
        cached_data = check_cache(cache_key)
        
        if cached_data:
            st.success(f"♻️ キャッシュが見つかりました！(コスト0円)\nタイトル: {cached_data.get('title', '無題')}")
            st.audio(cached_data['audio_url'], format="audio/mp3")
            st.download_button("⬇️ ダウンロード", data=requests.get(cached_data['audio_url']).content, file_name="cached_radio.mp3")
        
        else:
            try:
                # 情報収集
                with st.spinner("🐢 取材中..."):
                    content_text = fetch_content(url_input, openai_key)
                
                # 台本作成
                with st.spinner("✍️ 台本作成中..."):
                    genai.configure(api_key=gemini_key)
                    model = genai.GenerativeModel('gemini-flash-latest')
                    
                    prompt = f"""
                    以下の情報を元にラジオ台本を作成してください。
                    
                    {style_config['prompt_role']}

                    【重要：出力形式】
                    - **表（テーブル）形式は絶対に使わないでください。**
                    - 以下の形式で、会話文のみを箇条書きにしてください。
                    - 時間表記（0:00など）やト書きは不要です。
                    
                    A: (Aさんのセリフ)
                    B: (Bさんのセリフ)

                    【構成】OP→本題→ED。5分程度。

                    【取材データ】
                    {content_text}
                    """
                    
                    script_text = model.generate_content(prompt).text
                    with st.expander("台本を見る"): st.write(script_text)

                # 音声化
                with st.spinner("🎙️ 収録中..."):
                    client = OpenAI(api_key=openai_key)
                    lines = script_text.split('\n')
                    combined_audio = b""
                    
                    for line in lines:
                        line = line.strip()
                        if not line: continue
                        
                        parts = re.split('[:：]', line, 1)
                        if len(parts) < 2: continue
                            
                        speaker_part = parts[0].strip()
                        text_content = parts[1].strip()
                        
                        voice = None
                        if "A" in speaker_part or "Ａ" in speaker_part:
                            voice = style_config['voice_a']
                        elif "B" in speaker_part or "Ｂ" in speaker_part:
                            voice = style_config['voice_b']
                        
                        if voice and text_content:
                            try:
                                res = client.audio.speech.create(model="tts-1", voice=voice, input=text_content)
                                combined_audio += res.content
                            except: pass
                
                # 保存処理
                if len(combined_audio) == 0:
                    st.error("⚠️ 音声生成に失敗しました（台本の形式が読み取れませんでした）。キャッシュには保存しません。")
                else:
                    with st.spinner("💾 クラウドに保存中..."):
                        title = "ラジオ番組"
                        if "【Web記事：" in content_text:
                            title = content_text.split("【Web記事：")[1].split("】")[0]
                        audio_url = save_to_cache(cache_key, combined_audio, url_input, style_key, language, title)

                    st.success("🎉 完成！クラウドに保存しました")
                    st.audio(audio_url, format="audio/mp3")
                    st.download_button("⬇️ ダウンロード", data=combined_audio, file_name="new_radio.mp3")

            except Exception as e:
                st.error(f"エラー: {e}")
