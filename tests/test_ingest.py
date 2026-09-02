"""`step_ingest` n'a pas de test dans ce repo (yt-dlp et ffmpeg réels seraient
nécessaires pour un vrai passage bout en bout) — on ne vérifie ici QUE le changement
d'ordre introduit : `upsert_video` doit avoir lieu avant tout téléchargement, pour
qu'une vidéo qui échoue plus loin (réseau, geo-block...) reste marquée « vue » et ne
soit jamais reproposée par `clippey auto`. `_ytdlp` est le seul point d'entrée réseau
avant ce marquage : le faire échouer juste après suffit à isoler la question sans
toucher à ffmpeg ni au réseau."""

import json
from types import SimpleNamespace

import pytest

import clippey.ingest as ingest_module
from clippey.charte import load_charte
from clippey.config import AppConfig
from clippey.ingest import step_ingest
from clippey.pipeline import Context


class FakeDb:
    """Remplace `Db` : seule `upsert_video` est appelée avant l'échec simulé — la
    convention du repo garde les tests hors base de données réelle."""

    def __init__(self):
        self.upserted: list[tuple] = []

    def upsert_video(self, video_id, url, title, duration_s):
        self.upserted.append((video_id, url, title, duration_s))


def make_ctx(tmp_path, url="https://www.youtube.com/watch?v=vid42") -> Context:
    ctx = Context(
        config=AppConfig(data_dir=tmp_path),
        charte=load_charte(),
        db=FakeDb(),
        video_id="vid42",
    )
    ctx.extra["url"] = url
    return ctx


def test_step_ingest_marks_the_video_seen_before_the_download_even_when_it_fails_after(
    tmp_path, monkeypatch
):
    """Le déplacement testé : si `upsert_video` avait encore lieu APRÈS le téléchargement
    (comme avant ce changement), cet échec réseau simulé empêcherait tout enregistrement
    et `ctx.db.upserted` resterait vide."""
    ctx = make_ctx(tmp_path)
    calls: list[tuple] = []

    def fake_ytdlp(_ctx, *args):
        calls.append(args)
        if "-J" in args:
            info = {"id": "vid42", "title": "Titre source", "duration": 300}
            return SimpleNamespace(stdout=json.dumps(info))
        raise RuntimeError("réseau indisponible pendant le téléchargement")

    monkeypatch.setattr(ingest_module, "_ytdlp", fake_ytdlp)

    with pytest.raises(RuntimeError, match="réseau indisponible"):
        step_ingest(ctx)

    assert ctx.db.upserted == [
        ("vid42", "https://www.youtube.com/watch?v=vid42", "Titre source", 300.0)
    ]
    assert len(calls) == 2  # métadonnées, puis la tentative de téléchargement qui échoue
