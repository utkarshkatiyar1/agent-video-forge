from dataclasses import dataclass

from app.config import Settings
from app.providers.image import FallbackImage, HordeImage, ImageProvider, MockImage, PollinationsImage
from app.providers.llm import GeminiLLM, LLMProvider, MockLLM, OpenAICompatLLM
from app.providers.tts import EdgeTTS, MockTTS, TTSProvider


@dataclass
class Providers:
    llm: LLMProvider
    image: ImageProvider
    tts: TTSProvider


def build_providers(s: Settings) -> Providers:
    llm: LLMProvider
    if s.llm_provider == "gemini":
        if not s.gemini_api_key:
            raise ValueError("LLM_PROVIDER=gemini needs GEMINI_API_KEY")
        llm = GeminiLLM(s.gemini_api_key, s.gemini_model)
    elif s.llm_provider == "openai_compat":
        if not s.openai_api_key:
            raise ValueError("LLM_PROVIDER=openai_compat needs OPENAI_API_KEY")
        llm = OpenAICompatLLM(s.openai_base_url, s.openai_api_key, s.openai_model)
    elif s.llm_provider == "mock":
        llm = MockLLM()
    else:
        raise ValueError(f"unknown LLM_PROVIDER {s.llm_provider!r}")

    images = {"horde": HordeImage, "pollinations": PollinationsImage, "mock": MockImage}
    names = [n.strip() for n in s.image_provider.split(",") if n.strip()]
    for n in names:
        if n not in images:
            raise ValueError(f"unknown IMAGE_PROVIDER {n!r}")

    chain = [images[n]() for n in names]

    if s.tts_provider == "edge":
        tts: TTSProvider = EdgeTTS(s.edge_voice)
    elif s.tts_provider == "mock":
        tts = MockTTS()
    else:
        raise ValueError(f"unknown TTS_PROVIDER {s.tts_provider!r}")

    return Providers(llm=llm, image=chain[0] if len(chain) == 1 else FallbackImage(chain), tts=tts)
