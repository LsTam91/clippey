"""Raffinement de bornes : contrainte hook, souffle de fin, durées, hashtags."""

from clippey.charte import load_charte
from clippey.config import AppConfig
from clippey.models import Charte, ClipDraft, ClipPart, ClipScore, Sentence, Transcript, Word
from clippey.pipeline import Context
from clippey.select.brain import _valid_ids, merge_hashtags, refine_boundaries, tail_plan


def make_transcript(n_sentences: int = 20, words_per: int = 5, word_dur: float = 0.4):
    words, sentences = [], []
    t = 0.0
    for s in range(n_sentences):
        w0 = len(words)
        for i in range(words_per):
            text = f"mot{s}_{i}" + ("." if i == words_per - 1 else "")
            words.append(Word(start=t, end=t + word_dur, text=text))
            t += word_dur
        sentences.append(
            Sentence(
                id=f"S{s + 1:04d}",
                start=words[w0].start,
                end=words[-1].end,
                text=" ".join(w.text for w in words[w0:]),
                word_start=w0,
                word_end=len(words),
            )
        )
        t += 0.2  # petite pause inter-phrases
    return Transcript(language="fr", words=words, sentences=sentences)


def make_ctx(tmp_path):
    cfg = AppConfig(data_dir=tmp_path)

    class FakeDb:
        def __getattr__(self, name):
            return lambda *a, **k: None

    return Context(config=cfg, charte=load_charte(), db=FakeDb(), video_id="test123")


def draft(start="S0001", end="S0010", hook="S0001", parts=None, **scores):
    base = dict(hook=8, emotion=7, value=7, quotability=7, standalone=8)
    base.update(scores)
    return ClipDraft(
        parts=parts or [ClipPart(start_sentence_id=start, end_sentence_id=end)],
        hook_sentence_id=hook,
        hook_overlay="LE TEST ULTIME",
        title="Titre de test",
        scores=ClipScore(**base),
    )


def test_hook_constraint_forces_start(tmp_path):
    """Hook à la phrase 5 avec start à la phrase 1 → start forcé vers le hook."""
    t = make_transcript()
    ctx = make_ctx(tmp_path)
    clip = refine_boundaries(
        draft(start="S0001", end="S0012", hook="S0005"), t, ctx, 7.5, 1, 10_000.0
    )
    assert clip is not None
    hook_sentence = t.sentence_by_id("S0005")
    assert clip.hook_t - clip.t0 <= 3.5
    assert abs(clip.t0 - (hook_sentence.start - 0.35)) < 0.01


def test_end_capped_before_next_word(tmp_path):
    t = make_transcript()
    ctx = make_ctx(tmp_path)
    clip = refine_boundaries(draft(), t, ctx, 7.5, 1, 10_000.0)
    assert clip is not None
    end_sentence = t.sentence_by_id("S0010")
    next_word = t.words[end_sentence.word_end]
    assert clip.t1 <= next_word.start - 0.049
    assert clip.freeze_tail_s > 0.8  # la parole reprend : le souffle est gelé
    # le souffle ne doit jamais faire entrer le mot suivant dans le clip
    last = clip.segments[-1]
    assert next_word not in t.words_between(last.t0, last.t1)


def test_too_short_rejected(tmp_path):
    t = make_transcript()
    ctx = make_ctx(tmp_path)
    clip = refine_boundaries(
        draft(start="S0001", end="S0002", hook="S0001"), t, ctx, 7.5, 1, 10_000.0
    )
    assert clip is None  # ~4 s < duration_min_s (10 s)


def test_too_long_trimmed_by_sentences(tmp_path):
    t = make_transcript(n_sentences=50)
    ctx = make_ctx(tmp_path)
    clip = refine_boundaries(
        draft(start="S0001", end="S0050", hook="S0001"), t, ctx, 7.5, 1, 10_000.0
    )
    assert clip is not None
    assert clip.t1 - clip.t0 <= ctx.charte.clips.duration_max_s


def test_hallucinated_id_dropped(tmp_path):
    t = make_transcript()
    assert not _valid_ids(draft(end="S9999"), t)
    assert not _valid_ids(draft(hook="S0015", end="S0010"), t)  # hook hors 1re part


