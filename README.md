# AgentVideoForge

Agentic, multi-model pipeline that turns a one-line prompt into a narrated, captioned video:

**prompt → script → scene plan → visuals + narration → FFmpeg edit → `final.mp4`**

Built as a vertical slice to demonstrate orchestration, structured (Pydantic-validated) planning, per-scene state,
retries and resumability. Runs fully offline with mock providers, and on free tiers with real ones.

## Contents
- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Providers](#providers)
- [HTTP API](#http-api)
- [Job and scene states](#job-and-scene-states)
- [Retries and resume](#retries-and-resume)
- [Rendering](#rendering)
- [Project layout](#project-layout)
- [Testing](#testing)
- [Extending](#extending)
- [Honest limits](#honest-limits)

## How it works

```
prompt ─► Director (LLM, 2 steps: script, scene plan; Pydantic-validated)
              │
              ├─► Visual Agent ─► ImageProvider ─► scene_NN.png      (per-scene state, retries)
              └─► Voice Agent  ─► TTSProvider   ─► scene_NN.mp3      (per-scene state, retries)
                         │
              Editor Agent ─► EditDecision[] (timing from real audio length, caption, transition)
                         │
              FFmpeg: Ken Burns clip per scene + caption overlay + xfade/acrossfade (+ optional music bed)
                         ▼
                     final.mp4
```

| Agent | File | Job |
|-------|------|-----|
| Director | `agents/director.py` | Step 1: write a `Script` (title + one narration line per scene). Step 2: expand it into a `ScenePlan` (visual prompt, caption, duration, transition per scene). Scene count is derived from a target length parsed from the prompt (e.g. "30-second"; clamped 10–60s, 3–6 scenes). Output is validated against `models.py`. |
| Visual | `agents/visual.py` | Generates one still per scene via the `ImageProvider`, with retries. |
| Voice | `agents/voice.py` | Synthesizes narration per scene via the `TTSProvider`, with retries; records real audio duration. |
| Editor | `agents/editor.py` | Rule-based: produces an `EditDecision` per scene (clip length = narration + tail pad + transition overlap, alternating zoom-in/zoom-out), then drives FFmpeg. |
| Orchestrator | `pipeline/orchestrator.py` | Runs stages in order, persists state, fans out scenes concurrently (semaphore-limited), skips finished work. |

## Quick start

Prerequisites: Python 3.11+, Node 18+ (frontend only). FFmpeg is **not** required to install: the app uses `ffmpeg`
on `PATH`, else the binary bundled by `imageio-ffmpeg`.

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
cp .env.example .env              # optional; see Configuration
```

**Offline smoke test (no keys, no network):**

```bash
python -m app.cli --mock "Create a 30-second promotional video for an AI recruiting platform"
```

Prints the job id, final status and the path to `final.mp4` (under `backend/data/jobs/<job_id>/`).

**Run the API:**

```bash
uvicorn app.main:app --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev                       # http://localhost:3000
```

One page: prompt box, pipeline progress, per-scene cards (image, narration, status, retry), and a video player.
Next.js proxies `/api/*` to the backend at `http://localhost:8000`; override with `BACKEND_URL`.

### Default behaviour without any keys

Mock LLM (template script) + AI Horde images + Edge TTS voice. Set `GEMINI_API_KEY` (free at aistudio.google.com)
for real scripts. For a fully offline run use `--mock` on the CLI, or set all `*_PROVIDER=mock`.

## Configuration

Environment variables, loaded from `backend/.env` (see [.env.example](backend/.env.example)). Parsed in
[config.py](backend/app/config.py); empty values fall back to defaults.

| Variable | Default | Meaning |
|----------|---------|---------|
| `LLM_PROVIDER` | `gemini` if `GEMINI_API_KEY` set, else `mock` | `mock` \| `gemini` \| `openai_compat` |
| `GEMINI_API_KEY` | – | Required for `gemini` |
| `GEMINI_MODEL` | `gemini-flash-lite-latest` | |
| `OPENAI_BASE_URL` | `https://api.groq.com/openai/v1` | Any OpenAI-compatible endpoint (Groq, OpenAI, Ollama…) |
| `OPENAI_API_KEY` | – | Required for `openai_compat` |
| `OPENAI_MODEL` | `llama-3.3-70b-versatile` | |
| `IMAGE_PROVIDER` | `horde` | `horde` \| `pollinations` \| `mock`. Comma-separated list = fallback chain, e.g. `horde,mock` |
| `AI_HORDE_API_KEY` | – | Optional; anonymous works but queues longer |
| `POLLINATIONS_API_KEY` | – | Optional |
| `TTS_PROVIDER` | `edge` | `edge` \| `mock` |
| `EDGE_TTS_VOICE` | `en-US-AriaNeural` | Any Edge neural voice |
| `BGM_PATH` | – | Optional audio file looped under narration at 10% volume |
| `FFMPEG_PATH` | – | Override ffmpeg binary |
| `DATA_DIR` | `backend/data` | SQLite DB (`forge.db`) and per-job artifacts (`jobs/<id>/`) |

Fixed defaults in `Settings` (code, not env): 1280×720, 30 fps, 0.5 s transitions, 3 attempts per provider call,
1 s base backoff, 3 scenes processed concurrently.

## Providers

All providers are abstract base classes in `backend/app/providers/`; implementations are selected in
`providers/__init__.py::build_providers`.

| Role | Options | Status |
|------|---------|--------|
| LLM | `mock` (offline template), `gemini`, `openai_compat` | Implemented |
| Image | `horde` (anonymous, free, queue can be slow), `pollinations` (free tier gated/flaky, watermark), `mock` | Implemented; `FallbackImage` chains several |
| TTS | `edge` (free neural voices via edge-tts, no key), `mock` (tone, **not** speech) | Implemented |
| Video | `VideoGenerator` | **Interface only.** Stills are animated with FFmpeg Ken Burns. |
| Lip-sync | `LipSyncProvider` | **Interface only. Not implemented, not called by the pipeline.** |

Mock providers are real, clearly named implementations meant for offline runs and tests; nothing pretends to be an
integration it is not.

## HTTP API

Base path `/api`. Jobs run in the background; poll `GET /api/videos/{id}`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | `{"ok": true}` |
| `POST` | `/api/videos` | Body `{"prompt": "..."}` (5–1000 chars). Creates a job, starts it, returns `202` with the job view. |
| `GET` | `/api/videos` | 20 most recent jobs (id, prompt, status, title, created_at). |
| `GET` | `/api/videos/{id}` | Job view: `status`, `error`, `running`, `scenes[]`, `video_url` (set once `COMPLETED`). |
| `POST` | `/api/videos/{id}/retry` | Resume the job; only failed/pending work is redone. `409` if already running. |
| `POST` | `/api/videos/{id}/scenes/{n}/retry` | Regenerate one scene (visual + audio) and re-assemble. `404` unknown scene, `409` if running. |
| `GET` | `/api/videos/{id}/final.mp4` | The rendered video. |
| `GET` | `/api/videos/{id}/scenes/{n}/image.png` | A scene's generated still. |

```bash
curl -X POST localhost:8000/api/videos -H "content-type: application/json" \
  -d '{"prompt":"Create a 30-second promo for an AI recruiting platform"}'
curl localhost:8000/api/videos/<id>
```

Server-internal file paths are stripped from API responses. CORS allows `http://localhost:3000`.

## Job and scene states

Job: `CREATED → SCRIPTED → SCENES_PLANNED → VISUALS_GENERATED → AUDIO_GENERATED → ASSEMBLING → COMPLETED`, or `FAILED`
(with `error` set).

Each scene tracks `visual_status` and `audio_status` independently: `PENDING → GENERATING → GENERATED | FAILED`,
plus attempt counters and the last error. Everything is persisted in SQLite (`jobs` and `scenes` tables in
[state.py](backend/app/pipeline/state.py)).

## Retries and resume

- **Inline retries:** each provider call is wrapped in `with_retry` (3 attempts, exponential backoff 1 s, 2 s…).
- **Stage failure:** if a scene still fails, the stage raises and the job becomes `FAILED`, naming the scenes.
- **Resume:** `Orchestrator.run` is idempotent. It restarts from the stored state, reusing the saved script/plan and
  skipping every scene already `GENERATED`. `POST /retry` redoes only failed scenes; `POST /scenes/{n}/retry`
  resets one scene and re-assembles the video.
- Keep `run` idempotent when changing the pipeline.

## Rendering

Deterministic: the Editor produces `EditDecision`s (`models.py`) and `render/ffmpeg.py` turns them into commands, so
the same decisions always yield the same FFmpeg invocations.

1. Per scene: still scaled up, Ken Burns `zoompan` (up to 1.15×, alternating in/out), caption overlay, narration
   padded/trimmed to the scene length.
2. Join: chained `xfade` (video) + `acrossfade` (audio), using each incoming scene's transition
   (`fade`, `dissolve`, `wipeleft`, `wiperight`, `slideleft`, `slideright`).
3. Optional `BGM_PATH` music bed mixed under narration.

Captions are Pillow-rendered PNG overlays (`render/captions.py`), not FFmpeg `drawtext`, to avoid font/escaping
problems on Windows. Scene length is derived from the real narration duration, so audio never clips.

## Project layout

```
backend/
  app/
    agents/      director, visual, voice, editor
    providers/   llm, image, tts, video, lipsync (ABCs + adapters); __init__.py registers them
    pipeline/    orchestrator (resumable run), state (SQLite store, enums), retry (backoff)
    render/      ffmpeg (clip + transition assembly), captions (Pillow overlays)
    api/         videos.py (FastAPI router)
    cli.py       offline/online one-shot runner
    config.py    Settings from env
    models.py    Script, Scene, ScenePlan, EditDecision
    main.py      FastAPI app
  tests/         test_pipeline.py
  data/          runtime output (gitignored)
frontend/
  app/page.tsx   single page: prompt, progress, scene cards, player
```

## Testing

```bash
cd backend
.venv/Scripts/python -m pytest -q tests     # macOS/Linux: .venv/bin/python
```

Uses mock providers, needs no network, takes about 45 s. Covers the happy path, inline retry of transient failures,
retry redoing only the failed scene, and resume skipping `GENERATED` scenes.

## Extending

**Add a provider:** subclass the relevant ABC in `providers/` (`LLMProvider.complete_json`,
`ImageProvider.generate`, `TTSProvider.synthesize`), then register it by name in `build_providers` in
`providers/__init__.py` and document its env vars in `.env.example`. Provide a real adapter or a clearly named mock,
never a fake integration.

**Change edit style:** adjust `EditorAgent.decide` (timing, zoom, transitions). Rendering stays in `render/ffmpeg.py`.

## Honest limits

- No lip-sync and no true video model; visuals are stills with zoom/pan. `LipSyncProvider` and `VideoGenerator` are
  interfaces only.
- Sync is by timing (scene length derived from real narration duration), not phoneme alignment.
- In-process asyncio worker + SQLite instead of Celery/Redis; jobs do not survive a server restart mid-run unless
  retried, but the orchestrator is resumable so it moves to a queue cleanly.
- No authentication or rate limiting on the API; it is intended for local use.
- AI Horde and Pollinations are third-party free services: expect rate limits and queue waits.
