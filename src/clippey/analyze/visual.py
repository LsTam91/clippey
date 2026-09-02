"""Analyse visuelle sur le proxy 480p : cuts de scènes (PySceneDetect) et visages
échantillonnés (MediaPipe, boîtes normalisées [0,1]) → scenes.json, faces.json."""

from __future__ import annotations

import json
from pathlib import Path

from ..models import FaceSample, Scene
from ..pipeline import Context, write_json_atomic

SAMPLE_INTERVAL_S = 0.5


def step_visual(ctx: Context) -> None:
    proxy = str(ctx.paths["proxy"])
    scenes = _detect_scenes(proxy)
    faces = _sample_faces(proxy)
    write_json_atomic(
        ctx.paths["scenes"],
        json.dumps([s.model_dump() for s in scenes], indent=1),
    )
    write_json_atomic(
        ctx.paths["faces"],
        json.dumps([f.model_dump() for f in faces], indent=1),
    )
    with_face = sum(1 for f in faces if f.boxes)
    print(f"       {len(scenes)} scènes, {len(faces)} échantillons ({with_face} avec visage)")


def _detect_scenes(proxy: str) -> list[Scene]:
    from scenedetect import ContentDetector, detect

    scene_list = detect(proxy, ContentDetector())
    return [
        Scene(index=i, start=start.get_seconds(), end=end.get_seconds())
        for i, (start, end) in enumerate(scene_list)
    ]


def _sample_faces(proxy: str) -> list[FaceSample]:
    import cv2
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import FaceDetector, FaceDetectorOptions

    model = Path(__file__).resolve().parents[3] / "models" / "blaze_face_short_range.tflite"
    detector = FaceDetector.create_from_options(
        FaceDetectorOptions(
            base_options=BaseOptions(model_asset_path=str(model)),
            min_detection_confidence=0.5,
        )
    )

    cap = cv2.VideoCapture(proxy)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1.0
    height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1.0
    step = max(1, round(fps * SAMPLE_INTERVAL_S))
    samples: list[FaceSample] = []

    frame_idx = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if frame_idx % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
            )
            boxes: list[tuple[float, float, float, float]] = []
            for det in detector.detect(image).detections:
                bb = det.bounding_box  # pixels → normalisé [0,1]
                boxes.append(
                    (
                        round(bb.origin_x / width, 4),
                        round(bb.origin_y / height, 4),
                        round(bb.width / width, 4),
                        round(bb.height / height, 4),
                    )
                )
            samples.append(FaceSample(t=round(frame_idx / fps, 3), boxes=boxes))
        frame_idx += 1
    cap.release()
    detector.close()
    return samples
