"""Persistent pipeline state (SQLite). Jobs and scenes each carry their own status."""

import json
import sqlite3
import time
import uuid
from contextlib import closing
from enum import Enum
from pathlib import Path
from typing import Any


class JobStatus(str, Enum):
    CREATED = "CREATED"
    SCRIPTED = "SCRIPTED"
    SCENES_PLANNED = "SCENES_PLANNED"
    VISUALS_GENERATED = "VISUALS_GENERATED"
    AUDIO_GENERATED = "AUDIO_GENERATED"
    ASSEMBLING = "ASSEMBLING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class StepStatus(str, Enum):
    PENDING = "PENDING"
    GENERATING = "GENERATING"
    GENERATED = "GENERATED"
    FAILED = "FAILED"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    prompt TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT,
    script_json TEXT,
    plan_json TEXT,
    error TEXT,
    output_path TEXT,
    created_at REAL,
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS scenes (
    job_id TEXT NOT NULL,
    scene_id INTEGER NOT NULL,
    plan_json TEXT NOT NULL,
    visual_status TEXT NOT NULL DEFAULT 'PENDING',
    visual_attempts INTEGER NOT NULL DEFAULT 0,
    visual_path TEXT,
    audio_status TEXT NOT NULL DEFAULT 'PENDING',
    audio_attempts INTEGER NOT NULL DEFAULT 0,
    audio_path TEXT,
    audio_duration REAL,
    error TEXT,
    PRIMARY KEY (job_id, scene_id)
);
"""

_JOB_COLS = {"status", "title", "script_json", "plan_json", "error", "output_path"}
_SCENE_COLS = {
    "visual_status", "visual_attempts", "visual_path",
    "audio_status", "audio_attempts", "audio_path", "audio_duration", "error",
}


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as c, c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    def _write(self, sql: str, params: tuple = ()) -> None:
        with closing(self._conn()) as c, c:
            c.execute(sql, params)

    @staticmethod
    def _set_clause(fields: dict[str, Any], allowed: set[str]) -> tuple[str, list]:
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown columns: {bad}")
        return ", ".join(f"{k} = ?" for k in fields), list(fields.values())

    # ---- jobs ----
    def create_job(self, prompt: str) -> str:
        job_id = uuid.uuid4().hex[:12]
        now = time.time()
        self._write(
            "INSERT INTO jobs (id, prompt, status, created_at, updated_at) VALUES (?,?,?,?,?)",
            (job_id, prompt, JobStatus.CREATED.value, now, now),
        )
        return job_id

    def update_job(self, job_id: str, **fields: Any) -> None:
        for k in ("status",):
            if isinstance(fields.get(k), Enum):
                fields[k] = fields[k].value
        clause, vals = self._set_clause(fields, _JOB_COLS)
        self._write(f"UPDATE jobs SET {clause}, updated_at = ? WHERE id = ?", (*vals, time.time(), job_id))

    def get_job(self, job_id: str) -> dict | None:
        with closing(self._conn()) as c:
            row = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        job = dict(row)
        job["script"] = json.loads(job.pop("script_json")) if job.get("script_json") else None
        job["plan"] = json.loads(job.pop("plan_json")) if job.get("plan_json") else None
        return job

    def list_jobs(self, limit: int = 20) -> list[dict]:
        with closing(self._conn()) as c:
            rows = c.execute(
                "SELECT id, prompt, status, title, created_at FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- scenes ----
    def save_scenes(self, job_id: str, scenes: list[dict]) -> None:
        with closing(self._conn()) as c, c:
            c.execute("DELETE FROM scenes WHERE job_id = ?", (job_id,))
            c.executemany(
                "INSERT INTO scenes (job_id, scene_id, plan_json) VALUES (?,?,?)",
                [(job_id, s["id"], json.dumps(s)) for s in scenes],
            )

    def update_scene(self, job_id: str, scene_id: int, **fields: Any) -> None:
        for k in ("visual_status", "audio_status"):
            if isinstance(fields.get(k), Enum):
                fields[k] = fields[k].value
        clause, vals = self._set_clause(fields, _SCENE_COLS)
        self._write(
            f"UPDATE scenes SET {clause} WHERE job_id = ? AND scene_id = ?", (*vals, job_id, scene_id)
        )

    def bump_attempts(self, job_id: str, scene_id: int, kind: str, error: str) -> None:
        col = f"{kind}_attempts"
        self._write(
            f"UPDATE scenes SET {col} = {col} + 1, error = ? WHERE job_id = ? AND scene_id = ?",
            (error, job_id, scene_id),
        )

    def list_scenes(self, job_id: str) -> list[dict]:
        with closing(self._conn()) as c:
            rows = c.execute(
                "SELECT * FROM scenes WHERE job_id = ? ORDER BY scene_id", (job_id,)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            plan = json.loads(d.pop("plan_json"))
            out.append({**plan, **d})
        return out

    def reset_scene(self, job_id: str, scene_id: int) -> None:
        """Make a scene eligible for regeneration; other scenes are untouched."""
        self._write(
            "UPDATE scenes SET visual_status='PENDING', audio_status='PENDING', visual_attempts=0,"
            " audio_attempts=0, error=NULL WHERE job_id = ? AND scene_id = ?",
            (job_id, scene_id),
        )
