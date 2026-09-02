"""ASR mots + phrases via mlx-whisper (Apple Silicon). transcript.json en sortie."""

from __future__ import annotations

from ..models import Sentence, Transcript, Word
from ..pipeline import Context, write_json_atomic

_PUNCT_ONLY = set(".,!?;:…»«\"'-")
_SENTENCE_END = (".", "!", "?", "…")


def step_asr(ctx: Context) -> None:
    import mlx_whisper  # import local : dépendance macOS/arm64 uniquement

    result = mlx_whisper.transcribe(
        str(ctx.paths["audio"]),
        path_or_hf_repo=ctx.config.asr.model_repo,
        word_timestamps=True,
        language=ctx.charte.language,
    )

    words = _collect_words(result, ctx)
    sentences = split_sentences(words, pause_s=ctx.config.asr.sentence_pause_s)
    transcript = Transcript(
        language=result.get("language", ctx.charte.language),
        words=words,
        sentences=sentences,
    )
    write_json_atomic(ctx.paths["transcript"], transcript.model_dump_json(indent=1))
    print(f"       {len(words)} mots, {len(sentences)} phrases")


def _collect_words(result: dict, ctx: Context) -> list[Word]:
    cfg = ctx.config.asr
    words: list[Word] = []
    for seg in result["segments"]:
        # heuristique anti-hallucination whisper (silence/musique)
        if (
            seg.get("no_speech_prob", 0) > cfg.no_speech_threshold
            and seg.get("avg_logprob", 0) < cfg.logprob_threshold
        ):
            continue
        for w in seg.get("words", []):
            text = w["word"].strip()
            if not text:
                continue
            if set(text) <= _PUNCT_ONLY and words:
                # la ponctuation arrive en tokens séparés → fusion avec le mot précédent
                words[-1].text += text
                words[-1].end = max(words[-1].end, float(w["end"]))
                continue
            if text[0] in ("'", "’") and words:
                # élisions françaises découpées par whisper (« C » + « 'est »)
                words[-1].text += text
                words[-1].end = max(words[-1].end, float(w["end"]))
                continue
            words.append(
                Word(
                    start=float(w["start"]),
                    end=float(w["end"]),
                    text=text,
                    confidence=float(w.get("probability", 1.0)),
                )
            )
    return words


def split_sentences(words: list[Word], pause_s: float = 0.8) -> list[Sentence]:
    sentences: list[Sentence] = []
    start_idx = 0
    for i, w in enumerate(words):
        is_last = i == len(words) - 1
        ends_sentence = w.text.endswith(_SENTENCE_END)
        long_pause = not is_last and (words[i + 1].start - w.end) > pause_s
        if is_last or ends_sentence or long_pause:
            chunk = words[start_idx : i + 1]
            sentences.append(
                Sentence(
                    id=f"S{len(sentences) + 1:04d}",
                    start=chunk[0].start,
                    end=chunk[-1].end,
                    text=" ".join(x.text for x in chunk),
                    word_start=start_idx,
                    word_end=i + 1,
                )
            )
            start_idx = i + 1
    return sentences
