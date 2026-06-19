# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AutoCut — a web app that analyzes oral video recordings against a script, identifies the best takes, and exports Jianying (剪映) drafts with subtitles. The user uploads a video + script (one sentence per line), the backend runs ASR → LLM alignment → multi-analyzer quality grading, then the user reviews takes via a keyboard-driven UI and exports a剪映 draft, SRT subtitles, or a text clip guide.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Start the server (hot-reload)
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8520

# Run a test script (these are standalone, not automated tests)
python test_auth.py        # Test V3 ASR auth headers against the real API
python test_cluster.py     # Test V2 cluster names for SeedASR
python test_cluster2.py    # More cluster name testing against V2 endpoint
```

No test framework is configured. The three `test_*.py` files are standalone ASR connectivity experiments that hit the real Volcengine API directly.

## Architecture

```
frontend/          # Static SPA (vanilla JS, no build step)
  index.html       # Two-section layout: upload → editor; loads all JS/CSS from /static
  css/style.css
  js/
    app.js         # Upload, polling, rendering, confirm/reject/export, STATE singleton
    player.js      # Video element control, segment loop playback, seek
    timeline.js    # Canvas-based timeline bar showing sentence positions
    keyboard.js    # All keyboard shortcuts (arrows, Enter, Space, Ctrl+S, 1-9, etc.)

backend/
  main.py          # FastAPI app, CORS, static mounts, lifespan (creates dirs), route registration
  config.py        # Settings dataclass reading from .env via python-dotenv
  models/
    schemas.py     # Pydantic models: ASRSegment, AnalyzedTake, ScriptSentence, ProcessResult, etc.
  routes/
    upload.py      # POST /api/upload — video+script upload, kicks off background pipeline
    process.py     # GET /api/task/{id} — poll status/results; PUT confirm/reject endpoints
    export.py      # GET /api/export/{id}/draft|srt|text — export endpoints
  services/
    media.py       # ffmpeg/ffprobe wrapper: video info, audio extraction, segment concat/cut
    asr.py         # Volcengine WebSocket V3 ASR client (bigmodel) — binary protocol, chunked audio
    aligner.py     # LLM semantic alignment between script sentences and ASR segments; fallback: Levenshtein
    exporter.py    # Jianying draft JSON (+ pyJianYingDraft if available), SRT, text guide export
    analyzers/
      __init__.py  # Registry + run_all_analyzers() — runs each analyzer, then computes final grade
      base.py      # BaseAnalyzer, AnalysisContext, AnalysisResult (all dataclasses)
      abandoned.py    # Detects NG takes (abandon keywords, truncation, too-short, very low confidence)
      filler_words.py # Detects Chinese filler words (呃, 那个, etc.) and stutter
      confidence.py   # Scores based on ASR confidence
      fluency.py      # Speed analysis, stutter, long pauses, sentence-start hesitation
      script_match.py # Levenshtein ratio + keyword coverage vs script sentence
      grader.py       # Weighted aggregator: A/B/C/D/废 grade from all analyzer results
```

## Processing Pipeline

1. `POST /api/upload` — saves video, parses script lines, starts `process_video_task` as background task
2. **Extract audio** (`media.extract_audio`) — ffmpeg copies/encodes audio to M4A
3. **ASR** (`asr.VolcASRClient`) — WebSocket V3 to `wss://openspeech.bytedance.com/api/v3/sauc/bigmodel`; audio auto-converted to WAV, sent in chunks via binary protocol; returns timestamped utterance segments
4. **Align** (`aligner.LLMAligner`) — sends script + ASR segments to LLM (doubao-seed-2-0-pro) for semantic matching; falls back to Levenshtein distance (threshold 0.35)
5. **Analyze** (`analyzers.run_all_analyzers`) — runs all 5 analyzers per take, computes A/B/C/D/废 grade via weighted scoring
6. **Poll** — frontend polls `GET /api/task/{id}` every 2s until status = "done"
7. **Edit** — user reviews takes in three-panel layout (script list | video | take versions), confirms/rejects via keyboard or clicks
8. **Export** — confirmed takes assembled into剪映 draft JSON (with subtitle track), SRT, or text guide

## Key Design Points

- **No database** — tasks stored in an in-memory dict (`_tasks` in `upload.py`); lost on restart
- **Streaming ASR** — uses WebSocket V3 binary protocol; audio data sent in chunks directly, no public URL or cloud storage required. The async `transcribe()` is wrapped synchronously via `asyncio.run()` because the pipeline runs in a background thread
- **Analyzers are pluggable** — create a new `.py` in `analyzers/`, inherit `BaseAnalyzer`, `@register` it in `__init__.py`
- **LLM alignment prompt** is visible in `aligner.py:ALIGNMENT_PROMPT` — it asks the LLM to return JSON matching script indices to ASR segment indices
- **Frontend STATE singleton** in `app.js` holds all editing state; global functions (`selectSentence`, `confirmCurrent`, etc.) are called by keyboard/player modules directly
- **Subtitle splitting** — long sentences are split at punctuation boundaries, capped at `SUBTITLE_MAX_CHARS` (default 12)
- **Video playback** uses segment looping: when a take is selected, the player loops between its start/end times

## Credentials Warning

The `.env` file contains real Volcengine API credentials and should NEVER be committed. It is listed in `.gitignore` if present.
