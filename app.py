import streamlit as st
import google.generativeai as genai
from openai import OpenAI
import requests
from bs4 import BeautifulSoup
import time
import os
import hashlib
import re
import json
from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs
import yt_dlp
import firebase_admin
from firebase_admin import credentials, firestore, storage
import PyPDF2
import io
import base64 # ★追加：iPhone対策の切り札
import audio_mixer # ★これを追加！

# ---------------------------
# 基本設定
# ---------------------------
st.set_page_config(page_title="WebRadio", page_icon="📻", initial_sidebar_state="collapsed")

# ==========================================
# 🎨 UIクリーニング（余計なアイコンを消す）
# ==========================================
hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            .stDeployButton {display:none;}
            [data-testid="stToolbar"] {visibility: hidden !important;}
            [data-testid="stDecoration"] {visibility: hidden !important;}
            [data-testid="stStatusWidget"] {visibility: hidden !important;}
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

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
def is_safe_domain(url):
    try:
        domain = urlparse(url).netloc
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
    blob = bucket.blob(f"audio/{cache_key}.mp3")
    blob.upload_from_string(audio_data, content_type="audio/mp3")
    blob.make_public()
    audio_url = blob.public_url

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
    config = {
        "prompt_role": f"【役割】A:メインMC B:アシスタント 口調:{language}の標準的ニュース。落ち着いたトーンで。",
        "voice_a": "onyx", "voice_b": "nova",
        "speed": 1.0
    }

    if style_key == "jk":
        config = {
            "prompt_role": "【役割】A:元気なJK(ボケ) B:冷静なJK(ツッコミ) 口調:『〜だし！』『マジで？』等のタメ口。短文でテンポよく。",
            "voice_a": "nova", "voice_b": "alloy",
            "speed": 1.15
        }
    elif style_key == "comedian":
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
            "voice_a": "fable", "voice_b": "nova",
            "speed": 1.1
        }
    return config

def fetch_content_from_url(url, openai_api_key):
    if "youtube.com" in url or "youtu.be" in url:
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
        try:
            res = requests.get(url, timeout=10)
            res.encoding = res.apparent_encoding
            soup = BeautifulSoup(res.text, 'html.parser')
            title = soup.title.string if soup.title else "Web記事"
            return f"【Web記事：{title}】\n{' '.join([p.text for p in soup.find_all('p')])[:5000]}..."
        except: return f"Error: {url}"

def extract_text_from_pdf(uploaded_file):
    try:
        reader = PyPDF2.PdfReader(uploaded_file)
        text = ""
        for page in reader.pages:
            text += page.extract_text()
        return f"【PDF資料：{uploaded_file.name}】\n{text[:10000]}..."
    except Exception as e:
        return f"PDF読み込みエラー: {e}"

def is_content_fetch_error(content_text):
    if not content_text:
        return True
    error_markers = ["Error:", "PDF読み込みエラー", "字幕が見つかりませんでした。"]
    return any(content_text.startswith(marker) for marker in error_markers)

def parse_json_response(response_text):
    cleaned = response_text.strip()
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError("JSON not found")
        return json.loads(match.group(0))

