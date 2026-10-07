import asyncio
import io
from pathlib import Path

from PIL import Image, ImageOps

from app.config import Settings
from app.pipeline.retry import with_retry
from app.pipeline.state import StepStatus, Store
from app.providers.image import ImageProvider


class VisualAgent:
    def __init__(self, provider: ImageProvider, store: Store, settings: Settings):
        self.provider, self.store, self.s = provider, store, settings

    async def run_scene(self, job_id: str, scene: dict) -> bool:
        """Generate one scene image. Independent state per scene; returns success."""
        sid = scene["id"]
        self.store.update_scene(job_id, sid, visual_status=StepStatus.GENERATING)

        async def call() -> Path:
            seed = scene["visual_attempts"] * 1000 + sid  # new seed on each retry
            raw = await self.provider.generate(scene["visual_prompt"], self.s.width, self.s.height, seed)
            return await asyncio.to_thread(self._save, raw, self.s.job_dir(job_id) / f"scene_{sid:02d}.png")

        try:
            path = await with_retry(
                call,
                attempts=self.s.max_attempts,
                base_delay=self.s.retry_base_delay,
                on_failure=lambda _n, e: self.store.bump_attempts(job_id, sid, "visual", str(e)[:500]),
                label=f"visual[{sid}]",
            )
        except Exception:
            self.store.update_scene(job_id, sid, visual_status=StepStatus.FAILED)
            return False
        self.store.update_scene(job_id, sid, visual_status=StepStatus.GENERATED, visual_path=str(path), error=None)
        return True

    def _save(self, raw: bytes, out: Path) -> Path:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        ImageOps.fit(img, (self.s.width, self.s.height), Image.LANCZOS).save(out, "PNG")
        return out