def test_multicut_segments_and_duration(tmp_path):
    """2 parts non contiguës → 2 segments ; durée totale = somme des parts."""
    t = make_transcript(n_sentences=40)
    ctx = make_ctx(tmp_path)
    parts = [
        ClipPart(start_sentence_id="S0001", end_sentence_id="S0005"),
        ClipPart(start_sentence_id="S0020", end_sentence_id="S0026"),
    ]
    clip = refine_boundaries(draft(parts=parts), t, ctx, 7.5, 1, 10_000.0)
    assert clip is not None
    assert len(clip.segments) == 2
    assert clip.segments[0].t1 < clip.segments[1].t0  # chronologique, non contigu
    assert abs(clip.duration - sum(s.duration for s in clip.segments)) < 0.01
    assert ctx.charte.clips.duration_min_s <= clip.duration <= ctx.charte.clips.duration_max_s


def test_multicut_unordered_parts_rejected(tmp_path):
    t = make_transcript(n_sentences=40)
    parts = [
        ClipPart(start_sentence_id="S0020", end_sentence_id="S0026"),
        ClipPart(start_sentence_id="S0001", end_sentence_id="S0005"),
    ]
    assert not _valid_ids(draft(parts=parts, hook="S0020"), t)


def test_multicut_too_long_drops_last_part(tmp_path):
    """Dépassement → on rogne la fin de la dernière part, puis on la retire."""
    t = make_transcript(n_sentences=80)
    ctx = make_ctx(tmp_path)
    parts = [
        ClipPart(start_sentence_id="S0001", end_sentence_id="S0025"),
        ClipPart(start_sentence_id="S0040", end_sentence_id="S0075"),
    ]
    clip = refine_boundaries(draft(parts=parts), t, ctx, 7.5, 1, 10_000.0)
    assert clip is not None
    assert clip.duration <= ctx.charte.clips.duration_max_s


def test_tail_plan_extends_into_silence():
    """Silence assez long dans la source → tout le souffle est en images réelles."""
    assert tail_plan(10.0, 10.6, 45.0, 1.0) == (11.0, 0.0)


def test_tail_plan_freezes_when_speech_resumes():
    """La parole reprend juste après → le souffle manquant est gelé."""
    assert tail_plan(10.0, 10.15, 10.15, 1.0) == (10.15, 0.85)


def test_tail_plan_clamps_past_source_end():
    """Fin de la vidéo source → prolongation tronquée, gel du reste."""
    assert tail_plan(10.0, 10.6, 10.4, 1.0) == (10.4, 0.6)


def test_tail_plan_disabled_is_noop():
    assert tail_plan(10.0, 10.6, 45.0, 0.0) == (10.6, 0.0)


def test_tail_only_on_last_segment(tmp_path):
    """Le souffle ne touche que la dernière part : une pause au milieu casserait le rythme."""
    t = make_transcript(n_sentences=40)
    ctx = make_ctx(tmp_path)
    parts = [
        ClipPart(start_sentence_id="S0001", end_sentence_id="S0005"),
        ClipPart(start_sentence_id="S0020", end_sentence_id="S0026"),
    ]
    ctx.charte.clips.tail_s = 0.0
    without = refine_boundaries(draft(parts=parts), t, ctx, 7.5, 1, 10_000.0)
    ctx.charte.clips.tail_s = 1.0
    with_tail = refine_boundaries(draft(parts=parts), t, ctx, 7.5, 1, 10_000.0)
    assert without is not None and with_tail is not None
    assert without.segments[0].t1 == with_tail.segments[0].t1
    assert without.freeze_tail_s == 0.0
    assert with_tail.total_duration > without.total_duration


def test_total_duration_never_exceeds_max(tmp_path):
    t = make_transcript(n_sentences=50)
    ctx = make_ctx(tmp_path)
    d = draft(start="S0001", end="S0050", hook="S0001")
    clip = refine_boundaries(d, t, ctx, 7.5, 1, 10_000.0)
    assert clip is not None
    assert clip.total_duration <= ctx.charte.clips.duration_max_s


def test_merge_hashtags_dedupes_and_bans():
    charte = Charte(hashtags={"base": ["fyp", "pourtoi"], "banned_words": ["Crypto"]})
    assert merge_hashtags(["#pourtoi", "crypto", "debat", "debat"], charte) == [
        "fyp",
        "pourtoi",
        "debat",
    ]
    assert len(merge_hashtags([f"tag{i}" for i in range(20)], charte)) == 12
