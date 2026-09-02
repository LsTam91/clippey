"""Rendu ffmpeg multi-segments : une entrée par morceau du plan de crop (seek précis),
crop 9:16 par morceau, concat, souffle de fin (dernière image gelée + fondu audio),
burn ASS sur la timeline assemblée, loudnorm -14 LUFS en 2 passes sur l'audio
concaténé. Un seul encodage par clip."""

from __future__ import annotations

import json
import subprocess

from ..models import Clip, FaceSample, Scene, Selection, Transcript, Word
from ..pipeline import Context
from .reframe import CropChunk, build_crop_plan, crop_x_expr
from .subtitles import generate_ass

LOUDNORM_TARGET = "I=-14:TP=-2:LRA=7"
FADE_OUT_S = 0.3


def step_compose(ctx: Context) -> None:
    selection = Selection.model_validate_json(ctx.paths["selection"].read_text())
    transcript = Transcript.model_validate_json(ctx.paths["transcript"].read_text())
    scenes = _load_scenes(ctx)
    faces = _load_faces(ctx)
    ctx.paths["clips_dir"].mkdir(parents=True, exist_ok=True)

    for clip in selection.clips:
        chunks = build_crop_plan(clip.segments, scenes, faces, ctx.charte.reframe.mode)
        out = ctx.paths["clips_dir"] / f"{clip.id}.mp4"
        ass_path = ctx.paths["clips_dir"] / f"{clip.id}.ass"
        ass_path.write_text(
            generate_ass(_rebased_words(clip, transcript), 0.0, clip.hook_overlay, ctx.charte),
            encoding="utf-8",
        )
        render_clip(ctx, chunks, str(ass_path), str(out), clip.total_duration, clip.freeze_tail_s)
        clip.file_path = str(out)
        print(
            f"       {out.name} ({clip.total_duration:.0f}s, {len(clip.segments)} seg, "
            f"{len(chunks)} plans de crop, score {clip.weighted_score})"
        )

    ctx.paths["selection"].write_text(selection.model_dump_json(indent=1))


def _rebased_words(clip: Clip, transcript: Transcript) -> list[Word]:
    """Mots de chaque segment, rebasés sur la timeline concaténée du clip."""
    words: list[Word] = []
    offset = 0.0
    for seg in clip.segments:
        for w in transcript.words_between(seg.t0, seg.t1):
            words.append(
                w.model_copy(
                    update={"start": w.start - seg.t0 + offset, "end": w.end - seg.t0 + offset}
                )
            )
        offset += seg.duration
    return words


def build_filter_graph(
    chunks: list[CropChunk],
    ass_path: str,
    fonts_dir: str,
    loudnorm: str,
    freeze_tail_s: float,
    total_duration: float,
) -> list[str]:
    """Graphe de filtres complet : crop par morceau, concat, gel de fin, ASS, loudnorm.

    `apad` DOIT rester après `loudnorm` : la passe de mesure ne voit pas le silence
    ajouté, l'insérer avant fausserait les statistiques mesurées.
    """
    graph = []
    for i, c in enumerate(chunks):
        graph.append(
            f"[{i}:v]crop=min(iw\\,ih*9/16):ih:{crop_x_expr(c.cx)}:0,scale=1080:1920,setsar=1[v{i}]"
        )
    pairs = "".join(f"[v{i}][{i}:a]" for i in range(len(chunks)))
    graph.append(f"{pairs}concat=n={len(chunks)}:v=1:a=1[vc][ac]")

    if freeze_tail_s <= 0.01:
        graph.append(f"[vc]ass={_escape_filter_path(ass_path)}:fontsdir={fonts_dir}[vout]")
        graph.append(f"[ac]{loudnorm}[aout]")
        return graph

    # Le fondu s'ancre sur la FIN DE L'AUDIO RÉEL, pas sur celle du fichier : placé dans
    # le silence ajouté par apad, il n'atténuerait rien et la coupure du fond sonore
    # resterait audible.
    fade = min(FADE_OUT_S, freeze_tail_s)
    fade_start = max(0.0, (total_duration - freeze_tail_s) - fade)
    graph.append(f"[vc]tpad=stop_mode=clone:stop_duration={freeze_tail_s:.3f}[vp]")
    graph.append(f"[vp]ass={_escape_filter_path(ass_path)}:fontsdir={fonts_dir}[vout]")
    graph.append(
        f"[ac]{loudnorm},apad=pad_dur={freeze_tail_s:.3f},"
        f"afade=t=out:st={fade_start:.3f}:d={fade:.3f}[aout]"
    )
    return graph


def render_clip(
    ctx: Context,
    chunks: list[CropChunk],
    ass_path: str,
    out_path: str,
    expected_duration: float,
    freeze_tail_s: float = 0.0,
) -> None:
    norm = str(ctx.paths["norm"])
    inputs: list[str] = []
    for c in chunks:
        inputs += ["-ss", f"{c.t0:.3f}", "-t", f"{c.t1 - c.t0:.3f}", "-i", norm]

    measured = _loudnorm_measure(ctx, inputs, len(chunks))
    loudnorm = (
        f"loudnorm={LOUDNORM_TARGET}:measured_I={measured['input_i']}"
        f":measured_TP={measured['input_tp']}:measured_LRA={measured['input_lra']}"
        f":measured_thresh={measured['input_thresh']}:offset={measured['target_offset']}"
        ":linear=true"
    )

    graph = build_filter_graph(
        chunks,
        ass_path,
        str(ctx.config.fonts_dir),
        loudnorm,
        freeze_tail_s,
        expected_duration,
    )

    _run(
        [
            ctx.config.ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            *inputs,
            "-filter_complex",
            ";".join(graph),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            out_path,
        ]
    )
    _validate(ctx, out_path, expected_duration)


def _loudnorm_measure(ctx: Context, inputs: list[str], n: int) -> dict:
    pairs = "".join(f"[{i}:a]" for i in range(n))
    graph = (
        f"{pairs}concat=n={n}:v=0:a=1[ac];[ac]loudnorm={LOUDNORM_TARGET}:print_format=json[aout]"
    )
    proc = subprocess.run(
        [
            ctx.config.ffmpeg_path,
            "-hide_banner",
            "-nostats",
            *inputs,
            "-filter_complex",
            graph,
            "-map",
            "[aout]",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stderr = proc.stderr
    start = stderr.find("{", stderr.rfind("Parsed_loudnorm"))
    if start < 0:
        raise RuntimeError(f"Sortie loudnorm introuvable :\n{stderr[-500:]}")
    obj, _ = json.JSONDecoder().raw_decode(stderr[start:])
    return obj


def _load_scenes(ctx: Context) -> list[Scene]:
    if not ctx.paths["scenes"].exists():
        return []
    return [Scene(**s) for s in json.loads(ctx.paths["scenes"].read_text())]


def _load_faces(ctx: Context) -> list[FaceSample]:
    if not ctx.paths["faces"].exists():
        return []
    return [FaceSample(**f) for f in json.loads(ctx.paths["faces"].read_text())]


def _validate(ctx: Context, out_path: str, expected_duration: float) -> None:
    out = subprocess.run(
        [ctx.config.ffprobe_path, "-v", "quiet", "-print_format", "json", "-show_format", out_path],
        capture_output=True,
        text=True,
        check=True,
    )
    actual = float(json.loads(out.stdout)["format"]["duration"])
    if abs(actual - expected_duration) > 1.0:
        raise RuntimeError(
            f"Durée rendue {actual:.1f}s ≠ attendue {expected_duration:.1f}s ({out_path})"
        )


def _escape_filter_path(path: str) -> str:
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)
