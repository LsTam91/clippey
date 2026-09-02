"""Sélection : un appel judge sur le transcript complet, clips mono ou multi-parts
(1-3 passages assemblés), raffinement de bornes déterministe (contrainte hook ≤ 3,5 s
sur la première part, souffle d'environ 1 s après le dernier mot), ranking +
non-chevauchement."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..models import Charte, Clip, ClipDraft, Segment, Selection, Sentence, Transcript, VideoMeta
from ..pipeline import Context, write_json_atomic
from .llm import LLMClient
from .prompts import critic_system, judge_system, judge_user

HOOK_MAX_DELAY_S = 3.5
START_PAD_S = 0.35
END_PAD_S = 0.6
MIN_GAP_BETWEEN_PARTS_S = 0.2
SOURCE_END_GUARD_S = 0.1


class JudgeResponse(BaseModel):
    clips: list[ClipDraft] = Field(default_factory=list)


def step_select(ctx: Context) -> None:
    transcript = Transcript.model_validate_json(ctx.paths["transcript"].read_text())
    meta = VideoMeta.model_validate_json(ctx.paths["meta"].read_text())
    client = LLMClient(ctx.config.llm, ctx.db, ctx.video_id, "select", ctx.paths["llm_cache"])
    signals = _audio_signals(ctx, transcript)
    response = client.chat_json(
        judge_system(ctx.charte), judge_user(transcript, signals), JudgeResponse
    )

    weights = ctx.config.ranking.model_dump()
    drafts: list[tuple[float, ClipDraft]] = []
    for draft in response.clips:
        if _valid_ids(draft, transcript):
            drafts.append((draft.scores.weighted(weights), draft))
    drafts.sort(key=lambda x: x[0], reverse=True)

    clips: list[Clip] = []
    rejected = 0
    for weighted, draft in drafts:
        clip = refine_boundaries(draft, transcript, ctx, weighted, len(clips) + 1, meta.duration_s)
        if clip is None or weighted < ctx.config.ranking.score_floor:
            rejected += 1
            continue
        if any(_overlaps(clip, c) for c in clips):
            rejected += 1
            continue
        clips.append(clip)
        if len(clips) >= ctx.charte.clips.max_clips:
            break

    fixed = _critic_pass(client, clips, transcript)
    selection = Selection(video_id=ctx.video_id, clips=clips, rejected_count=rejected)
    write_json_atomic(ctx.paths["selection"], selection.model_dump_json(indent=1))
    multi = sum(1 for c in clips if len(c.segments) > 1)
    print(
        f"       {len(clips)} clips retenus ({multi} multi-cut), {rejected} rejetés, "
        f"{fixed} overlays/titres dé-spoilés"
    )


def _audio_signals(ctx: Context, transcript: Transcript) -> str:
    """Pics d'énergie mappés sur les IDs de phrases voisines, pour le prompt du juge."""
    import json as _json

    from ..analyze.audio_events import energy_peaks

    if not ctx.paths["energy"].exists():
        return ""
    peaks = energy_peaks(_json.loads(ctx.paths["energy"].read_text()))
    lines = []
    for t, z in peaks:
        sentence = min(transcript.sentences, key=lambda s: abs(s.start - t), default=None)
        near = f" (près de [{sentence.id}])" if sentence else ""
        lines.append(f"- pic à {int(t // 60)}:{int(t % 60):02d}{near}, intensité z={z:.1f}")
    return "\n".join(lines)


class CriticFix(BaseModel):
    clip_id: str
    hook_overlay: str
    title: str


class CriticResponse(BaseModel):
    fixes: list[CriticFix] = Field(default_factory=list)


def _critic_pass(client: LLMClient, clips: list[Clip], transcript: Transcript) -> int:
    """Relecture anti-spoil : réécrit overlay/titre s'ils révèlent la chute."""
    if not clips:
        return 0
    cards = []
    for c in clips:
        ending = " ".join(
            w.text for w in transcript.words_between(c.segments[-1].t0, c.segments[-1].t1)
        )[-300:]
        cards.append(
            f'clip_id: {c.id}\noverlay: "{c.hook_overlay}"\ntitre: "{c.title}"\n'
            f"chute du clip : « …{ending} »"
        )
    response = client.chat_json(critic_system(), "\n\n".join(cards), CriticResponse)
    by_id = {c.id: c for c in clips}
    fixed = 0
    for fix in response.fixes:
        clip = by_id.get(fix.clip_id)
        if clip and (clip.hook_overlay != fix.hook_overlay or clip.title != fix.title):
            clip.hook_overlay = fix.hook_overlay[:80]
            clip.title = fix.title
            fixed += 1
    return fixed


def _valid_ids(draft: ClipDraft, transcript: Transcript) -> bool:
    hook = transcript.sentence_by_id(draft.hook_sentence_id)
    if hook is None:
        return False
    prev_end = -1.0
    for part in draft.parts:
        start = transcript.sentence_by_id(part.start_sentence_id)
        end = transcript.sentence_by_id(part.end_sentence_id)
        if start is None or end is None or start.start > end.start:
            return False  # ID halluciné ou part inversée → drop
        if start.start <= prev_end:
            return False  # parts non chronologiques ou chevauchantes
        prev_end = end.end
    first = transcript.sentence_by_id(draft.parts[0].start_sentence_id)
    first_end = transcript.sentence_by_id(draft.parts[0].end_sentence_id)
    return first.start <= hook.start and hook.end <= first_end.end


