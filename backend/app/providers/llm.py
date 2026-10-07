import json
import re
from abc import ABC, abstractmethod

import httpx


class LLMProvider(ABC):
    @abstractmethod
    async def complete_json(self, task: str, system: str, user: str) -> dict:
        """Return a JSON object. `task` is "script" or "scenes" (used by mock; real LLMs read `system`)."""


def _loads(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return json.loads(text)


class GeminiLLM(LLMProvider):
    """Google AI Studio free tier."""

    def __init__(self, api_key: str, model: str):
        self.api_key, self.model = api_key, model

    async def complete_json(self, task: str, system: str, user: str) -> dict:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8},
        }
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(url, json=body, headers={"x-goog-api-key": self.api_key})
            r.raise_for_status()
        return _loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])


class OpenAICompatLLM(LLMProvider):
    """Any /chat/completions endpoint: Groq free tier, OpenAI, Ollama, ..."""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model

    async def complete_json(self, task: str, system: str, user: str) -> dict:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "temperature": 0.8,
        }
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(
                f"{self.base_url}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            r.raise_for_status()
        return _loads(r.json()["choices"][0]["message"]["content"])


class MockLLM(LLMProvider):
    """Deterministic offline planner so the whole pipeline runs without credentials."""

    async def complete_json(self, task: str, system: str, user: str) -> dict:
        data = json.loads(user)
        return self._script(data) if task == "script" else self._scenes(data)

    @staticmethod
    def _subject(prompt: str) -> str:
        m = re.search(r"\b(?:for|about|explaining|of)\s+(?:an?\s+|the\s+)?(.+?)(?:[.!?]|$)", prompt, re.I)
        return (m.group(1) if m else prompt).strip()[:60]

    def _script(self, data: dict) -> dict:
        subject = self._subject(data["prompt"])
        n = data["scene_count"]
        beats = [
            f"Still doing this the hard way? {subject.capitalize()} changes that.",
            "Stop wasting hours on repetitive work that a smart system can handle for you.",
            "It plans, decides and acts on its own, so you stay focused on what matters.",
            "Teams get faster results, fewer mistakes, and far more time back every week.",
            f"Meet {subject}. Start today and see the difference.",
        ]
        lines = [beats[0], *(beats[1:4] * 2)[: max(n - 2, 0)], beats[4]]
        return {"title": subject.title(), "lines": lines}

    def _scenes(self, data: dict) -> dict:
        styles = [
            "cinematic wide shot, dramatic lighting",
            "modern flat illustration, vibrant colors",
            "close-up, shallow depth of field",
            "futuristic dashboard glowing in a dark office",
            "bright optimistic finale, warm sunrise light",
        ]
        transitions = ["fade", "dissolve", "slideleft", "wipeleft", "fade"]
        scenes = []
        for i, line in enumerate(data["lines"]):
            words = line.split()
            scenes.append({
                "id": i + 1,
                "duration": round(max(3.0, len(words) / 2.6 + 0.8), 1),
                "visual_prompt": f"{data['title']}: {line} {styles[i % len(styles)]}",
                "narration": line,
                "caption": " ".join(words[:7]).rstrip(".,"),
                "transition": transitions[i % len(transitions)],
            })
        return {"title": data["title"], "scenes": scenes}
