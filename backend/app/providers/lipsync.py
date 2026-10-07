from abc import ABC, abstractmethod
from pathlib import Path


class LipSyncProvider(ABC):
    """Next pipeline stage (not wired in): drive a face video/image with narration audio.

    Candidates to adapt: Wav2Lip / SadTalker (self-hosted), HeyGen / D-ID / Sync Labs APIs.
    The orchestrator does not call this yet; no lip-sync is performed by the current pipeline.
    """

    @abstractmethod
    async def apply(self, video: Path, audio: Path, out_path: Path) -> Path: ...
