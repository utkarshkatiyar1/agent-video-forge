"""python -m app.cli "Create a 30-second promotional video for an AI recruiting platform" [--mock]"""

import argparse
import asyncio
import logging

from app.config import Settings
from app.pipeline.orchestrator import Orchestrator
from app.pipeline.state import Store
from app.providers import build_providers


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("--mock", action="store_true", help="force mock LLM/image/TTS (offline)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    s = Settings()
    if args.mock:
        s.llm_provider = s.image_provider = s.tts_provider = "mock"
    o = Orchestrator(Store(s.db_path), build_providers(s), s)
    job_id = o.create(args.prompt)
    await o.run(job_id)
    job = o.store.get_job(job_id)
    print(f"job {job_id}: {job['status']}")
    if job["error"]:
        print("error:", job["error"])
    if job["output_path"]:
        print("video:", job["output_path"])


if __name__ == "__main__":
    asyncio.run(main())
