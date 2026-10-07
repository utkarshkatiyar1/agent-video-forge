from abc import ABC, abstractmethod
from pathlib import Path


class VideoGenerator(ABC):
    """Interface for true text/image-to-video models (Veo, Runway, Luma, Kling, ...).

    Not implemented: the shipped pipeline animates stills with FFmpeg Ken Burns moves
    (see render/ffmpeg.py). Implement this and swap it into VisualAgent to use a video model.
    """

    @abstractmethod
    async def generate(self, prompt: str, duration: float, out_path: Path) -> Path: ...
