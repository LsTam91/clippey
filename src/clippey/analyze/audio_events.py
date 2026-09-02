"""Courbe d'énergie audio (RMS 1 Hz, z-scores) → energy.json.

Les pics d'énergie (rires, cris, foule) signalent des moments que le transcript seul
ne voit pas : ils sont transmis au LLM en même temps que la transcription."""

from __future__ import annotations

import json
import wave

import numpy as np

from ..pipeline import Context, write_json_atomic

WINDOW_S = 1.0
SMOOTH_S = 5


def step_audio(ctx: Context) -> None:
    with wave.open(str(ctx.paths["audio"]), "rb") as f:
        rate = f.getframerate()
        pcm = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)

    samples_per_win = int(rate * WINDOW_S)
    n = len(pcm) // samples_per_win
    windows = pcm[: n * samples_per_win].astype(np.float32).reshape(n, samples_per_win)
    rms = np.sqrt((windows**2).mean(axis=1) + 1e-9)
    rms = np.convolve(rms, np.ones(SMOOTH_S) / SMOOTH_S, mode="same")  # lissage
    z = (rms - rms.mean()) / (rms.std() + 1e-9)

    points = [{"t": float(i * WINDOW_S), "z": round(float(z[i]), 3)} for i in range(n)]
    write_json_atomic(ctx.paths["energy"], json.dumps(points))
    print(f"       {n} s analysées, z max {z.max():.1f}")


def energy_peaks(
    points: list[dict], z_min: float = 2.0, min_gap_s: float = 20.0, top: int = 8
) -> list[tuple[float, float]]:
    """Maxima locaux (t, z) au-dessus de z_min, espacés d'au moins min_gap_s."""
    candidates = sorted((p for p in points if p["z"] >= z_min), key=lambda p: -p["z"])
    peaks: list[tuple[float, float]] = []
    for p in candidates:
        if all(abs(p["t"] - t) >= min_gap_s for t, _ in peaks):
            peaks.append((p["t"], p["z"]))
        if len(peaks) >= top:
            break
    return sorted(peaks)
