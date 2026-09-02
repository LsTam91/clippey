"""Découpage en phrases depuis les mots (ponctuation + pauses)."""

from clippey.analyze.asr import split_sentences
from clippey.models import Word


def test_split_on_punctuation_and_pause():
    words = [
        Word(start=0.0, end=0.3, text="Salut"),
        Word(start=0.3, end=0.6, text="tout"),
        Word(start=0.6, end=1.0, text="le"),
        Word(start=1.0, end=1.4, text="monde."),
        Word(start=1.5, end=1.9, text="Ça"),
        Word(start=1.9, end=2.2, text="va"),  # pas de ponctuation, mais pause après
        Word(start=3.5, end=3.9, text="On"),
        Word(start=3.9, end=4.4, text="commence"),
    ]
    sentences = split_sentences(words, pause_s=0.8)
    assert len(sentences) == 3
    assert sentences[0].text == "Salut tout le monde."
    assert sentences[0].id == "S0001"
    assert sentences[1].text == "Ça va"
    assert sentences[2].word_start == 6 and sentences[2].word_end == 8


def test_ids_map_back_to_words():
    words = [Word(start=i * 0.5, end=i * 0.5 + 0.4, text=f"w{i}.") for i in range(5)]
    sentences = split_sentences(words)
    assert len(sentences) == 5
    for i, s in enumerate(sentences):
        assert words[s.word_start].start == s.start
        assert words[s.word_end - 1].end == s.end
        assert s.id == f"S{i + 1:04d}"
