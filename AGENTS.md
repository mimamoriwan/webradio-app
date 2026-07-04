# AGENTS.md

This file defines standing instructions for Codex and other coding agents working on this repository.

## Session Startup

At the start of every new development session, read these files before planning or editing:

1. `AGENTS.md`
2. `DEVELOPMENT_LOG.md`

`AGENTS.md` is the repository rulebook. `DEVELOPMENT_LOG.md` is the development history and current project state. Use both files together so new sessions understand what has already been built, what must not be broken, and what the next likely work items are.

Also read `README.md` when you need setup commands, dependency notes, or local run instructions.

## Project

This is a Streamlit app for creating podcast-style radio episodes.

Current main workflow:

- Use an article URL or PDF as reference text.
- Upload NotebookLM-generated main audio.
- Add intro, outro, and optional BGM.
- Export the finished episode as MP3.

The current primary mode is:

- `NotebookLM音声を番組化`

Do not remove the legacy URL/PDF full-program generation flow unless explicitly instructed.

## Repository Checks Before Editing

Before editing files, run:

```bash
pwd
git status --short --branch
git log --oneline -5
git diff --stat
```

If there are existing uncommitted changes, inspect them before editing. Do not overwrite user changes.

## Secret Handling

Never print, expose, copy, or commit secrets.

Do not display the contents of:

- `firebase_key.json`
- `.streamlit/secrets.toml`
- API keys
- tokens
- credentials

If secret-related files are needed for local execution, only check whether they exist. Do not print their contents.

## Files That Must Not Be Committed

Do not commit generated audio, local runtime files, virtual environments, or secrets.

Examples:

- `.DS_Store`
- `radio_output.mp3`
- `final_episode.mp3`
- `tmp_audio/`
- `.venv/`
- `.streamlit/secrets.toml`
- `firebase_key.json`

If any of these appear in `git status`, do not stage them.

## Main Files

Important files include:

- `app.py`
- `audio_mixer.py`
- `README.md`
- `DEVELOPMENT_LOG.md`
- `AGENTS.md`

## Current Important Behavior

NotebookLM mode should support:

- Main audio: MP3 / M4A
- BGM audio: MP3 / M4A / WAV
- Final output: MP3

`audio_mixer.combine_intro_main_outro(...)` must remain compatible with `main_format`.

If Streamlit still shows old behavior after a code change, restart Streamlit.

## Legacy Behavior

Keep `combine_audio_with_ma(...)` intact unless explicitly instructed, because it supports the old full-program generation flow.

Do not remove the old URL/PDF generation mode unless explicitly instructed.

## Development Rules

- Prefer small, focused changes.
- Avoid large refactors unless requested.
- Preserve existing working behavior.
- When fixing a bug, identify the likely cause and make the smallest safe change.
- Test both the changed path and nearby existing paths.
- When adding audio format support, verify both UI upload restrictions and actual mixer decoding.

## Verification After Changes

After code changes, run:

```bash
git diff --stat
git diff --check
python3 -m py_compile app.py audio_mixer.py
```

When the change affects Streamlit UI or audio generation, also verify through the actual Streamlit screen.

Local run command:

```bash
.venv/bin/python -m streamlit run app.py --server.port 49152
```

Open:

```text
http://localhost:49152
```

## Before Commit

Before committing, check:

```bash
git status --short --branch
git diff --stat
git diff --check
```

Confirm that generated audio files, secrets, and local runtime files are not staged.

## DEVELOPMENT_LOG.md Updates

Update `DEVELOPMENT_LOG.md` when:

- A new feature is added.
- A major bug is fixed.
- A behavior or workflow changes.
- A known issue or workaround is discovered.
- A new next-phase candidate is identified.

## Commit Policy

Use clear, concise commit messages.

Examples:

- `NotebookLM本編音声のM4Aアップロードに対応`
- `M4A本編音声の読み込み形式推定を安定化`
- `開発ログとCodex作業ルールを追加`

Do not push unless explicitly instructed.

## Communication

When reporting back, include:

- What changed
- What was tested
- Whether files were committed
- Current `git status --short --branch`
- Any remaining risks or next actions
