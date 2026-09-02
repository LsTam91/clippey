"""Chargement d'une charte créateur (TOML) — défaut embarqué toujours valide."""

from __future__ import annotations

import tomllib
from pathlib import Path

from .models import Charte

DEFAULT_CHARTE = Path(__file__).resolve().parent.parent.parent / "chartes" / "default.toml"


def load_charte(path: Path | None = None) -> Charte:
    target = path or DEFAULT_CHARTE
    if not target.exists():
        return Charte()
    with target.open("rb") as f:
        return Charte(**tomllib.load(f))
