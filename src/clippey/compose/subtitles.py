"""Génération ASS maison : karaoké mot-à-mot (\\k) + calque overlay hook.
Temps ASS relatifs au début du clip (le rendu seek à t0 → sortie 0-based)."""

from __future__ import annotations

from ..models import Charte, Word

_ASS_HEADER = """[Script Info]
Title: clippey
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,{font},{font_size},{primary},{highlight},{outline_c},&H80000000,0,0,0,0,100,100,0,0,1,{outline},{shadow},2,60,60,{margin_v},1
Style: Hook,{font},{hook_size},&H00FFFFFF,&H00FFFFFF,{outline_c},&H80000000,0,0,0,0,100,100,0,0,1,{outline},{shadow},8,60,60,{hook_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def generate_ass(words: list[Word], t0: float, hook_text: str, charte: Charte) -> str:
    cap = charte.captions
    header = _ASS_HEADER.format(
        font=cap.font,
        font_size=cap.font_size,
        primary=cap.primary_color,
        highlight=cap.highlight_color,
        outline_c=cap.outline_color,
        outline=cap.outline,
        shadow=cap.shadow,
        margin_v=cap.margin_v,
        hook_size=charte.hook.font_size,
        hook_margin_v=charte.hook.margin_v,
    )
    events: list[str] = []

    if charte.hook.enabled and hook_text:
        events.append(
            f"Dialogue: 1,{_ts(0.0)},{_ts(charte.hook.duration_s)},Hook,,0,0,0,,"
            f"{_escape(hook_text.upper())}"
        )

    lines = group_lines(words, cap.max_words_per_line)
    # transcription douteuse (créole, marmonnement, musique) → pas de sous-titre
    lines = [
        ln for ln in lines if sum(w.confidence for w in ln) / len(ln) >= cap.min_word_confidence
    ]
    for line in lines:
        start = line[0].start - t0
        end = line[-1].end - t0 + 0.05
        parts = []
        for i, w in enumerate(line):
            # \k en centisecondes : du début du mot au début du mot suivant de la ligne
            until = line[i + 1].start if i + 1 < len(line) else line[-1].end
            k_cs = max(1, round((until - w.start) * 100))
            text = w.text.upper() if cap.uppercase else w.text
            parts.append(f"{{\\k{k_cs}}}{_escape(text)}")
        events.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Karaoke,,0,0,0,,{' '.join(parts)}")

    return header + "\n".join(events) + "\n"


def group_lines(words: list[Word], max_words: int, pause_s: float = 0.8) -> list[list[Word]]:
    lines: list[list[Word]] = []
    current: list[Word] = []
    for i, w in enumerate(words):
        current.append(w)
        pause = i + 1 < len(words) and (words[i + 1].start - w.end) > pause_s
        if len(current) >= max_words or w.text.endswith((".", "!", "?", "…")) or pause:
            lines.append(current)
            current = []
    if current:
        lines.append(current)
    return lines


def _ts(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", " ")
