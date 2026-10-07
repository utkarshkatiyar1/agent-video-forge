import json
import re

from app.config import Settings
from app.models import Scene, ScenePlan, Script
from app.pipeline.retry import with_retry
from app.providers.llm import LLMProvider

SCRIPT_SYSTEM = """You are the script writer for short promotional videos.
Return ONLY JSON: {"title": str, "lines": [str, ...]}.
`lines` has exactly `scene_count` entries, one per scene, each 1-2 short spoken sentences
(about 12-18 words). Together they form a hook, a problem, the solution, proof/benefit and a call to action.
Honor any personalization (names, occasion) in the prompt."""

SCENES_SYSTEM = """You are a video scene planner.
Given a title and narration lines, return ONLY JSON:
{"title": str, "scenes": [{"id": int, "duration": number, "visual_prompt": str,
"narration": str, "caption": str, "transition": one of fade|dissolve|wipeleft|wiperight|slideleft|slideright}]}.
One scene per line, in order; `narration` is the line verbatim. `duration` in seconds (3-8) fits the narration.
`visual_prompt` is a vivid, self-contained text-to-image prompt (subject, setting, style, lighting), no text in image.
`caption` is at most 7 words."""


def target_seconds(prompt: str) -> int:
    m = re.search(r"(\d+)\s*-?\s*(?:s|sec|secs|second|seconds)\b", prompt, re.I)
    return min(max(int(m.group(1)), 10), 60) if m else 30


class DirectorAgent:
    def __init__(self, llm: LLMProvider, settings: Settings):
        self.llm, self.s = llm, settings

    async def write_script(self, prompt: str) -> Script:
        seconds = target_seconds(prompt)
        scene_count = min(max(round(seconds / 6), 3), 6)
        user = json.dumps({"prompt": prompt, "target_seconds": seconds, "scene_count": scene_count})

        async def call() -> Script:
            script = Script.model_validate(await self.llm.complete_json("script", SCRIPT_SYSTEM, user))
            script.lines = [l.strip() for l in script.lines if l.strip()][:scene_count]
            if not script.lines:
                raise ValueError("empty script")
            return script

        return await with_retry(call, attempts=self.s.max_attempts, base_delay=self.s.retry_base_delay, label="script")

    async def plan_scenes(self, script: Script) -> ScenePlan:
        user = json.dumps({"title": script.title, "lines": script.lines})

        async def call() -> ScenePlan:
            plan = ScenePlan.model_validate(await self.llm.complete_json("scenes", SCENES_SYSTEM, user))
            return self._normalize(plan, script)

        return await with_retry(call, attempts=self.s.max_attempts, base_delay=self.s.retry_base_delay, label="plan")

    @staticmethod
    def _normalize(plan: ScenePlan, script: Script) -> ScenePlan:
        """Enforce invariants the renderer relies on, whatever the LLM returned."""
        scenes: list[Scene] = []
        for i, sc in enumerate(plan.scenes):
            narration = sc.narration.strip() or (script.lines[i] if i < len(script.lines) else "")
            caption = " ".join((sc.caption or narration).split()[:7])
            scenes.append(sc.model_copy(update={
                "id": i + 1,
                "duration": min(max(sc.duration, 3.0), 8.0),
                "narration": narration,
                "caption": caption,
            }))
        return ScenePlan(title=plan.title or script.title, scenes=scenes)
