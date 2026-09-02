"""Légendes : une passe LLM dédiée sur le texte réel de chaque clip retenu.

Séparée de `select` à dessein — retoucher la copie (titre, description, hashtags) ne
doit pas invalider la sélection ni relancer un rendu complet.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .models import CaptionSet, Charte, Clip, ClipCaption, Selection, Transcript
from .package import build_caption
from .pipeline import Context, write_json_atomic
from .select.brain import merge_hashtags
from .select.llm import LLMClient
from .select.prompts import caption_system

MAX_TITLE_CHARS = 90
MAX_CLIP_TEXT_CHARS = 1500
# Repli quand la charte n'en fixe pas d'autre (`[clips] caption_max_chars`). Le prompt
# vise déjà ce budget, mais on l'impose aussi en code : un prompt ne garantit jamais
# une contrainte dure, seul un filet de sécurité déterministe le peut.
DEFAULT_CAPTION_MAX_CHARS = 150


class CaptionResponse(BaseModel):
    captions: list[ClipCaption] = Field(default_factory=list)


def step_caption(ctx: Context) -> None:
    budget = ctx.charte.clips.caption_max_chars
    selection = Selection.model_validate_json(ctx.paths["selection"].read_text())
    fallback = enforce_caption_budget(_fallback(ctx.video_id, selection.clips, ctx.charte), budget)
    if not selection.clips:
        write_json_atomic(ctx.paths["captions"], fallback.model_dump_json(indent=1))
        return

    transcript = Transcript.model_validate_json(ctx.paths["transcript"].read_text())
    try:
        client = LLMClient(ctx.config.llm, ctx.db, ctx.video_id, "caption", ctx.paths["llm_cache"])
        response = client.chat_json(
            caption_system(ctx.charte),
            "\n\n".join(_cards(selection.clips, transcript)),
            CaptionResponse,
            temperature=0.7,
        )
    except Exception as e:
        # Aucune exception ne doit sortir d'ici : sans captions.json, package ne
        # tournerait pas et l'utilisateur n'aurait ni manifest ni galerie de review.
        # Volontairement `Exception` : une réponse HTTP 200 mais hors schéma (proxy
        # renvoyant {"error": ...}) lève un KeyError.
        print(f"       légendes LLM indisponibles ({e}) — titres du juge conservés")
        write_json_atomic(ctx.paths["captions"], fallback.model_dump_json(indent=1))
        return

    captions = enforce_caption_budget(
        merge_response(selection.clips, response, ctx.charte, fallback), budget
    )
    write_json_atomic(ctx.paths["captions"], captions.model_dump_json(indent=1))
    print(f"       {len(captions.clips)} légendes écrites")


def _fallback(video_id: str, clips: list[Clip], charte: Charte) -> CaptionSet:
    """Repli : la copie produite par le juge, hashtags passés par la charte."""
    return CaptionSet(
        video_id=video_id,
        clips=[
            ClipCaption(
                clip_id=c.id,
                title=c.title,
                description=c.description,
                hashtags=merge_hashtags(c.hashtags, charte),
            )
            for c in clips
        ],
    )


def _cards(clips: list[Clip], transcript: Transcript) -> list[str]:
    cards = []
    for c in clips:
        text = " ".join(
            w.text for seg in c.segments for w in transcript.words_between(seg.t0, seg.t1)
        )[:MAX_CLIP_TEXT_CHARS]
        cards.append(f'clip_id: {c.id}\ntitre provisoire : "{c.title}"\ntexte du clip : « {text} »')
    return cards


def merge_response(
    clips: list[Clip],
    response: CaptionResponse,
    charte: Charte,
    fallback: CaptionSet,
) -> CaptionSet:
    """Fusionne la réponse LLM sur le repli : clip_id inconnu ou champ vide → repli gardé."""
    known = {c.id for c in clips}
    proposed = {c.clip_id: c for c in response.captions if c.clip_id in known}
    merged = []
    for base in fallback.clips:
        item = proposed.get(base.clip_id)
        if item is None or not item.title.strip():
            merged.append(base.model_copy())
            continue
        merged.append(
            ClipCaption(
                clip_id=base.clip_id,
                title=item.title.strip()[:MAX_TITLE_CHARS],
                description=item.description.strip() or base.description,
                hashtags=merge_hashtags(item.hashtags, charte) if item.hashtags else base.hashtags,
            )
        )
    return CaptionSet(video_id=fallback.video_id, clips=merged)


def _fit_caption(
    title: str, description: str, hashtags: list[str], budget: int
) -> tuple[str, str, list[str]]:
    """Fait tenir une légende dans `budget` caractères (format `build_caption`).

    La description saute en premier (le prompt la traite déjà comme facultative),
    puis les hashtags de fin un par un, puis le titre en tout dernier recours —
    jamais de coupe à mi-mot ailleurs que sur le titre."""

    def fits(t: str, d: str, h: list[str]) -> bool:
        return len(build_caption(t, d, h)) <= budget

    if fits(title, description, hashtags):
        return title, description, hashtags
    if fits(title, "", hashtags):
        return title, "", hashtags
    tags = list(hashtags)
    while tags and not fits(title, "", tags):
        tags.pop()
    if fits(title, "", tags):
        return title, "", tags
    return title[:budget], "", []


def enforce_caption_budget(
    captions: CaptionSet, budget: int = DEFAULT_CAPTION_MAX_CHARS
) -> CaptionSet:
    """Applique `_fit_caption` à chaque clip — filet de sécurité déterministe
    derrière la consigne du prompt, jamais une confiance aveugle dans le LLM."""
    fitted = []
    for c in captions.clips:
        title, description, hashtags = _fit_caption(c.title, c.description, c.hashtags, budget)
        fitted.append(
            ClipCaption(clip_id=c.clip_id, title=title, description=description, hashtags=hashtags)
        )
    return CaptionSet(video_id=captions.video_id, clips=fitted)
