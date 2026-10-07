import math
import struct
import wave
from abc import ABC, abstractmethod
from pathlib import Path


class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, out_stem: Path) -> Path:
        """Write narration audio next to `out_stem` (extension chosen by provider); return the file."""


class EdgeTTS(TTSProvider):
    """Free neural voices via Microsoft Edge read-aloud (edge-tts). No key, needs internet."""

    def __init__(self, voice: str):
        self.voice = voice

    async def synthesize(self, text: str, out_stem: Path) -> Path:
        import edge_tts

        out = out_stem.with_suffix(".mp3")
        await edge_tts.Communicate(text, self.voice).save(str(out))
        if not out.exists() or out.stat().st_size == 0:
            raise RuntimeError("edge-tts produced no audio")
        return out


class MockTTS(TTSProvider):
    """Quiet low tone, length ~ speech duration. Offline stand-in, not real speech."""

    async def synthesize(self, text: str, out_stem: Path) -> Path:
        out = out_stem.with_suffix(".wav")
        seconds = max(1.5, len(text.split()) / 2.6)
        rate = 22050
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            frames = (
                struct.pack("<h", int(1200 * math.sin(2 * math.pi * 180 * i / rate) * (0.5 + 0.5 * math.sin(i / 2500))))
                for i in range(int(seconds * rate))
            )
            w.writeframes(b"".join(frames))
        return out
