from typing import Literal

from pydantic import BaseModel, Field

Transition = Literal["fade", "dissolve", "wipeleft", "wiperight", "slideleft", "slideright"]


class Script(BaseModel):
    """Stage 1 output: narration split into beats, one per scene."""

    title: str
    lines: list[str] = Field(min_length=1)


class Scene(BaseModel):
    id: int
    duration: float = Field(ge=1, le=20)
    visual_prompt: str
    narration: str
    caption: str
    transition: Transition = "fade"


class ScenePlan(BaseModel):
    """Stage 2 output: structured scene plan."""

    title: str
    scenes: list[Scene] = Field(min_length=1)


class EditDecision(BaseModel):
    """Editor Agent output for one scene; translated 1:1 into FFmpeg input."""

    scene: int
    image: str
    audio: str
    duration: float
    caption: str
    transition: str
    zoom_in: bool = True
