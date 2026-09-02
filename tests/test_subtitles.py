"""Génération ASS : timings karaoké, rebasage, échappement, regroupement."""

from clippey.compose.subtitles import _ts, generate_ass, group_lines
from clippey.models import Charte, Word


def words_fixture():
    return [
        Word(start=10.0, end=10.4, text="Bonjour"),
        Word(start=10.4, end=10.7, text="à"),
        Word(start=10.7, end=11.2, text="tous."),
        Word(start=12.5, end=13.0, text="Aujourd'hui"),  # pause > 0.8 s avant
        Word(start=13.0, end=13.6, text="on{teste}"),
    ]


def test_group_lines_breaks_on_punctuation_and_pause():
    lines = group_lines(words_fixture(), max_words=4)
    assert [len(line) for line in lines] == [3, 2]


def test_ass_times_rebased_to_clip_start():
    ass = generate_ass(words_fixture(), t0=10.0, hook_text="", charte=Charte())
    assert "Dialogue: 0,0:00:00.00," in ass  # premier mot à t=0 du clip


def test_karaoke_k_tags_cover_gaps():
    ass = generate_ass(words_fixture(), t0=10.0, hook_text="", charte=Charte())
    karaoke_line = next(line for line in ass.splitlines() if "BONJOUR" in line)
    # \k du 1er mot = 40 cs (jusqu'au mot suivant), 2e = 30, dernier = durée du mot 50
    assert "{\\k40}BONJOUR" in karaoke_line
    assert "{\\k30}À" in karaoke_line
    assert "{\\k50}TOUS." in karaoke_line


def test_hook_overlay_present_and_braces_escaped():
    ass = generate_ass(words_fixture(), t0=10.0, hook_text="Trop {fort}", charte=Charte())
    assert "Hook" in ass
    assert "TROP (FORT)" in ass
    assert "ON(TESTE)" in ass  # accolades du texte échappées (sinon parse ASS cassé)


def test_timestamp_format():
    assert _ts(0) == "0:00:00.00"
    assert _ts(75.5) == "0:01:15.50"
    assert _ts(3661.25) == "1:01:01.25"
