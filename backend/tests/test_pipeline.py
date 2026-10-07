import asyncio

import pytest

from app.config import Settings
from app.pipeline.orchestrator import Orchestrator
from app.pipeline.state import JobStatus, Store
from app.providers import Providers
from app.providers.image import ImageProvider, MockImage
from app.providers.llm import MockLLM
from app.providers.tts import MockTTS


class FlakyImage(ImageProvider):
    """Fails the first `fail_n` calls for prompts containing `marker`."""

    def __init__(self, marker: str, fail_n: int):
        self.marker, self.fail_n, self.calls = marker, fail_n, {}
        self.inner = MockImage()

    async def generate(self, prompt, width, height, seed):
        self.calls[prompt] = self.calls.get(prompt, 0) + 1
        if self.marker in prompt and self.calls[prompt] <= self.fail_n:
            raise RuntimeError("provider down")
        return await self.inner.generate(prompt, width, height, seed)


def make(tmp_path, image, attempts=2):
    s = Settings(data_dir=tmp_path, max_attempts=attempts, retry_base_delay=0.01)
    return Orchestrator(Store(s.db_path), Providers(MockLLM(), image, MockTTS()), s)


PROMPT = "Create a 12-second promotional video for an AI recruiting platform"


def test_happy_path(tmp_path):
    o = make(tmp_path, MockImage())
    jid = o.create(PROMPT)
    asyncio.run(o.run(jid))
    job = o.store.get_job(jid)
    assert job["status"] == JobStatus.COMPLETED.value
    assert job["output_path"] and (tmp_path / "jobs" / jid / "final.mp4").stat().st_size > 10_000


def test_transient_failure_is_retried_inline(tmp_path):
    img = FlakyImage("cinematic", fail_n=1)
    o = make(tmp_path, img, attempts=3)
    jid = o.create(PROMPT)
    asyncio.run(o.run(jid))
    assert o.store.get_job(jid)["status"] == JobStatus.COMPLETED.value
    assert o.store.list_scenes(jid)[0]["visual_attempts"] == 1


def test_failed_scene_retry_redoes_only_that_scene(tmp_path):
    img = FlakyImage("modern flat", fail_n=2)  # scene 2 exhausts its 2 attempts
    o = make(tmp_path, img, attempts=2)
    jid = o.create(PROMPT)
    asyncio.run(o.run(jid))

    job = o.store.get_job(jid)
    assert job["status"] == JobStatus.FAILED.value
    by_status = {s["id"]: s["visual_status"] for s in o.store.list_scenes(jid)}
    assert by_status[2] == "FAILED" and by_status[1] == "GENERATED"
    calls_before = sum(img.calls.values())

    o.reset_scene(jid, 2)
    asyncio.run(o.run(jid))
    assert o.store.get_job(jid)["status"] == JobStatus.COMPLETED.value
    # only scene 2 was regenerated (1 more call), scene 1/3 untouched
    assert sum(img.calls.values()) == calls_before + 1


def test_resume_without_reset_skips_generated_scenes(tmp_path):
    img = FlakyImage("modern flat", fail_n=2)
    o = make(tmp_path, img, attempts=2)
    jid = o.create(PROMPT)
    asyncio.run(o.run(jid))
    assert o.store.get_job(jid)["status"] == JobStatus.FAILED.value
    # failed scene keeps FAILED status, so a plain resume picks it up (provider healthy now: calls > fail_n)
    img.calls = {k: 99 for k in img.calls}
    asyncio.run(o.run(jid))
    assert o.store.get_job(jid)["status"] == JobStatus.COMPLETED.value
