# webradio-app

WebRadio is a Streamlit app that turns web pages, YouTube transcripts, PDFs, and pasted text into short radio-style audio.

## Local development

Recommended runtime:

- Python 3.10 or later
- ffmpeg

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run locally:

```bash
streamlit run app.py
```

## Secrets

Create `.streamlit/secrets.toml` locally. Do not commit real secrets or service account keys.

Example keys only:

```toml
GEMINI_API_KEY = "..."
OPENAI_API_KEY = "..."
FIREBASE_WEB_API_KEY = "..."

[firebase]
type = "..."
project_id = "..."
private_key_id = "..."
private_key = "..."
client_email = "..."
client_id = "..."
auth_uri = "..."
token_uri = "..."
auth_provider_x509_cert_url = "..."
client_x509_cert_url = "..."
```

## Generated audio

Generated MP3 files such as `radio_output.mp3` are local build outputs and should not be committed. Keep fixed source audio, such as BGM or jingles, in a clearly named asset directory if they need to be versioned later.

## BGM usage

When adding BGM, use only audio files whose rights and usage conditions you have confirmed. If you use free music from services such as DOVA-SYNDROME, check the conditions on each track page before use. BGM source files are not included in this repository; the app is designed to export finished MP3 files that may include user-provided BGM.
