# AgentVideoForge

- Backend: `backend/app` (FastAPI, Pydantic, SQLite, FFmpeg). Frontend: `frontend` (Next.js, one page).
- Pipeline entry: `pipeline/orchestrator.py::Orchestrator.run` — resumable; skips GENERATED scenes. Keep it idempotent.
- Providers are ABCs in `providers/`; register new ones in `providers/__init__.py`. Never fake an integration: real adapter or mock, clearly named.
- Rendering is deterministic: `agents/editor.py` makes `EditDecision`s, `render/ffmpeg.py` turns them into commands. Captions use Pillow overlays, not drawtext.
- Tests: `cd backend && .venv/Scripts/python -m pytest -q tests` (mock providers, ~45s, needs no network).
- LipSyncProvider / VideoGenerator are interfaces only; do not claim them as implemented.
