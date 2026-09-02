"""État du pipeline en SQLite (WAL). Les données vivent dans data/<video_id>/, pas ici."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

DDL = """
CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT DEFAULT '',
    duration_s REAL DEFAULT 0,
    status TEXT DEFAULT 'pending',
    created_at REAL,
    meta_json TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS steps (
    video_id TEXT NOT NULL,
    step TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    params_hash TEXT DEFAULT '',
    started_at REAL,
    finished_at REAL,
    error TEXT DEFAULT '',
    PRIMARY KEY (video_id, step)
);
CREATE TABLE IF NOT EXISTS clips (
    clip_id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    t0 REAL, t1 REAL,
    weighted_score REAL,
    title TEXT DEFAULT '',
    file_path TEXT DEFAULT '',
    status TEXT DEFAULT 'ready',
    created_at REAL
);
CREATE TABLE IF NOT EXISTS ratings (
    clip_id TEXT NOT NULL,
    rater TEXT DEFAULT 'me',
    stars INTEGER NOT NULL,
    notes TEXT DEFAULT '',
    created_at REAL
);
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT,
    step TEXT,
    model TEXT,
    prompt_hash TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_eur REAL,
    cached INTEGER DEFAULT 0,
    created_at REAL
);
"""


class Db:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(DDL)

    def upsert_video(self, video_id: str, url: str, title: str, duration_s: float) -> None:
        self.conn.execute(
            "INSERT INTO videos (video_id, url, title, duration_s, created_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(video_id) DO UPDATE SET "
            "title=excluded.title, duration_s=excluded.duration_s",
            (video_id, url, title, duration_s, time.time()),
        )
        self.conn.commit()

    def step_status(self, video_id: str, step: str) -> tuple[str, str] | None:
        row = self.conn.execute(
            "SELECT status, params_hash FROM steps WHERE video_id=? AND step=?",
            (video_id, step),
        ).fetchone()
        return (row[0], row[1]) if row else None

    def step_start(self, video_id: str, step: str, params_hash: str) -> None:
        self.conn.execute(
            "INSERT INTO steps (video_id, step, status, params_hash, started_at) "
            "VALUES (?, ?, 'running', ?, ?) ON CONFLICT(video_id, step) DO UPDATE SET "
            "status='running', params_hash=excluded.params_hash, "
            "started_at=excluded.started_at, error=''",
            (video_id, step, params_hash, time.time()),
        )
        self.conn.commit()

    def step_finish(self, video_id: str, step: str, error: str = "") -> None:
        self.conn.execute(
            "UPDATE steps SET status=?, finished_at=?, error=? WHERE video_id=? AND step=?",
            ("failed" if error else "complete", time.time(), error, video_id, step),
        )
        self.conn.commit()

    def record_clip(
        self,
        clip_id: str,
        video_id: str,
        t0: float,
        t1: float,
        score: float,
        title: str,
        file_path: str,
    ) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO clips "
            "(clip_id, video_id, t0, t1, weighted_score, title, file_path, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (clip_id, video_id, t0, t1, score, title, file_path, time.time()),
        )
        self.conn.commit()

    def record_llm_call(
        self,
        video_id: str,
        step: str,
        model: str,
        prompt_hash: str,
        tokens_in: int,
        tokens_out: int,
        cost_eur: float,
        cached: bool,
    ) -> None:
        self.conn.execute(
            "INSERT INTO llm_calls (video_id, step, model, prompt_hash, "
            "tokens_in, tokens_out, cost_eur, cached, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                video_id,
                step,
                model,
                prompt_hash,
                tokens_in,
                tokens_out,
                cost_eur,
                int(cached),
                time.time(),
            ),
        )
        self.conn.commit()

    def video_cost_eur(self, video_id: str) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(cost_eur), 0) FROM llm_calls WHERE video_id=? AND cached=0",
            (video_id,),
        ).fetchone()
        return float(row[0])

    def add_rating(self, clip_id: str, stars: int, notes: str, rater: str = "me") -> None:
        self.conn.execute(
            "INSERT INTO ratings (clip_id, rater, stars, notes, created_at) VALUES (?, ?, ?, ?, ?)",
            (clip_id, rater, stars, notes, time.time()),
        )
        self.conn.commit()