def generate_intro_outro(model, content_text, program_name, tone, language, episode_length="short"):
    length_guides = {
        "short": {
            "label": "ショート版",
            "summary_rule": "記事の概要と全体像が短時間でつかめる紹介文にすること。",
            "intro_guide": "このショート版では、まず記事の概要を整理しながら、全体像をつかみやすくお届けします。",
            "focus_fallback": "記事の概要と全体像"
        },
        "long": {
            "label": "ロング版",
            "summary_rule": "テーマの背景、問題点、影響、考えるべき論点が伝わる紹介文にすること。",
            "intro_guide": "このロング版では、背景にある問題点や論点にも踏み込みながら、テーマをじっくり深掘りしていきます。",
            "focus_fallback": "背景にある問題点や論点"
        }
    }
    length_config = length_guides.get(episode_length, length_guides["short"])

    prompt = f"""
    以下の参考本文から、ラジオ番組「ミマモリワン」で紹介する今回のテーマと短い紹介文だけを抽出してください。

    【JSON形式】
    {{
      "theme": "今回のテーマを20文字程度で",
      "summary": "今回のテーマについて、リスナーに向けた短い紹介文を80文字程度で"
    }}

    【ルール】
    - 出力はJSONのみ。Markdownは使わないこと。
    - 本編台本、冒頭挨拶、締め挨拶は作らないこと。
    - 日本語で自然に書くこと。
    - {length_config["label"]}として、{length_config["summary_rule"]}

    【参考本文】
    {content_text[:8000]}
    """
    response_text = model.generate_content(prompt).text
    data = parse_json_response(response_text)
    theme = str(data.get("theme", "")).strip() or "今回のテーマ"
    summary = str(data.get("summary", "")).strip() or f"今回は、{length_config['focus_fallback']}をわかりやすく見つめていきます。"

    intro_text = f"""
    みなさんこんにちは。ミマモリワンのラジオのお時間がやってきました。

    この番組では、DJのヤスシが日常生活の中で気になったニュースや新聞記事などについて、独自の調査を踏まえて深掘りしていきます。

    今日の放送が、あなたの経験や知識をちょっとだけ豊かにするきっかけになればうれしいです。

    さて、今回のミマモリワンでは、{theme}についてご紹介します。

    {summary}

    {length_config["intro_guide"]}

    それでは、本編をお楽しみください。
    """.strip()

    outro_text = """
    さて、本日のミマモリワンはいかがでしたでしょうか。

    今回の放送が、あなたにとって少しでもお役に立つ番組となっていればうれしいです。

    今後も、日常生活の中で気になったニュースや話題を、わかりやすく深掘りしてお届けしていきます。

    それでは、また次回をお楽しみに。
    """.strip()

    return intro_text, outro_text

def write_tts_mp3(client_openai, text, output_path, voice="alloy", speed=1.0):
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    response = client_openai.audio.speech.create(
        model="tts-1",
        voice=voice,
        input=text,
        speed=speed
    )
    with open(output_path, "wb") as f:
        f.write(response.content)
    return output_path

