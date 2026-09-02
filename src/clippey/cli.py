"""CLI clippey — chaque étape est une commande ; `run` enchaîne tout avec resume."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .analyze.asr import step_asr
from .analyze.audio_events import step_audio
from .analyze.visual import step_visual
from .caption import step_caption
from .charte import load_charte
from .compose.render import step_compose
from .config import load_config
from .db import Db
from .ingest import extract_video_id, step_ingest
from .package import step_package
from .pipeline import Context, Step, run_steps
from .select import prompts
from .select.brain import step_select

app = typer.Typer(help="Pipeline de clipping : vidéo longue → clips verticaux prêts à publier.")

CharteOpt = Annotated[Path | None, typer.Option("--charte", help="Charte créateur TOML")]


def _steps() -> list[Step]:
    return [
        Step("ingest", step_ingest, lambda c: {"url": c.extra.get("url", "")}),
        Step(
            "asr",
            step_asr,
            lambda c: {
                "asr": c.config.asr.model_dump(),
                "lang": c.charte.language,
            },
        ),
        Step("audio", step_audio, lambda c: {"energy": "rms-1hz-v1"}),
        Step(
            "visual",
            step_visual,
            lambda c: {"sample_interval": 0.5, "detector": "content-v1"},
        ),
        Step(
            "select",
            step_select,
            lambda c: {
                "prompt_version": prompts.PROMPT_VERSION,
                "model": c.config.llm.model,
                "ranking": c.config.ranking.model_dump(),
                "clips": c.charte.clips.model_dump(),
                "tone": c.charte.tone,
            },
        ),
        Step(
            "compose",
            step_compose,
            lambda c: {
                "captions": c.charte.captions.model_dump(),
                "hook": c.charte.hook.model_dump(),
                "reframe": c.charte.reframe.model_dump(),
            },
        ),
        Step(
            "caption",
            step_caption,
            lambda c: {
                "prompt_version": prompts.CAPTION_PROMPT_VERSION,
                "model": c.config.llm.model,
                "hashtags": c.charte.hashtags.model_dump(),
                "caption_max_chars": c.charte.clips.caption_max_chars,
                "language": c.charte.language,
                "tone": c.charte.tone,
            },
        ),
        Step("package", step_package, lambda c: {"hashtags": c.charte.hashtags.model_dump()}),
    ]


def _db() -> Db:
    return Db(load_config().data_dir / "clippey.db")


def _context(video_id: str, charte_path: Path | None, url: str = "") -> Context:
    config = load_config()
    charte = load_charte(charte_path)
    db = Db(config.data_dir / "clippey.db")
    ctx = Context(config=config, charte=charte, db=db, video_id=video_id)
    if url:
        ctx.extra["url"] = url
    return ctx


def _video_id_or_exit(url: str) -> str:
    video_id = extract_video_id(url)
    if not video_id:
        typer.echo("URL YouTube non reconnue (attendu : watch?v=, youtu.be/, shorts/)")
        raise typer.Exit(1)
    return video_id


@app.command()
def run(
    url: str,
    charte: CharteOpt = None,
    until: Annotated[str | None, typer.Option(help="S'arrêter après cette étape")] = None,
) -> None:
    """Pipeline complet : ingest → asr → select → compose → caption → package."""
    video_id = _video_id_or_exit(url)
    ctx = _context(video_id, charte, url=url)
    run_steps(ctx, _steps(), until=until)
    cost = ctx.db.video_cost_eur(video_id)
    typer.echo(f"Terminé. Coût API : {cost:.3f} € — review : {ctx.paths['review']}")


def _single(step_name: str, video_id: str, charte: Path | None, url: str = "") -> None:
    ctx = _context(video_id, charte, url=url)
    step = next(s for s in _steps() if s.name == step_name)
    from .pipeline import params_hash

    ctx.db.step_start(video_id, step.name, params_hash(step.params(ctx)))
    try:
        step.fn(ctx)
    except Exception as e:
        ctx.db.step_finish(video_id, step.name, error=str(e))
        raise
    ctx.db.step_finish(video_id, step.name)


@app.command()
def ingest(url: str, charte: CharteOpt = None) -> None:
    """Télécharge et normalise une vidéo."""
    _single("ingest", _video_id_or_exit(url), charte, url=url)


@app.command()
def asr(video_id: str, charte: CharteOpt = None) -> None:
    """Transcription mots + phrases."""
    _single("asr", video_id, charte)


@app.command()
def visual(video_id: str, charte: CharteOpt = None) -> None:
    """Scènes + visages (recadrage intelligent)."""
    _single("visual", video_id, charte)


@app.command()
def select(video_id: str, charte: CharteOpt = None) -> None:
    """Sélection des moments (LLM)."""
    _single("select", video_id, charte)


@app.command()
def compose(video_id: str, charte: CharteOpt = None) -> None:
    """Rendu des clips (crop, sous-titres, encodage)."""
    _single("compose", video_id, charte)


@app.command()
def caption(video_id: str, charte: CharteOpt = None) -> None:
    """Légendes : titre, description, hashtags (LLM)."""
    _single("caption", video_id, charte)


@app.command()
def package(video_id: str, charte: CharteOpt = None) -> None:
    """Manifest + galerie de review."""
    _single("package", video_id, charte)


@app.command()
def batch(
    urls: Annotated[Path, typer.Argument(help="Fichier texte : une URL YouTube par ligne")],
    charte: CharteOpt = None,
) -> None:
    """Traite une liste d'URLs YouTube — les échecs n'interrompent pas le lot."""
    if not urls.exists():
        typer.echo(f"Fichier introuvable : {urls}")
        raise typer.Exit(1)
    lines = [ln.strip() for ln in urls.read_text(encoding="utf-8").splitlines()]
    targets = [ln for ln in lines if ln and not ln.startswith("#")]
    ok, total = 0, 0.0
    for url in targets:
        video_id = extract_video_id(url)
        if not video_id:
            typer.echo(f"[skip] URL YouTube non reconnue : {url}")
            continue
        typer.echo(f"=== {video_id}")
        ctx = _context(video_id, charte, url=url)
        try:
            run_steps(ctx, _steps())
            ok += 1
        except Exception as e:
            typer.echo(f"[fail] {video_id} : {e}")
        total += ctx.db.video_cost_eur(video_id)
    typer.echo(f"{ok}/{len(targets)} vidéos traitées, coût total {total:.3f} €")


@app.command()
def rate(
    clip_id: str,
    stars: Annotated[int, typer.Option(min=1, max=5)],
    notes: str = "",
) -> None:
    """Note un clip (1-5) — alimente l'éval."""
    _db().add_rating(clip_id, stars, notes)
    typer.echo(f"{clip_id} : {stars}/5")


@app.command()
def status(video_id: str) -> None:
    """État des étapes et coût d'une vidéo."""
    db = _db()
    rows = db.conn.execute(
        "SELECT step, status, COALESCE(finished_at - started_at, 0), error "
        "FROM steps WHERE video_id=? ORDER BY started_at",
        (video_id,),
    ).fetchall()
    for step, st, dur, err in rows:
        line = f"{step:10s} {st:9s} {dur:6.1f}s"
        if err:
            line += f"  ! {err[:80]}"
        typer.echo(line)
    typer.echo(f"Coût API : {db.video_cost_eur(video_id):.3f} €")


if __name__ == "__main__":
    app()
