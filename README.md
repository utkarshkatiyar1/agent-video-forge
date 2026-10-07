# AgentVideoForge

Agentic, multi-model pipeline: **prompt → script → scene plan → visuals + narration → FFmpeg edit → final.mp4**.
Built as a vertical slice to show orchestration, structured planning, per-scene state and retries.

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

## Job states
`CREATED → SCRIPTED → SCENES_PLANNED → VISUALS_GENERATED → AUDIO_GENERATED → ASSEMBLING → COMPLETED` (or `FAILED`).
Each scene has its own `visual_status` / `audio_status` (`PENDING → GENERATING → GENERATED | FAILED`), persisted in SQLite.
Provider calls retry with exponential backoff. If a scene still fails, the job goes `FAILED`; **retry redoes only the
failed scenes** (`POST /api/videos/{id}/retry`), or regenerate one scene (`POST /api/videos/{id}/scenes/{n}/retry`).

## Providers (free by default, all swappable)
| Role | Options |
|------|---------|
| LLM | `mock` (offline), `gemini` (free AI Studio key), `openai_compat` (Groq free tier / OpenAI / Ollama) |
| Image | `horde` (AI Horde, anonymous, free, queue can be slow), `pollinations` (free tier currently gated/flaky, watermark), `mock` |
| TTS | `edge` (free neural voices via edge-tts, no key), `mock` (tone, not speech) |
| Video | `VideoGenerator` interface only; stills are animated with FFmpeg Ken Burns |
| Lip-sync | `LipSyncProvider` interface only: **not implemented, not called by the pipeline** |

Without any key the default is: mock LLM (template script) + Horde images + Edge voice. Set `GEMINI_API_KEY`
(free at aistudio.google.com) for real scripts. Use `--mock` / `*_PROVIDER=mock` for a fully offline run.

## Run
```bash
cd backend
python -m venv .venv && .venv\Scripts\activate     # Windows (source .venv/bin/activate elsewhere)
pip install -r requirements.txt
cp .env.example .env                                # optional
python -m app.cli --mock "Create a 30-second promotional video for an AI recruiting platform"   # CLI, offline
uvicorn app.main:app --port 8000                    # API
pytest -q tests                                     # retry/resume tests

cd ../frontend && npm install && npm run dev        # http://localhost:3000 (proxies /api to :8000)
```
FFmpeg: uses `ffmpeg` on PATH, else the binary bundled by `imageio-ffmpeg` (no system install needed).

## Layout
`backend/app/{agents,providers,pipeline,render,api}` · `frontend/app/page.tsx` (single page: prompt, pipeline progress, scene cards, player).

## Honest limits
- No lip-sync and no true video model; visuals are stills with zoom/pan.
- Sync is by timing (scene length derived from real narration duration), not phoneme alignment.
- In-process asyncio worker + SQLite instead of Celery/Redis; the orchestrator is resumable so it moves to a queue cleanly.
- Pollinations/Horde are third-party free services; expect rate limits and queue waits.
