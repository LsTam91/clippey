"""Plan de crop 9:16 : chaque segment est découpé aux frontières de scènes, chaque
morceau reçoit un centre horizontal (visage dominant médian). Crop statique par
morceau — pas de pan continu — avec hystérésis pour éviter les sauts parasites."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import FaceSample, Scene, Segment

HYSTERESIS = 0.06  # déplacement minimal (fraction de largeur) pour bouger le crop


@dataclass
class CropChunk:
    t0: float
    t1: float
    cx: float  # centre horizontal normalisé [0,1]


def build_crop_plan(
    segments: list[Segment],
    scenes: list[Scene],
    faces: list[FaceSample],
    mode: str = "face",
) -> list[CropChunk]:
    chunks: list[CropChunk] = []
    prev_cx = 0.5
    for seg in segments:
        for t0, t1 in _split_at_scene_cuts(seg, scenes):
            cx = 0.5
            if mode == "face":
                face_cx = _dominant_face_cx(faces, t0, t1)
                if face_cx is not None:
                    cx = face_cx
                elif chunks:
                    cx = prev_cx  # pas de visage → on garde le cadrage précédent
            if abs(cx - prev_cx) < HYSTERESIS:
                cx = prev_cx
            chunks.append(CropChunk(t0=t0, t1=t1, cx=cx))
            prev_cx = cx
    return _merge_same_crop(chunks)


def _split_at_scene_cuts(seg: Segment, scenes: list[Scene]) -> list[tuple[float, float]]:
    cuts = sorted(s.start for s in scenes if seg.t0 + 0.25 < s.start < seg.t1 - 0.25)
    bounds = [seg.t0, *cuts, seg.t1]
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]


def _dominant_face_cx(faces: list[FaceSample], t0: float, t1: float) -> float | None:
    """Médiane du centre x du plus grand visage de chaque échantillon du morceau."""
    centers = []
    for sample in faces:
        if t0 <= sample.t <= t1 and sample.boxes:
            x, _, w, h = max(sample.boxes, key=lambda b: b[2] * b[3])
            centers.append(x + w / 2)
    if not centers:
        return None
    centers.sort()
    return centers[len(centers) // 2]


def _merge_same_crop(chunks: list[CropChunk]) -> list[CropChunk]:
    """Fusionne les morceaux contigus au même cadrage (moins d'entrées ffmpeg)."""
    merged: list[CropChunk] = []
    for c in chunks:
        prev = merged[-1] if merged else None
        if prev and prev.cx == c.cx and abs(prev.t1 - c.t0) < 0.001:
            prev.t1 = c.t1
        else:
            merged.append(c)
    return merged


def crop_x_expr(cx: float) -> str:
    """Expression ffmpeg du bord gauche du crop (clampée dans l'image)."""
    return f"max(0\\,min(iw-ih*9/16\\,iw*{cx:.4f}-ih*9/32))"