def write_uploaded_audio_file(uploaded_file, output_path):
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(output_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return output_path

def render_notebook_result(audio_path, intro_text, outro_text):
    st.audio(audio_path, format="audio/mpeg")

    with open(audio_path, "rb") as f:
        final_audio = f.read()

    st.download_button(
        "完成MP3をダウンロード",
        data=final_audio,
        file_name="final_episode.mp3",
        mime="audio/mpeg",
        use_container_width=True
    )

    st.divider()
    with st.expander("📝 生成された冒頭挨拶・締め挨拶を確認する", expanded=False):
        st.markdown("**冒頭挨拶**")
        st.write(intro_text)
        st.markdown("**締め挨拶**")
        st.write(outro_text)

def login_user(email, password):
    # secrets.toml からAPIキーを取得
    api_key = st.secrets.get("FIREBASE_WEB_API_KEY")
    if not api_key:
        # 念のため firebase セクションも探すなどのフォールバックがあってもよいが
        # 今回は指定通り FIREBASE_WEB_API_KEY を使用
        return None

    request_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
    payload = {"email": email, "password": password, "returnSecureToken": True}

    try:
        response = requests.post(request_url, json=payload)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except:
        return None

def register_user(email, password):
    # secrets.toml からAPIキーを取得
    api_key = st.secrets.get("FIREBASE_WEB_API_KEY")
    if not api_key:
        return None

    request_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={api_key}"
    payload = {"email": email, "password": password, "returnSecureToken": True}

    try:
        response = requests.post(request_url, json=payload)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except:
        return None

# ---------------------------
# ログイン管理 & サイドバー表示
# ---------------------------
if 'is_logged_in' not in st.session_state:
    st.session_state['is_logged_in'] = False
if 'user_email' not in st.session_state:
    st.session_state['user_email'] = ""

with st.sidebar:
    with st.expander("👤 アカウント設定", expanded=False):
        if st.session_state['is_logged_in']:
            st.caption("ログイン中")
            st.write(st.session_state['user_email'])
            if st.button("ログアウト"):
                st.session_state['is_logged_in'] = False
                st.session_state['user_email'] = ""
                st.rerun()
        else:
            tab1, tab2 = st.tabs(["ログイン", "新規登録"])

            with tab1:
                with st.form("login_form"):
                    email = st.text_input("メールアドレス", key="login_email")
                    password = st.text_input("パスワード", type="password", key="login_pass")
                    submit_login = st.form_submit_button("ログイン")

                    if submit_login:
                        user = login_user(email, password)
                        if user:
                            st.session_state['is_logged_in'] = True
                            st.session_state['user_email'] = email
                            st.success("成功！")
                            st.rerun()
                        else:
                            st.error("失敗しました")

            with tab2:
                with st.form("register_form"):
                    new_email = st.text_input("メールアドレス", key="reg_email")
                    new_password = st.text_input("パスワード", type="password", key="reg_pass")
                    submit_reg = st.form_submit_button("新規登録")

                    if submit_reg:
                        user = register_user(new_email, new_password)
                        if user:
                            st.session_state['is_logged_in'] = True
                            st.session_state['user_email'] = new_email
                            st.success("登録完了！")
                            st.rerun()
                        else:
                            st.error("登録に失敗しました")

# ---------------------------
# メイン画面 (ログイン有無に関わらず表示)
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

# 入力モード切替
input_mode = st.radio("入力ソースを選択", ["URL (記事・動画)", "PDF (資料アップロード)", "NotebookLM音声を番組化"], horizontal=True)

content_text = ""
source_id = ""
title_str = "ラジオ番組"
allow_cache = True
ready_to_generate = False
notebook_source_type = "URL"
notebook_url_input = ""
notebook_pdf_file = None
notebook_main_audio_file = None
notebook_bgm_file = None
notebook_bgm_gain_db = -15
notebook_program_name = "ミマモリワン"
notebook_tone = "落ち着いたニュース解説"
notebook_episode_length = "short"

# モードA：URL入力
if input_mode == "URL (記事・動画)":
    url_input = st.text_input("記事または動画のURL", placeholder="https://...")
    
    if url_input:
        source_id = url_input
        if is_safe_domain(url_input):
            st.success("✅ 公的機関・教育機関等のドメインを確認しました。通常モードで生成可能です。")
            ready_to_generate = True
            allow_cache = True
        else:
            st.warning("⚠️ 公的機関以外のドメインが検出されました")
            st.info("""
            **【確認事項】**
            入力されたURLは公的機関のものではありません。著作権および利用規約を遵守するため、以下の条件に同意する場合のみ利用可能です。
            1. **私的利用**（個人での学習・情報収集）に限ること。
            2. 生成された音声を**SNS等で公開・配布しない**こと。
            3. **キャッシュ機能（0秒再生）は無効**になります。
            """)
            agree = st.checkbox("上記に同意し、自己責任で生成します")
            if agree:
                ready_to_generate = True
                allow_cache = False
            else:
                ready_to_generate = False

# モードB：PDFアップロード
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
                allow_cache = False
            else:
                ready_to_generate = False

# モードC：NotebookLM音声を番組化
elif input_mode == "NotebookLM音声を番組化":
    st.markdown("##### NotebookLM本編MP3をラジオ番組として仕上げる")
    notebook_source_type = st.radio("本文ソース", ["URL", "PDF"], horizontal=True, key="notebook_source_type")

    if notebook_source_type == "URL":
        notebook_url_input = st.text_input("記事URL", placeholder="https://...", key="notebook_url_input")
    else:
        notebook_pdf_file = st.file_uploader("PDFファイルをアップロード", type="pdf", key="notebook_pdf_file")

    notebook_main_audio_file = st.file_uploader("NotebookLMで生成した本編音声（MP3・M4A）", type=["mp3", "m4a"], key="notebook_main_audio")
    notebook_bgm_file = st.file_uploader("BGM音源（任意 / MP3・M4A・WAV）", type=["mp3", "m4a", "wav"], key="notebook_bgm_file")
    st.caption("DOVA-SYNDROMEなど、利用条件を確認済みのBGM素材をアップロードしてください。BGMは番組全体に薄く重ねます。")
    if notebook_bgm_file is not None:
        notebook_bgm_gain_db = st.slider("BGM音量", min_value=-40, max_value=-10, value=-15, step=1, format="%d dB")
    notebook_program_name = st.text_input("番組名", value="ミマモリワン", key="notebook_program_name")
    notebook_tone = st.selectbox(
        "番組トーン",
        ["落ち着いたニュース解説", "親しみやすいラジオ風", "深掘りレポート風", "やさしい雑談風"],
        key="notebook_tone"
    )
    st.caption("NotebookLMモードでは、MVPとして日本語のミマモリワン用テンプレートを優先します。番組トーンは今後の拡張予定です。")
    episode_length_options = {
        "short": "ショート版（概要と全体像）",
        "long": "ロング版（問題点まで深掘り）"
    }
    notebook_episode_length = st.radio(
        "番組の長さ",
        options=list(episode_length_options.keys()),
        format_func=lambda x: episode_length_options[x],
        horizontal=True,
        key="notebook_episode_length"
    )
    if notebook_episode_length == "short":
        st.caption("記事の概要を説明しつつ、全体像をつかみやすい冒頭案内にします。")
    else:
        st.caption("背景にある問題点や論点にも触れ、じっくり深掘りする冒頭案内にします。")

# 生成ロジック
if input_mode == "NotebookLM音声を番組化":
    if st.button("🎙️ NotebookLM音声を番組化する", use_container_width=True):
        if notebook_source_type == "URL" and not notebook_url_input:
            st.error("URLまたはPDFを入力してください。")
            st.stop()
        if notebook_source_type == "PDF" and notebook_pdf_file is None:
            st.error("URLまたはPDFを入力してください。")
            st.stop()
        if notebook_main_audio_file is None:
            st.error("NotebookLMで生成した本編音声をアップロードしてください。")
            st.stop()
        if not gemini_key:
            st.error("Gemini APIキーが未設定です。")
            st.stop()
        if not openai_key:
            st.error("OpenAI APIキーが未設定です。")
            st.stop()

        # 1. コンテンツ取得
        with st.spinner("🐢 本文を読み込んでいます..."):
            try:
                if notebook_source_type == "URL":
                    content_text = fetch_content_from_url(notebook_url_input, openai_key)
                    if "【Web記事：" in content_text:
                        title_str = content_text.split("【Web記事：")[1].split("】")[0]
                    else:
                        title_str = notebook_program_name
                else:
                    content_text = extract_text_from_pdf(notebook_pdf_file)
                    title_str = notebook_pdf_file.name
            except Exception:
                st.error("本文取得に失敗しました。URLまたはPDFを確認してください。")
                st.stop()

            if is_content_fetch_error(content_text):
                st.error("本文取得に失敗しました。URLまたはPDFを確認してください。")
                st.stop()

        # 2. intro/outro生成
        with st.spinner("✍️ 冒頭挨拶と締め挨拶を作成しています..."):
            try:
                genai.configure(api_key=gemini_key)
                model = genai.GenerativeModel('gemini-2.5-flash')
                intro_text, outro_text = generate_intro_outro(
                    model,
                    content_text,
                    notebook_program_name,
                    notebook_tone,
                    language,
                    notebook_episode_length
                )
            except Exception:
                st.error("Geminiによる冒頭挨拶・締め挨拶の生成に失敗しました。")
                st.stop()

        # 3. intro/outroをTTS化
        with st.spinner("🎙️ 冒頭挨拶と締め挨拶を音声化しています..."):
            try:
                client = OpenAI(api_key=openai_key)
                intro_path = os.path.join("tmp_audio", "intro.mp3")
                outro_path = os.path.join("tmp_audio", "outro.mp3")
                write_tts_mp3(client, intro_text, intro_path, voice="alloy", speed=1.0)
                write_tts_mp3(client, outro_text, outro_path, voice="alloy", speed=1.0)
            except Exception:
                st.error("OpenAI TTSによる音声生成に失敗しました。")
                st.stop()

        # 4. 音声結合
        with st.spinner("🎚️ 1本の番組MP3に仕上げています..."):
            try:
                main_extension = os.path.splitext(notebook_main_audio_file.name)[1].lower()
                main_audio_path = os.path.join("tmp_audio", f"notebook_main{main_extension}")
                write_uploaded_audio_file(notebook_main_audio_file, main_audio_path)
                main_format = main_extension.lstrip(".")
                if main_format == "m4a":
                    main_format = "mp4"

                bgm_path = None
                bgm_format = None
                if notebook_bgm_file is not None:
                    bgm_extension = os.path.splitext(notebook_bgm_file.name)[1].lower()
                    bgm_path = os.path.join("tmp_audio", f"bgm_source{bgm_extension}")
                    write_uploaded_audio_file(notebook_bgm_file, bgm_path)
                    bgm_format = bgm_extension.lstrip(".")
                    if bgm_format == "m4a":
                        bgm_format = "mp4"

                output_filename = audio_mixer.combine_intro_main_outro(
                    intro_path,
                    main_audio_path,
                    outro_path,
                    silence_seconds=2.5,
                    output_path="final_episode.mp3",
                    bgm_audio=bgm_path,
                    bgm_gain_db=notebook_bgm_gain_db,
                    bgm_format=bgm_format,
                    main_format=main_format,
                    bgm_tail_seconds=5.0
                )
            except Exception as e:
                st.error("音声結合に失敗しました。")
                with st.expander("エラー詳細"):
                    st.exception(e)
                st.stop()

        st.session_state["notebook_final_audio_path"] = output_filename
        st.session_state["notebook_intro_text"] = intro_text
        st.session_state["notebook_outro_text"] = outro_text
        st.success("🎉 NotebookLM音声の番組化が完了しました！")

    if "notebook_final_audio_path" in st.session_state:
        render_notebook_result(
            st.session_state["notebook_final_audio_path"],
            st.session_state.get("notebook_intro_text", ""),
            st.session_state.get("notebook_outro_text", "")
        )

elif ready_to_generate:
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
            # 新規生成
            try:
                # 1. コンテンツ取得
                with st.spinner("🐢 資料を読み込んでいます..."):
                    if input_mode == "URL (記事・動画)":
                        content_text = fetch_content_from_url(url_input, openai_key)
                        if "【Web記事：" in content_text:
                            title_str = content_text.split("【Web記事：")[1].split("】")[0]
                    else:
                        # ▼▼▼【ここが修正版！】▼▼▼
                        # PDFの文字数チェック機能を追加
                        pdf_reader = PyPDF2.PdfReader(uploaded_file)
                        text = ""
                        for page in pdf_reader.pages:
                            text += page.extract_text()
                        
                        st.info(f"🔍 デバッグ: PDFから読み取れた文字数は **{len(text)} 文字** です")
                        
                        if len(text) == 0:
                            st.error("⚠️ エラー: 文字が読み取れませんでした。このPDFは「画像（スキャンデータ）」ではありませんか？ 現在の仕組みでは画像PDFは読めません。")
                            st.stop() # ここで強制ストップ
                        
                        content_text = f"【PDF資料：{uploaded_file.name}】\n{text[:10000]}..."
                        # ▲▲▲【ここまで】▲▲▲
                
                # 2. 台本作成
                with st.spinner("✍️ AIが構成を考えています..."):
                    genai.configure(api_key=gemini_key)
                    model = genai.GenerativeModel('gemini-2.5-flash')
                    
                    source_statement = ""
                    if input_mode == "PDF (資料アップロード)":
                        source_statement = f"冒頭で『この放送は、資料 {title_str} を元にAIが作成しました』と明言すること。"
                    
                    prompt = f"""
                    以下の情報を元にラジオ台本を作成してください。
                    {style_config['prompt_role']}
                    {source_statement}
                    
                    【重要：出力形式】
                    - 各行は「A: セリフ」「B: セリフ」の形式で書くこと。
                    - 箇条書きの記号（・や*）は使わないこと。
                    - ト書き（笑いや拍手など）は書かないこと。
                    - 専門用語はわかりやすく噛み砕くこと。
                    
                    【構成】OP→本題→ED。5分程度。
                    
                    【入力データ】
                    {content_text}
                    """
                    script_text = model.generate_content(prompt).text

                # 3. 音声合成
                with st.spinner("🎙️ 収録中（間を調整しています）..."):
                    client = OpenAI(api_key=openai_key)
                    lines = script_text.split('\n')
                    
                    # ミキサーに渡すためのデータリストを作成
                    script_data_list = []
                    
                    for line in lines:
                        line = line.strip()
                        if not line: continue
                        
                        # クリーニング処理
                        clean_line = re.sub(r'^[\*\-・\s]+', '', line)
                        clean_line = clean_line.replace('**', '')
                        
                        parts = re.split('[:：]', clean_line, 1)
                        
                        voice = None
                        text_content = ""

                        # 話者判定と声の割り当て
                        if len(parts) >= 2:
                            speaker_part = parts[0].strip()
                            text_content = parts[1].strip()
                            if "A" in speaker_part or "Ａ" in speaker_part:
                                voice = style_config['voice_a']
                            elif "B" in speaker_part or "Ｂ" in speaker_part:
                                voice = style_config['voice_b']
                            else:
                                voice = style_config['voice_a']
                                text_content = clean_line
                        else:
                            voice = style_config['voice_a']
                            text_content = clean_line
                        
                        # リストに追加
                        if voice and text_content:
                            script_data_list.append({
                                "voice": voice,
                                "text": text_content
                            })

                    # ★ここでaudio_mixerを呼び出す！
                    if script_data_list:
                        try:
                            # ミキサー関数を実行（ファイルが生成される）
                            output_filename = audio_mixer.combine_audio_with_ma(
                                script_data_list, 
                                client, 
                                speed=style_config['speed']
                            )
                            
                            # 生成されたファイルを読み込んで combined_audio に入れる
                            with open(output_filename, "rb") as f:
                                combined_audio = f.read()
                                
                            # 一時ファイルは削除してもOK（今回は残しておいても上書きされるので放置でも可）
                            
                        except Exception as e:
                            st.error(f"Mixing Error: {e}")
                            combined_audio = b""
                    else:
                        combined_audio = b""
                        
                    # 4. 完了表示
                    if allow_cache:
                        # 保存ありモード（URL再生なのでiPhoneもOK）
                        with st.spinner("💾 クラウドに保存中..."):
                            audio_url = save_to_cache(cache_key, combined_audio, source_id, style_key, language, title_str)
                        st.success("🎉 完成！")
                        st.audio(audio_url, format="audio/mp3")
                    else:
                        # 保存なしモード（iPhoneでコケる鬼門）
                        st.success("🎉 完成！（保存なしモード）")
                        st.warning("⚠️ 著作権保護のためサーバーには保存されません。ダウンロードデータは**「私的利用（個人での視聴）」**に留め、**第三者への配布やSNSへのアップロードは絶対に行わないでください。**")
                        
                        # ★ここが最終兵器：Base64埋め込みプレーヤー
                        # データを文字列化してHTMLに直接書き込むことで、iPhoneでも強制的に再生させる
                        b64_audio = base64.b64encode(combined_audio).decode()
                        audio_html = f"""
                        <audio controls style="width: 100%;">
                            <source src="data:audio/mp3;base64,{b64_audio}" type="audio/mp3">
                            お使いのブラウザは音声再生に対応していません。
                        </audio>
                        """
                        st.markdown(audio_html, unsafe_allow_html=True)

                    # 台本表示
                    st.divider()
                    with st.expander("📝 生成された台本をチェックする（クリックで開閉）", expanded=False):
                        st.write(script_text)

            except Exception as e:
                st.error(f"エラーが発生しました: {e}")
