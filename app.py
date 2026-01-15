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
import PyPDF2
import io

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
# 関数定義エリア
# ---------------------------
# ★安全対策：ドメイン判定関数
def is_safe_domain(url):
    try:
        domain = urlparse(url).netloc
        # ホワイトリスト（安全とみなすドメイン）
        safe_suffixes = ['.go.jp', '.lg.jp', '.ac.jp', '.ed.jp', '.or.jp']
        for suffix in safe_suffixes:
            if domain.endswith(suffix):
                return True
        return False
    except:
        return False

def generate_cache_key(source_id, style, lang):
    unique_string = f"{source_id}_{style}_{lang}"
    return hashlib.md5(unique_string.encode()).hexdigest()

def check_cache(cache_key):
    if not firebase_admin._apps: return None
    doc_ref = db.collection('radios').document(cache_key)
    doc = doc_ref.get()
    if doc.exists: return doc.to_dict()
    return None

def save_to_cache(cache_key, audio_data, source_info, style, lang, title):
    if not firebase_admin._apps: return None
    # Firebase Storageへ保存
    blob = bucket.blob(f"audio/{cache_key}.mp3")
    blob.upload_from_string(audio_data, content_type="audio/mp3")
    blob.make_public()
    audio_url = blob.public_url

    # Firestoreへメタデータ保存
    doc_ref = db.collection('radios').document(cache_key)
    doc_ref.set({
        'source': source_info,
        'style': style,
        'language': lang,
        'title': title,
        'audio_url': audio_url,
        'created_at': firestore.SERVER_TIMESTAMP
    })
    return audio_url

def get_style_config(style_key, language):
    # 基本設定
    config = {
        "prompt_role": f"【役割】A:メインMC B:アシスタント 口調:{language}の標準的ニュース。落ち着いたトーンで。",
        "voice_a": "onyx", "voice_b": "nova", # onyx:低音男性, nova:女性
        "speed": 1.0
    }
    
    if style_key == "jk":
        # JKは早口（1.15倍）にし、shimmer(ハスキー)をやめてalloy(中性)を採用
        config = {
            "prompt_role": "【役割】A:元気なJK(ボケ) B:冷静なJK(ツッコミ) 口調:『〜だし！』『マジで？』等のタメ口。短文でテンポよく。",
            "voice_a": "nova", "voice_b": "alloy",
            "speed": 1.15
        }
    elif style_key == "comedian":
        # 芸人は勢い重視で少し速く
        config = {
            "prompt_role": "【役割】A:ボケ(ハイテンション) B:ツッコミ(鋭く) 口調:関西弁や漫才口調。掛け合いを早く。",
            "voice_a": "echo", "voice_b": "onyx",
            "speed": 1.1
        }
    elif style_key == "okayama":
        config = {
            "prompt_role": "【役割】A,B:岡山出身の女性。口調:『〜じゃが』『〜だけぇ』等の岡山弁。親しみやすく。",
            "voice_a": "nova", "voice_b": "alloy",
            "speed": 1.05
        }
    elif style_key == "university":
        config = {
            "prompt_role": "【役割】A:男子大学生 B:女子大学生 口調:敬語混じりのカジュアルな会話。サークル棟での会話風。",
            "voice_a": "fable", "voice_b": "nova", # fable:若め男性
            "speed": 1.1
        }
    return config

# コンテンツ取得関数（URL用）
def fetch_content_from_url(url, openai_api_key):
    if "youtube.com" in url or "youtu.be" in url:
        # YouTube処理
        parsed = urlparse(url)
        if "youtube.com" in parsed.netloc: video_id = parse_qs(parsed.query).get("v", [None])[0]
        elif "youtu.be" in parsed.netloc: video_id = parsed.path[1:]
        else: video_id = None
        
        if not video_id: return "Error: Video ID not found"
        try:
            ts = YouTubeTranscriptApi.get_transcript(video_id, languages=['ja','en'])
            return f"【YouTube(字幕)】\n{' '.join([t['text'] for t in ts])[:5000]}..."
        except:
            return "字幕が見つかりませんでした。"
    else:
        # Web記事処理
        try:
            res = requests.get(url, timeout=10)
            res.encoding = res.apparent_encoding
            soup = BeautifulSoup(res.text, 'html.parser')
            title = soup.title.string if soup.title else "Web記事"
            return f"【Web記事：{title}】\n{' '.join([p.text for p in soup.find_all('p')])[:5000]}..."
        except: return f"Error: {url}"

# PDF読み込み関数
def extract_text_from_pdf(uploaded_file):
    try:
        reader = PyPDF2.PdfReader(uploaded_file)
        text = ""
        for page in reader.pages:
            text += page.extract_text()
        return f"【PDF資料：{uploaded_file.name}】\n{text[:10000]}..." # 文字数制限
    except Exception as e:
        return f"PDF読み込みエラー: {e}"

# ---------------------------
# メイン画面
# ---------------------------
st.title("📻 WebRadio Maker")
st.caption("公的情報や社内資料を、AIが聞きやすいラジオ番組にします。")

# 設定エリア
st.markdown("##### ⚙️ 番組の設定")
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
st.markdown("---")

# ★入力モード切替
input_mode = st.radio("入力ソースを選択", ["URL (記事・動画)", "PDF (資料アップロード)"], horizontal=True)

content_text = ""
source_id = ""
title_str = "ラジオ番組"
allow_cache = True
ready_to_generate = False

