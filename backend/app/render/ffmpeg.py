"""Deterministic media assembly. Same EditDecisions in -> same FFmpeg commands out."""

import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path

from app.models import EditDecision

MAX_ZOOM = 1.15
_XFADE = {"fade", "dissolve", "wipeleft", "wiperight", "slideleft", "slideright"}


def ffmpeg_exe() -> str:
    explicit = os.getenv("FFMPEG_PATH", "").strip()
    if explicit:
        return explicit
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


async def _exec(args: list[str]) -> tuple[int, str]:
    """Run a process in a thread: asyncio subprocesses raise NotImplementedError on Windows selector loops."""
    r = await asyncio.to_thread(subprocess.run, args, capture_output=True)
    return r.returncode, r.stderr.decode(errors="replace")


async def _run(args: list[str]) -> str:
    code, text = await _exec([ffmpeg_exe(), "-hide_banner", "-y", *args])
    if code != 0:
        raise RuntimeError(f"ffmpeg failed ({code}): {text[-1500:]}")
    return text


async def probe_duration(path: Path) -> float:
    _, err = await _exec([ffmpeg_exe(), "-hide_banner", "-i", str(path)])  # exits 1; Duration is on stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if not m:
        raise RuntimeError(f"cannot read duration of {path}")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


async def render_scene_clip(
    d: EditDecision, overlay: Path, out: Path, width: int, height: int, fps: int
) -> Path:
    """Still -> Ken Burns zoom, caption overlay, narration audio padded/trimmed to d.duration."""
    frames = max(1, round(d.duration * fps))
    inc = (MAX_ZOOM - 1) / frames
    zoom = (
        f"min(zoom+{inc:.6f},{MAX_ZOOM})"
        if d.zoom_in
        else f"if(eq(on,0),{MAX_ZOOM},max(zoom-{inc:.6f},1.0))"
    )
    graph = (
        f"[0:v]scale={width * 2}:{height * 2},"
        f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps}[bg];"
        f"[bg][1:v]overlay=0:0,format=yuv420p[v];"
        f"[2:a]aresample=44100,aformat=channel_layouts=stereo,apad[a]"
    )
    await _run([
        "-i", d.image, "-i", str(overlay), "-i", d.audio,
        "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
        "-t", f"{d.duration:.3f}", "-r", str(fps),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
        str(out),
    ])
    return out


async def concat_with_transitions(
    clips: list[Path], decisions: list[EditDecision], out: Path, transition_s: float, bgm: str = ""
) -> Path:
    """Chain xfade (video) + acrossfade (audio); each join uses the incoming scene's transition."""
    n = len(clips)
    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", str(c)]

    parts: list[str] = []
    if n == 1:
        v_label, a_label = "0:v", "0:a"
        total = decisions[0].duration
    else:
        v_prev, a_prev = "0:v", "0:a"
        elapsed = decisions[0].duration
        for k in range(1, n):
            t = decisions[k].transition if decisions[k].transition in _XFADE else "fade"
            offset = elapsed - transition_s
            parts.append(f"[{v_prev}][{k}:v]xfade=transition={t}:duration={transition_s}:offset={offset:.3f}[v{k}]")
            parts.append(f"[{a_prev}][{k}:a]acrossfade=d={transition_s}[a{k}]")
            v_prev, a_prev = f"v{k}", f"a{k}"
            elapsed += decisions[k].duration - transition_s
        v_label, a_label, total = v_prev, a_prev, elapsed

    map_v, map_a = (f"[{v_label}]" if n > 1 else v_label), (f"[{a_label}]" if n > 1 else a_label)
    if bgm and Path(bgm).exists():
        inputs += ["-stream_loop", "-1", "-i", bgm]
        parts.append(f"[{n}:a]volume=0.10,aresample=44100,aformat=channel_layouts=stereo[bgm]")
        parts.append(f"{map_a}aresample=44100[nar];[nar][bgm]amix=inputs=2:duration=first:dropout_transition=0[aout]")
        map_a = "[aout]"

    args = [*inputs]
    if parts:
        args += ["-filter_complex", ";".join(parts)]
    args += [
        "-map", map_v, "-map", map_a, "-t", f"{total:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out),
    ]
    await _run(args)
    return out
