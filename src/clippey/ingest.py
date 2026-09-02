"""Téléchargement + normalisation : source.mp4 → norm.mp4 (timebase canonique),
audio.wav 16 kHz mono et proxy480.mp4 extraits du fichier normalisé."""

from __future__ import annotations

import json
import re
import subprocess
import sys

from .models import HeatmapPoint, VideoMeta
from .pipeline import Context, write_json_atomic

_ID_PATTERNS = [
    r"[?&]v=([\w-]{11})",
    r"youtu\.be/([\w-]{11})",
    r"/shorts/([\w-]{11})",
    r"/live/([\w-]{11})",
]


def extract_video_id(url: str) -> str | None:
    for pat in _ID_PATTERNS:
        if m := re.search(pat, url):
            return m.group(1)
    return None


def _ytdlp(ctx: Context, *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "yt_dlp", *args]
    if ctx.config.cookies_from_browser:
        cmd += ["--cookies-from-browser", ctx.config.cookies_from_browser]
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def _ffmpeg(ctx: Context, *args: str) -> None:
    subprocess.run(
        [ctx.config.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error", *args],
        check=True,
    )


def probe(ctx: Context, path: str) -> dict:
    out = subprocess.run(
        [
            ctx.config.ffprobe_path,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def step_ingest(ctx: Context) -> None:
    url = ctx.extra["url"]
    p = ctx.paths

    info_raw = _ytdlp(ctx, "-J", "--skip-download", url).stdout
    info = json.loads(info_raw)

    meta = VideoMeta(
        video_id=info["id"],
        url=url,
        title=info.get("title", ""),
        channel=info.get("channel") or info.get("uploader", ""),
        duration_s=float(info.get("duration") or 0),
        fps=float(info.get("fps") or 0),
        width=int(info.get("width") or 0),
        height=int(info.get("height") or 0),
        language=info.get("language") or ctx.config.language,
        upload_date=info.get("upload_date", ""),
        heatmap=[
            HeatmapPoint(start=h["start_time"], end=h["end_time"], value=h["value"])
            for h in (info.get("heatmap") or [])
        ],
    )
    # Enregistré avant tout téléchargement/ré-encodage : une vidéo qui échoue plus loin
    # (réseau, geo-block, retrait) garde une trace exploitable par `clippey status`.
    ctx.db.upsert_video(meta.video_id, url, meta.title, meta.duration_s)

    if not p["source"].exists():
        _ytdlp(
            ctx,
            "-f",
            "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/b",
            "--merge-output-format",
            "mp4",
            "-o",
            str(p["source"]),
            url,
        )

    # Timebase canonique : remux suffit si start_time≈0 et CFR ; sinon ré-encodage CFR.
    src = probe(ctx, str(p["source"]))
    vstream = next(s for s in src["streams"] if s["codec_type"] == "video")
    start_time = float(vstream.get("start_time") or 0)
    cfr = vstream.get("r_frame_rate") == vstream.get("avg_frame_rate")
    if abs(start_time) < 0.01 and cfr:
        _ffmpeg(
            ctx, "-i", str(p["source"]), "-c", "copy", "-movflags", "+faststart", str(p["norm"])
        )
    else:
        from fractions import Fraction

        try:
            fps = round(float(Fraction(vstream["avg_frame_rate"]))) or 30
        except (ValueError, ZeroDivisionError):
            fps = 30
        _ffmpeg(
            ctx,
            "-i",
            str(p["source"]),
            "-r",
            str(fps),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(p["norm"]),
        )

    _ffmpeg(ctx, "-i", str(p["norm"]), "-vn", "-ac", "1", "-ar", "16000", str(p["audio"]))
    _ffmpeg(
        ctx,
        "-i",
        str(p["norm"]),
        "-an",
        "-vf",
        "scale=-2:480",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "28",
        str(p["proxy"]),
    )

    write_json_atomic(p["meta"], meta.model_dump_json(indent=1))
