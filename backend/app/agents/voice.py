from app.config import Settings
from app.pipeline.retry import with_retry
from app.pipeline.state import StepStatus, Store
from app.providers.tts import TTSProvider
from app.render.ffmpeg import probe_duration


class VoiceAgent:
    def __init__(self, provider: TTSProvider, store: Store, settings: Settings):
        self.provider, self.store, self.s = provider, store, settings

    async def run_scene(self, job_id: str, scene: dict) -> bool:
        sid = scene["id"]
        self.store.update_scene(job_id, sid, audio_status=StepStatus.GENERATING)

        async def call():
            path = await self.provider.synthesize(scene["narration"], self.s.job_dir(job_id) / f"scene_{sid:02d}")
            return path, await probe_duration(path)

        try:
            path, duration = await with_retry(
                call,
                attempts=self.s.max_attempts,
                base_delay=self.s.retry_base_delay,
                on_failure=lambda _n, e: self.store.bump_attempts(job_id, sid, "audio", str(e)[:500]),
                label=f"voice[{sid}]",
            )
        except Exception:
            self.store.update_scene(job_id, sid, audio_status=StepStatus.FAILED)
            return False
        self.store.update_scene(
            job_id, sid, audio_status=StepStatus.GENERATED, audio_path=str(path), audio_duration=duration, error=None
        )
        return True
