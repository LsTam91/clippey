"""Graphe de filtres ffmpeg : gel de fin, fondu audio, échappement du chemin ASS."""

from clippey.compose.reframe import CropChunk
from clippey.compose.render import build_filter_graph

LOUDNORM = "loudnorm=I=-14:TP=-2:LRA=7:measured_I=-16.5:linear=true"


def chunks():
    return [CropChunk(t0=0.0, t1=5.0, cx=0.5), CropChunk(t0=5.0, t1=9.0, cx=0.4)]


def graph(freeze: float, total: float, ass_path: str = "/tmp/clip.ass"):
    return build_filter_graph(chunks(), ass_path, "fonts", LOUDNORM, freeze, total)


def test_graph_without_freeze_is_unchanged():
    lines = graph(0.0, 9.0)
    assert not any("tpad" in line or "apad" in line or "afade" in line for line in lines)
    assert lines[-1] == f"[ac]{LOUDNORM}[aout]"
    assert lines[-2].startswith("[vc]ass=")


def test_graph_with_freeze_inserts_tpad_and_apad():
    lines = graph(0.7, 9.7)
    assert "[vc]tpad=stop_mode=clone:stop_duration=0.700[vp]" in lines
    assert lines[-2].startswith("[vp]ass=")
    audio = lines[-1]
    assert audio.index("apad=pad_dur=0.700") > audio.index("loudnorm")  # mesure faite avant
    # audio réel : 9.7 - 0.7 = 9.0 s ; fondu de 0.3 s AVANT le silence ajouté
    assert "afade=t=out:st=8.700:d=0.300" in audio


def test_graph_short_freeze_shortens_fade():
    """Fondu jamais plus long que le gel (sinon il mordrait trop sur la parole)."""
    # audio réel : 9.15 - 0.15 = 9.0 s ; fondu ramené à 0.15 s → départ à 8.85 s
    assert "afade=t=out:st=8.850:d=0.150" in graph(0.15, 9.15)[-1]


def test_graph_escapes_ass_path():
    ass_line = graph(0.0, 9.0, ass_path="/tmp/a:b/clip.ass")[-2]
    assert "/tmp/a\\:b/clip.ass" in ass_line
