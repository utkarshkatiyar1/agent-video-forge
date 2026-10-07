import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, "").strip() or default


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", str(BACKEND_ROOT / "data"))))
    llm_provider: str = field(
        default_factory=lambda: _env("LLM_PROVIDER", "gemini" if _env("GEMINI_API_KEY") else "mock")
    )
    image_provider: str = field(default_factory=lambda: _env("IMAGE_PROVIDER", "horde"))
    tts_provider: str = field(default_factory=lambda: _env("TTS_PROVIDER", "edge"))
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-flash-lite-latest"))
    openai_base_url: str = field(default_factory=lambda: _env("OPENAI_BASE_URL", "https://api.groq.com/openai/v1"))
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    openai_model: str = field(default_factory=lambda: _env("OPENAI_MODEL", "llama-3.3-70b-versatile"))
    edge_voice: str = field(default_factory=lambda: _env("EDGE_TTS_VOICE", "en-US-AriaNeural"))
    bgm_path: str = field(default_factory=lambda: _env("BGM_PATH"))
    width: int = 1280
    height: int = 720
    fps: int = 30
    transition_seconds: float = 0.5
    max_attempts: int = 3
    retry_base_delay: float = 1.0
    concurrency: int = 3

    @property
    def db_path(self) -> Path:
        return self.data_dir / "forge.db"

    def job_dir(self, job_id: str) -> Path:
        d = self.data_dir / "jobs" / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d
