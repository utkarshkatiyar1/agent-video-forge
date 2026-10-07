import asyncio
import logging

from app.agents.director import DirectorAgent
from app.agents.editor import EditorAgent
from app.agents.visual import VisualAgent
from app.agents.voice import VoiceAgent
from app.config import Settings
from app.models import ScenePlan, Script
from app.pipeline.state import JobStatus, StepStatus, Store
from app.providers import Providers

log = logging.getLogger("forge.orchestrator")


class StageFailed(Exception):
    pass


class Orchestrator:
    """Resumable pipeline. run() skips every stage/scene already GENERATED, so retrying a job
    (or a single scene) only redoes the failed work."""

    def __init__(self, store: Store, providers: Providers, settings: Settings):
        self.store, self.s = store, settings
        self.director = DirectorAgent(providers.llm, settings)
        self.visual = VisualAgent(providers.image, store, settings)
        self.voice = VoiceAgent(providers.tts, store, settings)
        self.editor = EditorAgent(settings)
        self._tasks: dict[str, asyncio.Task] = {}

    # ---- public API ----
    def create(self, prompt: str) -> str:
        return self.store.create_job(prompt)

    def submit(self, job_id: str) -> bool:
        """Start run() in the background unless it is already running."""
        task = self._tasks.get(job_id)
        if task and not task.done():
            return False
        self._tasks[job_id] = asyncio.create_task(self.run(job_id))
        return True

    def is_running(self, job_id: str) -> bool:
        t = self._tasks.get(job_id)
        return bool(t and not t.done())

    def reset_scene(self, job_id: str, scene_id: int) -> None:
        self.store.reset_scene(job_id, scene_id)

    # ---- pipeline ----
    async def run(self, job_id: str) -> None:
        st = self.store
        try:
            job = st.get_job(job_id)
            if job is None:
                raise StageFailed("job not found")
            initial = (
                JobStatus.SCENES_PLANNED if job["plan"] else JobStatus.SCRIPTED if job["script"] else JobStatus.CREATED
            )
            st.update_job(job_id, status=initial, error=None, output_path=None)

            if not job["script"]:
                script = await self.director.write_script(job["prompt"])
                st.update_job(job_id, status=JobStatus.SCRIPTED, title=script.title, script_json=script.model_dump_json())
            else:
                script = Script.model_validate(job["script"])

            if not job["plan"]:
                plan = await self.director.plan_scenes(script)
                st.save_scenes(job_id, [sc.model_dump() for sc in plan.scenes])
                st.update_job(job_id, status=JobStatus.SCENES_PLANNED, title=plan.title, plan_json=plan.model_dump_json())

            await self._stage("visual", job_id, self.visual.run_scene, JobStatus.VISUALS_GENERATED)
            await self._stage("audio", job_id, self.voice.run_scene, JobStatus.AUDIO_GENERATED)
            await self._assemble(job_id)
        except Exception as exc:
            log.exception("job %s failed", job_id)
            st.update_job(job_id, status=JobStatus.FAILED, error=str(exc)[:1500])

    async def _stage(self, kind: str, job_id: str, run_scene, done: JobStatus) -> None:
        sem = asyncio.Semaphore(self.s.concurrency)
        pending = [s for s in self.store.list_scenes(job_id) if s[f"{kind}_status"] != StepStatus.GENERATED.value]

        async def one(scene: dict) -> bool:
            async with sem:
                return await run_scene(job_id, scene)

        results = await asyncio.gather(*(one(s) for s in pending))
        failed = [s["id"] for s, ok in zip(pending, results) if not ok]
        if failed:
            raise StageFailed(f"{kind} generation failed for scene(s) {failed}; retry to redo only those")
        self.store.update_job(job_id, status=done)

    async def _assemble(self, job_id: str) -> None:
        self.store.update_job(job_id, status=JobStatus.ASSEMBLING)
        scenes = self.store.list_scenes(job_id)
        decisions = self.editor.decide(scenes)
        final = await self.editor.assemble(job_id, decisions)
        self.store.update_job(job_id, status=JobStatus.COMPLETED, output_path=str(final))