# ---------------------------
# モードA：URL入力
# ---------------------------
if input_mode == "URL (記事・動画)":
    url_input = st.text_input("記事または動画のURL", placeholder="https://...")
    
    if url_input:
        source_id = url_input
        # ★判定ロジック
        if is_safe_domain(url_input):
            st.success("✅ 公的機関・教育機関等のドメインを確認しました。通常モードで生成可能です。")
            ready_to_generate = True
            allow_cache = True
        else:
            # ⚠️ 警告モード
            st.warning("⚠️ 公的機関以外のドメインが検出されました")
            st.info("""
            **【確認事項】**
            入力されたURLは公的機関のものではありません。著作権および利用規約を遵守するため、以下の条件に同意する場合のみ利用可能です。
            
            1. **私的利用**（個人での学習・情報収集）に限ること。
            2. 生成された音声を**SNS等で公開・配布しない**こと。
            3. **キャッシュ機能（0秒再生）は無効**になります（サーバーに保存されません）。
            """)
            agree = st.checkbox("上記に同意し、自己責任で生成します")
            if agree:
                ready_to_generate = True
                allow_cache = False # キャッシュOFF
            else:
                ready_to_generate = False

# ---------------------------
# モードB：PDFアップロード
# ---------------------------
elif input_mode == "PDF (資料アップロード)":
    uploaded_file = st.file_uploader("PDFファイルをアップロード", type="pdf")
    
    if uploaded_file:
        source_id = uploaded_file.name + str(uploaded_file.size)
        title_str = uploaded_file.name
        
        st.markdown("**この資料の種類を選択してください：**")
        doc_type = st.radio("資料タイプ", 
            ["公的機関の資料・広報物（国・自治体など）", 
             "社内資料・自分自身の著作物", 
             "その他（第三者の著作物・ニュース等）"],
            index=None
        )
        
        if doc_type == "公的機関の資料・広報物（国・自治体など）" or doc_type == "社内資料・自分自身の著作物":
            st.success("✅ 権利確認OK。通常モードで生成可能です。")
            ready_to_generate = True
            allow_cache = True
        elif doc_type == "その他（第三者の著作物・ニュース等）":
            st.warning("⚠️ 第三者の著作物が選択されました")
            st.info("私的利用の範囲内でのみ利用可能です。キャッシュ機能は無効化されます。")
            agree_pdf = st.checkbox("利用規約・著作権を遵守し、自己責任で生成します")
            if agree_pdf:
                ready_to_generate = True
                allow_cache = False # キャッシュOFF
            else:
                ready_to_generate = False

# ---------------------------
# 生成ボタンと実行ロジック
# ---------------------------
if ready_to_generate:
    btn_label = "🎙️ 番組を再生する" if allow_cache else "🎙️ 番組を再生する（保存なしモード）"
    
    if st.button(btn_label, use_container_width=True):
        style_config = get_style_config(style_key, language)
        cache_key = generate_cache_key(source_id, style_key, language)
        
        # キャッシュ確認
        cached_data = None
        if allow_cache:
            cached_data = check_cache(cache_key)
        
        if cached_data:
            st.success(f"♻️ キャッシュから再生します！\nタイトル: {cached_data.get('title', '無題')}")
            st.audio(cached_data['audio_url'], format="audio/mp3")
        
        else:
            # 新規生成プロセス
            try:
                # 1. コンテンツ取得
                with st.spinner("🐢 資料を読み込んでいます..."):
                    if input_mode == "URL (記事・動画)":
                        content_text = fetch_content_from_url(url_input, openai_key)
                        if "【Web記事：" in content_text:
                            title_str = content_text.split("【Web記事：")[1].split("】")[0]
                    else:
                        content_text = extract_text_from_pdf(uploaded_file)
                
                # 2. 台本作成
                with st.spinner("✍️ AIが構成を考えています..."):
                    genai.configure(api_key=gemini_key)
                    # ★ここで診断リストにあった最新モデルを指定
                    model = genai.GenerativeModel('gemini-flash-latest')
                    
                    source_statement = ""
                    if input_mode == "PDF (資料アップロード)":
                        source_statement = f"冒頭で『この放送は、資料 {title_str} を元にAIが作成しました』と明言すること。"
                    
                    prompt = f"""
                    以下の情報を元にラジオ台本を作成してください。
                    {style_config['prompt_role']}
                    {source_statement}
                    
                    【重要：出力形式】
                    - 表形式は禁止。会話文のみ箇条書き。
                    - 専門用語はわかりやすく噛み砕くこと。
                    - 事実関係（数字・日付）は正確に。
                    
                    【構成】OP→本題→ED。5分程度。
                    
                    【入力データ】
                    {content_text}
                    """
                    script_text = model.generate_content(prompt).text
                    # UI修正：デフォルトは閉じた状態で、クリックで開くように設定
                    with st.expander("📝 生成された台本をチェックする（クリックで開閉）", expanded=False):st.write(script_text)
                        
                # 3. 音声合成
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
                                res = client.audio.speech.create(model="tts-1", voice=voice, input=text_content, speed=style_config['speed'])
                                combined_audio += res.content
                            except: pass
                
                if len(combined_audio) == 0:
                    st.error("⚠️ 音声生成に失敗しました。")
                else:
                    # 4. 保存と再生
                    if allow_cache:
                        with st.spinner("💾 クラウドに保存中..."):
                            audio_url = save_to_cache(cache_key, combined_audio, source_id, style_key, language, title_str)
                        st.success("🎉 完成！")
                        st.audio(audio_url, format="audio/mp3")
                    else:
                        st.success("🎉 完成！（保存なしモード）")
                        st.warning("⚠️ この音声は保存されていません。ページを閉じると消えます。")
                        st.audio(combined_audio, format="audio/mp3")

            except Exception as e:
                st.error(f"エラーが発生しました: {e}")
