from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.pipeline.orchestrator import Orchestrator
from app.pipeline.state import JobStatus

router = APIRouter(prefix="/api/videos", tags=["videos"])


class CreateVideo(BaseModel):
    prompt: str = Field(min_length=5, max_length=1000)


def _orch(request: Request) -> Orchestrator:
    return request.app.state.orchestrator


def _view(o: Orchestrator, job_id: str) -> dict:
    job = o.store.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    scenes = o.store.list_scenes(job_id)
    for sc in scenes:  # local file paths are server-internal
        sc.pop("visual_path", None)
        sc.pop("audio_path", None)
    return {
        "id": job["id"],
        "prompt": job["prompt"],
        "title": job["title"],
        "status": job["status"],
        "error": job["error"],
        "running": o.is_running(job_id),
        "scenes": scenes,
        "video_url": f"/api/videos/{job_id}/final.mp4" if job["status"] == JobStatus.COMPLETED.value else None,
    }


@router.post("", status_code=202)
async def create_video(body: CreateVideo, request: Request) -> dict:
    o = _orch(request)
    job_id = o.create(body.prompt)
    o.submit(job_id)
    return _view(o, job_id)


@router.get("")
async def list_videos(request: Request) -> list[dict]:
    return _orch(request).store.list_jobs()


@router.get("/{job_id}")
async def get_video(job_id: str, request: Request) -> dict:
    return _view(_orch(request), job_id)


@router.post("/{job_id}/retry", status_code=202)
async def retry_job(job_id: str, request: Request) -> dict:
    """Resume: failed/pending work is redone, GENERATED scenes are kept."""
    o = _orch(request)
    _view(o, job_id)
    if o.is_running(job_id):
        raise HTTPException(409, "job already running")
    o.submit(job_id)
    return _view(o, job_id)


@router.post("/{job_id}/scenes/{scene_id}/retry", status_code=202)
async def retry_scene(job_id: str, scene_id: int, request: Request) -> dict:
    """Regenerate one scene (visual + audio) and re-assemble; other scenes are untouched."""
    o = _orch(request)
    view = _view(o, job_id)
    if o.is_running(job_id):
        raise HTTPException(409, "job already running")
    if scene_id not in {s["id"] for s in view["scenes"]}:
        raise HTTPException(404, "scene not found")
    o.reset_scene(job_id, scene_id)
    o.submit(job_id)
    return _view(o, job_id)


@router.get("/{job_id}/final.mp4")
async def final_video(job_id: str, request: Request) -> FileResponse:
    job = _orch(request).store.get_job(job_id)
    if not job or not job["output_path"] or not Path(job["output_path"]).exists():
        raise HTTPException(404, "video not ready")
    return FileResponse(job["output_path"], media_type="video/mp4")


@router.get("/{job_id}/scenes/{scene_id}/image.png")
async def scene_image(job_id: str, scene_id: int, request: Request) -> FileResponse:
    for sc in _orch(request).store.list_scenes(job_id):
        if sc["id"] == scene_id and sc.get("visual_path") and Path(sc["visual_path"]).exists():
            return FileResponse(sc["visual_path"], media_type="image/png", headers={"Cache-Control": "no-store"})
    raise HTTPException(404, "image not ready")
