"""Runner séquentiel avec resume : une étape déjà `complete` dont le params_hash
n'a pas changé est sautée ; un changement de config ou de version de prompt
invalide l'étape et toutes les suivantes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import AppConfig
from .db import Db
from .models import Charte, artifact_paths


@dataclass
class Context:
    config: AppConfig
    charte: Charte
    db: Db
    video_id: str
    paths: dict[str, Path] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.paths:
            self.paths = artifact_paths(self.config.data_dir, self.video_id)
            self.paths["root"].mkdir(parents=True, exist_ok=True)


@dataclass
class Step:
    name: str
    fn: Callable[[Context], None]
    # clés de config/charte dont dépend l'étape → params_hash
    params: Callable[[Context], dict[str, Any]]


def params_hash(values: dict[str, Any]) -> str:
    payload = json.dumps(values, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def run_steps(ctx: Context, steps: list[Step], until: str | None = None) -> None:
    stale = False
    for step in steps:
        h = params_hash(step.params(ctx))
        state = ctx.db.step_status(ctx.video_id, step.name)
        if not stale and state and state[0] == "complete" and state[1] == h:
            print(f"[skip] {step.name} (déjà fait, params inchangés)")
        else:
            stale = True  # invalide toutes les étapes suivantes
            print(f"[run ] {step.name}")
            ctx.db.step_start(ctx.video_id, step.name, h)
            try:
                step.fn(ctx)
            except Exception as e:
                ctx.db.step_finish(ctx.video_id, step.name, error=str(e))
                raise
            ctx.db.step_finish(ctx.video_id, step.name)
        if until and step.name == until:
            return


def write_json_atomic(path: Path, payload: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.rename(path)