def refine_boundaries(
    draft: ClipDraft,
    transcript: Transcript,
    ctx: Context,
    weighted: float,
    index: int,
    video_duration_s: float,
) -> Clip | None:
    prefs = ctx.charte.clips
    hook = transcript.sentence_by_id(draft.hook_sentence_id)

    # bornes de chaque part : [phrase de début, phrase de fin] → temps paddés
    parts: list[list[Sentence]] = [
        [
            transcript.sentence_by_id(p.start_sentence_id),
            transcript.sentence_by_id(p.end_sentence_id),
        ]
        for p in draft.parts
    ]

    # Contrainte hook sur la première part : ≤ 3,5 s après t=0, sinon le setup saute.
    t0_first = max(0.0, parts[0][0].start - START_PAD_S)
    if hook.start - t0_first > HOOK_MAX_DELAY_S:
        parts[0][0] = hook

    # Trop long → retirer des phrases entières à la fin de la dernière part,
    # puis retirer la dernière part si elle se vide (jamais couper un mot).
    while _total_duration(parts, transcript) > prefs.duration_max_s:
        last = parts[-1]
        prev = _previous_sentence(last[1], transcript)
        if (
            prev is not None
            and prev.start >= last[0].start
            and (len(parts) > 1 or prev.start >= hook.start)
        ):
            last[1] = prev
        elif len(parts) > 1:
            parts.pop()
        else:
            break

    segments = [_segment(start, end, transcript) for start, end in parts]
    duration = sum(s.duration for s in segments)
    if duration < prefs.duration_min_s or duration > prefs.duration_max_s:
        return None

    # Souffle uniquement sur la dernière part : une pause au milieu casserait le rythme.
    tail = min(prefs.tail_s, max(0.0, prefs.duration_max_s - duration))
    last_sentence = parts[-1][1]
    segments[-1].t1, freeze = tail_plan(
        last_sentence.end,
        segments[-1].t1,
        _tail_limit(last_sentence, transcript, video_duration_s),
        tail,
    )

    return Clip(
        id=f"{ctx.video_id}-c{index:02d}",
        video_id=ctx.video_id,
        segments=segments,
        hook_t=round(hook.start, 3),
        hook_overlay=draft.hook_overlay,
        title=draft.title,
        description=draft.description,
        hashtags=merge_hashtags(draft.hashtags, ctx.charte),
        scores=draft.scores,
        weighted_score=round(weighted, 2),
        reason=draft.reason,
        freeze_tail_s=freeze,
    )


def _tail_limit(end: Sentence, transcript: Transcript, video_duration_s: float) -> float:
    """Borne dure au-delà de laquelle on ne peut pas prolonger : reprise de la parole
    ou fin de la vidéo source."""
    hard = video_duration_s - SOURCE_END_GUARD_S if video_duration_s > 0 else float("inf")
    if end.word_end < len(transcript.words):
        return min(hard, transcript.words[end.word_end].start - 0.05)
    return hard


def tail_plan(last_word_end: float, t1: float, limit: float, tail_s: float) -> tuple[float, float]:
    """Souffle de fin : (t1 prolongé, durée de gel de la dernière image).

    `tail_s` est la cible TOTALE de silence après le dernier mot : on la prend en
    images réelles tant que la source le permet, le reste est gelé.
    """
    t1_final = min(max(t1, last_word_end + tail_s), limit)
    freeze = min(tail_s, max(0.0, tail_s - (t1_final - last_word_end)))
    return round(t1_final, 3), round(freeze, 3)


def _segment(start: Sentence, end: Sentence, transcript: Transcript) -> Segment:
    return Segment(
        t0=round(max(0.0, start.start - START_PAD_S), 3),
        t1=round(_end_time(end, transcript), 3),
    )


def _total_duration(parts: list[list[Sentence]], transcript: Transcript) -> float:
    return sum(
        _end_time(end, transcript) - max(0.0, start.start - START_PAD_S) for start, end in parts
    )


def _end_time(end: Sentence, transcript: Transcript) -> float:
    t1 = end.end + END_PAD_S
    if end.word_end < len(transcript.words):
        t1 = min(t1, transcript.words[end.word_end].start - 0.05)
    return t1


def _previous_sentence(s: Sentence, transcript: Transcript) -> Sentence | None:
    idx = int(s.id.removeprefix("S")) - 2
    return transcript.sentences[idx] if idx >= 0 else None


def _overlaps(a: Clip, b: Clip) -> bool:
    return any(sa.t0 < sb.t1 and sb.t0 < sa.t1 for sa in a.segments for sb in b.segments)


def merge_hashtags(tags: list[str], charte: Charte) -> list[str]:
    banned = {w.lower() for w in charte.hashtags.banned_words}
    merged = list(dict.fromkeys(charte.hashtags.base + [t.lstrip("#") for t in tags]))
    return [t for t in merged if t.lower() not in banned][:12]
