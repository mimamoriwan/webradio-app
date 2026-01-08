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

# ★設定エリア
BUCKET_NAME = "webradio-app1.firebasestorage.app" 

# ---------------------------
# APIキーとFirebase設定の読み込み
# ---------------------------
gemini_key = st.secrets.get("GEMINI_API_KEY", "")
openai_key = st.secrets.get("OPENAI_API_KEY", "")

if not firebase_admin._apps:
    try:
        if "firebase" in st.secrets:
            key_dict = dict(st.secrets["firebase"])
            cred = credentials.Certificate(key_dict)
        else:
            if os.path.exists("firebase_key.json"):
                cred = credentials.Certificate("firebase_key.json")
            else:
                cred = None
        
        if cred:
            firebase_admin.initialize_app(cred, {'storageBucket': BUCKET_NAME})
    except Exception as e:
        st.error(f"Firebase設定エラー: {e}")

if firebase_admin._apps:
    db = firestore.client()
    bucket = storage.bucket()

# ---------------------------
# 関数定義エリア（変更なし）
# ---------------------------
def generate_cache_key(url, style, lang):
    unique_string = f"{url}_{style}_{lang}"
    return hashlib.md5(unique_string.encode()).hexdigest()

def check_cache(cache_key):
    if not firebase_admin._apps: return None
    doc_ref = db.collection('radios').document(cache_key)
    doc = doc_ref.get()
    if doc.exists: return doc.to_dict()
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
# メイン画面（ここを大改造しました！）
# ---------------------------
st.title("📻 WebRadio Maker")
st.caption("記事や動画のURLを入れるだけで、AIが楽しいラジオ番組にします。")

# APIキーチェック（画面には出さず、裏でチェック）
if not gemini_key or not openai_key:
    st.error("⚠️ 管理者設定エラー：APIキーが設定されていません。")

# ★ここが変更点！メイン画面に設定を移動
# -----------------------------------
st.markdown("##### ⚙️ 番組の設定") # 小さめの見出し

# 2列（カラム）を作って横に並べる
col1, col2 = st.columns(2)

with col1:
    language = st.selectbox("放送言語", ["日本語", "英語", "中国語"], index=0)

with col2:
    style_options = {
        "standard": "🎙️ 標準ニュース",
        "jk": "🎀 女子高生(JK)",
        "comedian": "🤣 お笑い芸人",
        "okayama": "🍑 岡山弁女子アナ",
        "university": "🏫 大学生トーク"
    }
    style_key = st.selectbox("番組の雰囲気", options=list(style_options.keys()), format_func=lambda x: style_options[x])

st.markdown("---") # 区切り線
# -----------------------------------

url_input = st.text_input("記事または動画のURL", placeholder="https://...")

if st.button("🎙️ 番組を再生する", use_container_width=True): # ボタンをスマホ幅いっぱいに
    if not url_input:
        st.warning("URLを入力してください")
    else:
        # ここから下のロジックは変更なし
        style_config = get_style_config(style_key, language)
        cache_key = generate_cache_key(url_input, style_key, language)
        
        cached_data = check_cache(cache_key)
        
        if cached_data:
            st.success(f"♻️ キャッシュが見つかりました！(無料)\nタイトル: {cached_data.get('title', '無題')}")
            st.audio(cached_data['audio_url'], format="audio/mp3")
            # ダウンロードボタンなどもここに入れる
        
        else:
            try:
                with st.spinner("🐢 取材中..."):
                    content_text = fetch_content(url_input, openai_key)
                
                with st.spinner("✍️ 台本作成中..."):
                    genai.configure(api_key=gemini_key)
                    model = genai.GenerativeModel('gemini-flash-latest')
                    prompt = f"""
                    以下の情報を元にラジオ台本を作成してください。
                    {style_config['prompt_role']}
                    【重要：出力形式】
                    - 表形式は禁止。会話文のみ箇条書き。
                    - ト書き不要。
                    A: (Aのセリフ)
                    B: (Bのセリフ)
                    【構成】OP→本題→ED。5分程度。
                    【取材データ】
                    {content_text}
                    """
                    script_text = model.generate_content(prompt).text
                    with st.expander("台本を見る"): st.write(script_text)

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
                
                if len(combined_audio) == 0:
                    st.error("⚠️ 生成失敗。キャッシュ保存しません。")
                else:
                    with st.spinner("💾 保存中..."):
                        title = "ラジオ番組"
                        if "【Web記事：" in content_text:
                            title = content_text.split("【Web記事：")[1].split("】")[0]
                        audio_url = save_to_cache(cache_key, combined_audio, url_input, style_key, language, title)

                    st.success("🎉 完成！")
                    st.audio(audio_url, format="audio/mp3")

            except Exception as e:
                st.error(f"エラー: {e}")
