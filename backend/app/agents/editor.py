import asyncio
from pathlib import Path

from app.config import Settings
from app.models import EditDecision
from app.render import ffmpeg
from app.render.captions import render_caption_overlay

TAIL_PAD = 0.4  # silence after narration so it never clips


class EditorAgent:
    """Turns generated assets into explicit edit decisions, then renders them with FFmpeg."""

    def __init__(self, settings: Settings):
        self.s = settings

    def decide(self, scenes: list[dict]) -> list[EditDecision]:
        """Rule-based timing: each clip covers its narration + pad + the overlap consumed by the next fade."""
        out = []
        last = len(scenes) - 1
        for i, sc in enumerate(scenes):
            need = sc["audio_duration"] + TAIL_PAD + (self.s.transition_seconds if i < last else 0)
            out.append(EditDecision(
                scene=sc["id"],
                image=sc["visual_path"],
                audio=sc["audio_path"],
                duration=round(max(sc["duration"], need), 3),
                caption=sc["caption"],
                transition=sc["transition"],
                zoom_in=i % 2 == 0,
            ))
        return out

    async def assemble(self, job_id: str, decisions: list[EditDecision]) -> Path:
        d = self.s.job_dir(job_id)

        async def clip(dec: EditDecision) -> Path:
            overlay = await asyncio.to_thread(
                render_caption_overlay, dec.caption, self.s.width, self.s.height, d / f"cap_{dec.scene:02d}.png"
            )
            return await ffmpeg.render_scene_clip(
                dec, overlay, d / f"clip_{dec.scene:02d}.mp4", self.s.width, self.s.height, self.s.fps
            )

        clips = await asyncio.gather(*(clip(x) for x in decisions))
        return await ffmpeg.concat_with_transitions(
            list(clips), decisions, d / "final.mp4", self.s.transition_seconds, self.s.bgm_path
        )
