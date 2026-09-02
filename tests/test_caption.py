"""Légendes : fusion LLM/repli, cartes de prompt et budget de caractères."""

from clippey.caption import (
    MAX_TITLE_CHARS,
    CaptionResponse,
    _cards,
    _fallback,
    _fit_caption,
    enforce_caption_budget,
    merge_response,
)
from clippey.models import (
    CaptionSet,
    Charte,
    Clip,
    ClipCaption,
    ClipScore,
    Segment,
    Transcript,
    Word,
)
from clippey.package import build_caption

CHARTE = Charte(hashtags={"base": ["fyp"], "banned_words": []})


def make_clip(index: int = 1, title: str = "Titre du juge"):
    return Clip(
        id=f"vid-c{index:02d}",
        video_id="vid",
        segments=[Segment(t0=0.0, t1=2.0)],
        hook_t=0.0,
        hook_overlay="ACCROCHE",
        title=title,
        description="Description du juge.",
        hashtags=["debat"],
        scores=ClipScore(hook=8, emotion=7, value=7, quotability=7, standalone=8),
        weighted_score=7.5,
    )


def make_transcript():
    words = [
        Word(start=0.0, end=0.5, text="phrase"),
        Word(start=0.5, end=1.0, text="du"),
        Word(start=1.0, end=1.5, text="clip"),
    ]
    return Transcript(language="fr", words=words, sentences=[])


def fallback(clips):
    return _fallback("vid", clips, CHARTE)


def test_llm_overrides_title_and_hashtags():
    clips = [make_clip()]
    response = CaptionResponse(
        captions=[
            ClipCaption(
                clip_id="vid-c01",
                title="Le titre viral",
                description="Et vous, vous feriez quoi ?",
                hashtags=["psychologie", "debat"],
            )
        ]
    )
    merged = merge_response(clips, response, CHARTE, fallback(clips)).clips[0]
    assert merged.title == "Le titre viral"
    assert merged.description == "Et vous, vous feriez quoi ?"
    assert merged.hashtags == ["fyp", "psychologie", "debat"]


def test_long_title_truncated():
    clips = [make_clip()]
    response = CaptionResponse(captions=[ClipCaption(clip_id="vid-c01", title="a" * 120)])
    merged = merge_response(clips, response, CHARTE, fallback(clips)).clips[0]
    assert len(merged.title) == MAX_TITLE_CHARS


def test_unknown_clip_id_ignored():
    clips = [make_clip()]
    response = CaptionResponse(captions=[ClipCaption(clip_id="autre-c09", title="Hors sujet")])
    merged = merge_response(clips, response, CHARTE, fallback(clips))
    assert [c.clip_id for c in merged.clips] == ["vid-c01"]
    assert merged.clips[0].title == "Titre du juge"


def test_blank_title_keeps_fallback():
    clips = [make_clip()]
    response = CaptionResponse(captions=[ClipCaption(clip_id="vid-c01", title="   ")])
    merged = merge_response(clips, response, CHARTE, fallback(clips)).clips[0]
    assert merged.title == "Titre du juge"
    assert merged.description == "Description du juge."
    assert merged.hashtags == ["fyp", "debat"]


def test_cards_carry_id_and_clip_text():
    card = _cards([make_clip()], make_transcript())[0]
    assert "clip_id: vid-c01" in card
    assert "phrase du clip" in card


def test_build_caption_is_the_text_to_copy():
    assert build_caption("T", "D", ["a", "b"]) == "T\n\nD\n\n#a #b"


def test_fit_caption_keeps_short_caption_untouched():
    title, description, hashtags = _fit_caption("Titre court", "Une question ?", ["fyp"], 150)
    assert (title, description, hashtags) == ("Titre court", "Une question ?", ["fyp"])


def test_fit_caption_drops_description_first():
    title = "Titre" * 10  # 50 car.
    long_description = "Description bien trop longue pour tenir dans le budget restant."
    hashtags = ["fyp", "debat", "societe"]
    title, description, hashtags = _fit_caption(title, long_description, hashtags, 80)
    assert description == ""
    assert hashtags == ["fyp", "debat", "societe"]  # les hashtags survivent, courts


def test_fit_caption_trims_hashtags_from_the_end_when_still_too_long():
    title = "T" * 60
    hashtags = ["aaaaaaaaaa", "bbbbbbbbbb", "cccccccccc"]
    title, description, hashtags = _fit_caption(title, "peu importe", hashtags, 80)
    assert description == ""
    assert hashtags == ["aaaaaaaaaa"]  # on retire depuis la fin jusqu'à tenir


def test_fit_caption_truncates_title_as_last_resort():
    title, description, hashtags = _fit_caption("T" * 200, "peu importe", ["fyp"], 50)
    assert description == ""
    assert hashtags == []
    assert len(title) == 50


def test_enforce_caption_budget_applies_to_every_clip():
    captions = CaptionSet(
        video_id="vid",
        clips=[
            ClipCaption(clip_id="vid-c01", title="Court", description="", hashtags=["fyp"]),
            ClipCaption(
                clip_id="vid-c02",
                title="T" * 60,
                description="Une description bien trop longue pour le budget imparti ici",
                hashtags=["fyp", "debat", "societe", "psychologie"],
            ),
        ],
    )
    fitted = enforce_caption_budget(captions, budget=150)
    for c in fitted.clips:
        assert len(build_caption(c.title, c.description, c.hashtags)) <= 150
    assert fitted.clips[0].title == "Court"  # déjà conforme, inchangé
