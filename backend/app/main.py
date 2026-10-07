import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.videos import router as videos_router
from app.config import Settings
from app.pipeline.orchestrator import Orchestrator
from app.pipeline.state import Store
from app.providers import build_providers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    app.state.orchestrator = Orchestrator(Store(settings.db_path), build_providers(settings), settings)
    yield


app = FastAPI(title="AgentVideoForge", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"]
)
app.include_router(videos_router)


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True}
