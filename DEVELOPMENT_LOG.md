# Webradio App Development Log

このファイルは、Codexなどで新しい開発セッションを始めるときに最初に確認するための開発記録です。

## Current Snapshot

- Main repository: `/Users/itokazuyasushi/Desktop/webradio-app`
- GitHub remote: `https://github.com/mimamoriwan/webradio-app.git`
- Main branch: `main`
- Primary current direction: NotebookLMで生成した本編音声をアップロードし、Webradio側で冒頭挨拶、締め挨拶、BGMを付けてラジオ番組化する
- Legacy direction kept for now: URL/PDFからWebradio側で番組全体を生成する旧機能は削除せず保留

As of 2026-07-05, local `main` is ahead of `origin/main` by two commits:

```text
764d5d4 M4A本編音声の読み込み形式推定を安定化
03d0182 NotebookLM本編音声のM4Aアップロードに対応
```

## Read This First In New Sessions

1. Check the current repository and branch.

```bash
pwd
git status --short --branch
git log --oneline -5
```

2. Do not display secret values.

Never print the contents of:

- `firebase_key.json`
- `.streamlit/secrets.toml`
- API keys or tokens

3. Do not commit generated audio or local runtime files.

These should stay out of Git:

- `.DS_Store`
- `radio_output.mp3`
- `final_episode.mp3`
- `tmp_audio/`
- `.venv/`
- `.streamlit/secrets.toml`

## App Summary

WebRadio is a Streamlit app. The current MVP focus is the `NotebookLM音声を番組化` mode.

NotebookLM mode inputs:

- Article URL or PDF, used only as reference text for intro/outro theme extraction
- NotebookLM main audio, currently MP3 or M4A
- Optional BGM audio, currently MP3, M4A, or WAV
- Program name, defaulting to `ミマモリワン`
- Program tone UI, currently treated as future extension

NotebookLM mode output:

- `final_episode.mp3`
- Streamlit audio playback
- Streamlit download button

## Current NotebookLM Mode Flow

1. Read article URL or PDF text.
2. Generate only theme and short summary with Gemini.
3. Build fixed `ミマモリワン` intro/outro templates around that theme.
4. Generate intro/outro audio with OpenAI TTS.
5. Save uploaded NotebookLM main audio to `tmp_audio/`, preserving its extension.
6. Combine audio with `audio_mixer.combine_intro_main_outro(...)`.
7. Export finished MP3 as `final_episode.mp3`.

## Current Program Structure

BGMなし:

```text
intro
2.5秒無音
NotebookLM本編
2.5秒無音
outro
```

BGMあり:

```text
BGM開始
intro
BGMのみ 2.5秒
NotebookLM本編 + BGM
BGMのみ 2.5秒
outro + BGM
BGMのみ 5秒
終了
```

BGM settings:

- BGM is looped or cut to match the final program duration.
- BGM is faded in and faded out.
- Current UI default BGM volume: `-15 dB`
- Slider range: `-40 dB` to `-10 dB`

## Important Implementation Notes

### `app.py`

Key responsibilities:

- Streamlit UI
- Firebase login/sidebar UI
- URL/PDF text extraction
- Gemini prompt for theme and summary extraction
- Fixed `ミマモリワン` intro/outro template construction
- OpenAI TTS calls for intro/outro
- Saving uploaded audio into `tmp_audio/`
- Calling `audio_mixer.combine_intro_main_outro(...)`

NotebookLM main audio upload:

- Label: `NotebookLMで生成した本編音声（MP3・M4A）`
- Allowed types: `["mp3", "m4a"]`
- The uploaded file extension is preserved in `tmp_audio/notebook_main.<ext>`.
- The derived `main_format` is passed to `combine_intro_main_outro(...)`.

### `audio_mixer.py`

Keep `combine_audio_with_ma(...)` intact because it supports the old full-program generation flow.

`combine_intro_main_outro(...)` currently supports:

- intro audio: MP3
- main audio: MP3 or M4A via `main_format`
- outro audio: MP3
- BGM audio: MP3, M4A, or WAV via `bgm_format`
- final export: MP3

The function signature must accept `main_format`; otherwise Streamlit raises:

```text
TypeError: combine_intro_main_outro() got an unexpected keyword argument 'main_format'
```

If that error appears after code changes, restart Streamlit so Python reloads `audio_mixer.py`.

## Recent Development Timeline

### Repository preparation

Commit:

```text
30b9ace Prepare repository for Webradio v2 development
```

What changed:

- `.gitignore` safety cleanup
- README minimum development notes
- `.DS_Store` removed from Git tracking
- `radio_output.mp3` removed from Git tracking

### NotebookLM v2 MVP and full BGM support

Commit:

```text
225265a NotebookLM音声の番組化と全編BGM対応を追加
```

What changed:

- Added `NotebookLM音声を番組化` mode
- Added intro/outro generation
- Added upload flow for NotebookLM main audio
- Added optional BGM upload
- Added full-program BGM bed
- Added `ミマモリワン` intro/outro templates
- Confirmed real Streamlit generation, playback, and download

### NotebookLM main audio M4A support

Commit:

```text
03d0182 NotebookLM本編音声のM4Aアップロードに対応
```

What changed:

- NotebookLM main audio upload allows MP3 and M4A
- UI label no longer says MP3 only
- Main audio is saved with its original extension
- README notes that ffmpeg is needed for M4A decode

### M4A main audio format stabilization

Commit:

```text
764d5d4 M4A本編音声の読み込み形式推定を安定化
```

What changed:

- `combine_intro_main_outro(...)` accepts `main_format=None`
- If `main_format` is omitted, the mixer guesses format from the main audio file extension
- Verified local tests for:
  - MP3 main audio without BGM
  - M4A main audio without BGM
  - M4A main audio with MP3 BGM
  - M4A main audio with M4A BGM
  - M4A main audio with WAV BGM

## Local Run Commands

Use the project virtual environment when available:

```bash
cd /Users/itokazuyasushi/Desktop/webradio-app
.venv/bin/python -m streamlit run app.py --server.port 49152
```

Open:

```text
http://localhost:49152
```

If a previous Streamlit process is still running and old code appears to be loaded, stop and restart it.

## Verification Commands

Use these after code changes:

```bash
git status --short --branch
git diff --stat
git diff --check
python3 -m py_compile app.py audio_mixer.py
```

For `py_compile`, the environment may need permission to write `__pycache__`.

## Known Warnings

`google.generativeai` currently emits a deprecation warning:

```text
All support for the google.generativeai package has ended.
```

This is not currently blocking the MVP. Migration to `google.genai` is a future task.

## Known Non-goals For The MVP

- Do not remove the old URL/PDF full-program generation flow yet.
- Do not implement full tone/style variation yet.
- Do not add bundled BGM assets to the repository.
- Do not commit user-provided BGM or generated episode MP3 files.
- Do not implement loudness normalization yet.
- Do not implement jingles yet.

## Next Phase Candidates

- Push the two local M4A-related commits if they have not been pushed yet.
- Add a small automated mixer test file if the project starts accumulating more audio format changes.
- Consider migrating from `google.generativeai` to `google.genai`.
- Decide whether to keep, hide, or refactor the old URL/PDF generation mode.
- Improve loudness normalization for consistent BGM/main voice balance.
- Add a more explicit UI note that NotebookLM mode is the main recommended workflow.
