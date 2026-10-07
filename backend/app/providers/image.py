import hashlib
import asyncio
import io
import os
import random
from abc import ABC, abstractmethod
from urllib.parse import quote

import httpx
from PIL import Image, ImageDraw

from app.render.captions import load_font, wrap


class ImageProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, width: int, height: int, seed: int) -> bytes:
        """Return encoded image bytes (any format Pillow can read)."""


class PollinationsImage(ImageProvider):
    """Free, keyless flux text-to-image. Output carries a pollinations.ai watermark.

    The free tier is picky: `seed` and `nologo` params get 401/402, so they are not sent.
    Optional POLLINATIONS_API_KEY (Bearer) lifts the restrictions.
    """

    async def generate(self, prompt: str, width: int, height: int, seed: int) -> bytes:
        url = f"https://image.pollinations.ai/prompt/{quote(prompt[:600])}"
        # Free tier 402s above ~0.3MP; request small, VisualAgent upscales to video size.
        scale = min(1.0, (640 * 360 / (width * height)) ** 0.5)
        params = {"model": "flux", "width": int(width * scale) // 8 * 8, "height": int(height * scale) // 8 * 8}
        key = os.getenv("POLLINATIONS_API_KEY", "").strip()
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
            r = await client.get(url, params=params, headers=headers)
            r.raise_for_status()
        if not r.headers.get("content-type", "").startswith("image/"):
            raise RuntimeError(f"pollinations returned {r.headers.get('content-type')}")
        return r.content


class HordeImage(ImageProvider):
    """AI Horde: community-run Stable Diffusion, free with the anonymous key (0000000000).

    Slow when the queue is busy (seconds to minutes). Set AI_HORDE_API_KEY for priority.
    Requests a small image (anonymous limits); VisualAgent upscales/crops to the video size.
    """

    BASE = "https://aihorde.net/api/v2"

    def __init__(self, timeout_s: int = 420):
        self.timeout_s = timeout_s
        self.headers = {
            "apikey": os.getenv("AI_HORDE_API_KEY", "").strip() or "0000000000",
            "Client-Agent": "agentvideoforge:0.1:github",
        }

    # Anonymous/free keys allow ~1 active request per IP; serialize to avoid 429.
    _lock: asyncio.Lock | None = None

    async def generate(self, prompt: str, width: int, height: int, seed: int) -> bytes:
        if self.headers["apikey"] != "0000000000":
            return await self._generate(prompt, seed)  # registered key: concurrent OK, 429 retried
        if HordeImage._lock is None:
            HordeImage._lock = asyncio.Lock()
        async with HordeImage._lock:
            return await self._generate(prompt, seed)

    async def _generate(self, prompt: str, seed: int) -> bytes:
        body = {
            "prompt": f"{prompt[:700]}, high quality, detailed, no text",
            "params": {"width": 640, "height": 384, "steps": 25, "n": 1, "cfg_scale": 7, "seed": str(seed)},
            "nsfw": False,
            "censor_nsfw": True,
            "r2": True,
        }
        async with httpx.AsyncClient(timeout=60, headers=self.headers) as client:
            for attempt in range(6):
                r = await client.post(f"{self.BASE}/generate/async", json=body)
                if r.status_code != 429:
                    break
                await asyncio.sleep(10 * (attempt + 1))
            r.raise_for_status()
            job_id = r.json()["id"]
            deadline = asyncio.get_running_loop().time() + self.timeout_s
            while True:
                await asyncio.sleep(4)
                c = await client.get(f"{self.BASE}/generate/check/{job_id}")
                c.raise_for_status()
                state = c.json()
                if state.get("faulted"):
                    raise RuntimeError("horde job faulted")
                if state.get("done"):
                    break
                if asyncio.get_running_loop().time() > deadline:
                    await client.delete(f"{self.BASE}/generate/status/{job_id}")
                    raise TimeoutError(f"horde queue timeout after {self.timeout_s}s")
            st = await client.get(f"{self.BASE}/generate/status/{job_id}")
            st.raise_for_status()
            gens = st.json().get("generations") or []
            if not gens or gens[0].get("censored"):
                raise RuntimeError("horde returned no usable image")
            img = await client.get(gens[0]["img"], timeout=120)
            img.raise_for_status()
            return img.content


class FallbackImage(ImageProvider):
    """Try providers in order; first success wins."""

    def __init__(self, providers: list[ImageProvider]):
        self.providers = providers

    async def generate(self, prompt: str, width: int, height: int, seed: int) -> bytes:
        last: Exception | None = None
        for p in self.providers:
            try:
                return await p.generate(prompt, width, height, seed)
            except Exception as e:  # noqa: BLE001 - any provider failure falls through
                last = e
        raise last or RuntimeError("no image providers configured")


class MockImage(ImageProvider):
    """Seeded gradient card with the prompt printed on it. Offline."""

    async def generate(self, prompt: str, width: int, height: int, seed: int) -> bytes:
        rng = random.Random(int(hashlib.md5(f"{prompt}{seed}".encode()).hexdigest(), 16))
        c1 = tuple(rng.randint(20, 120) for _ in range(3))
        c2 = tuple(rng.randint(100, 230) for _ in range(3))
        img = Image.new("RGB", (width, height))
        px = ImageDraw.Draw(img)
        for y in range(height):
            t = y / height
            px.line([(0, y), (width, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
        for _ in range(6):
            r = rng.randint(60, 220)
            x, y = rng.randint(0, width), rng.randint(0, height)
            px.ellipse([x - r, y - r, x + r, y + r], outline=(255, 255, 255), width=3)
        font = load_font(34)
        text = "\n".join(wrap(prompt, font, int(width * 0.75)))
        px.multiline_text((width * 0.125, height * 0.3), text, font=font, fill=(255, 255, 255), spacing=10)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()
