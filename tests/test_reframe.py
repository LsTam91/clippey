"""Plan de crop : découpe aux scènes, visage dominant, hystérésis, fusion."""

from clippey.compose.reframe import build_crop_plan
from clippey.models import FaceSample, Scene, Segment


def faces_at(cx: float, t0: float, t1: float, size: float = 0.2) -> list[FaceSample]:
    return [
        FaceSample(t=t0 + i * 0.5, boxes=[(cx - size / 2, 0.2, size, size)])
        for i in range(int((t1 - t0) / 0.5) + 1)
    ]


def test_split_at_scene_cuts_with_distinct_crops():
    segments = [Segment(t0=10.0, t1=20.0)]
    scenes = [Scene(index=0, start=0, end=15.0), Scene(index=1, start=15.0, end=30.0)]
    faces = faces_at(0.25, 10.0, 14.5) + faces_at(0.75, 15.0, 20.0)
    plan = build_crop_plan(segments, scenes, faces, mode="face")
    assert len(plan) == 2
    assert plan[0].t1 == 15.0 and plan[1].t0 == 15.0
    assert plan[0].cx < 0.4 and plan[1].cx > 0.6


def test_hysteresis_keeps_stable_crop():
    """Visage quasi immobile entre deux scènes → un seul plan fusionné."""
    segments = [Segment(t0=0.0, t1=10.0)]
    scenes = [Scene(index=0, start=0, end=5.0), Scene(index=1, start=5.0, end=10.0)]
    faces = faces_at(0.50, 0.0, 4.5) + faces_at(0.53, 5.0, 10.0)  # +3 % < hystérésis
    plan = build_crop_plan(segments, scenes, faces, mode="face")
    assert len(plan) == 1
    assert plan[0].t0 == 0.0 and plan[0].t1 == 10.0


def test_no_face_inherits_previous_crop():
    segments = [Segment(t0=0.0, t1=10.0)]
    scenes = [Scene(index=0, start=0, end=5.0), Scene(index=1, start=5.0, end=10.0)]
    faces = faces_at(0.8, 0.0, 4.5)  # aucun visage après 5 s
    plan = build_crop_plan(segments, scenes, faces, mode="face")
    assert len(plan) == 1  # hérite du crop précédent → fusionné
    assert plan[0].cx == 0.8


def test_center_mode_ignores_faces():
    segments = [Segment(t0=0.0, t1=10.0)]
    faces = faces_at(0.9, 0.0, 10.0)
    plan = build_crop_plan(segments, [], faces, mode="center")
    assert len(plan) == 1
    assert plan[0].cx == 0.5


def test_multi_segment_chunks_cover_all_segments():
    segments = [Segment(t0=10.0, t1=15.0), Segment(t0=100.0, t1=110.0)]
    plan = build_crop_plan(segments, [], [], mode="face")
    assert plan[0].t0 == 10.0 and plan[0].t1 == 15.0
    assert plan[-1].t0 == 100.0 and plan[-1].t1 == 110.0
