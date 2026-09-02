"""Contrats Pydantic partagés par toutes les étapes du pipeline.

Timebase canonique : secondes (float) depuis le début du fichier normalisé
(`norm.mp4`). Tous les artefacts, sans exception, utilisent cette référence.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class HeatmapPoint(BaseModel):
    start: float
    end: float
    value: float


class VideoMeta(BaseModel):
    video_id: str
    url: str
    title: str
    channel: str = ""
    duration_s: float
    fps: float = 0.0
    width: int = 0
    height: int = 0
    language: str = "fr"
    upload_date: str = ""
    heatmap: list[HeatmapPoint] = Field(default_factory=list)


# --- Transcript ------------------------------------------------------------


class Word(BaseModel):
    start: float
    end: float
    text: str
    confidence: float = 1.0


class Sentence(BaseModel):
    id: str  # "S0001"
    start: float
    end: float
    text: str
    word_start: int  # index dans Transcript.words
    word_end: int  # exclusif


class Transcript(BaseModel):
    language: str
    words: list[Word]
    sentences: list[Sentence]

    def sentence_by_id(self, sid: str) -> Sentence | None:
        idx = int(sid.removeprefix("S")) - 1
        if 0 <= idx < len(self.sentences):
            return self.sentences[idx]
        return None

    def words_between(self, t0: float, t1: float) -> list[Word]:
        return [w for w in self.words if w.start >= t0 and w.end <= t1]


# --- Signaux audio et visuels ------------------------------------------------


class AudioEventKind(StrEnum):
    LAUGHTER = "laughter"
    APPLAUSE = "applause"
    SHOUT = "shout"
    MUSIC = "music"


class AudioEvent(BaseModel):
    kind: AudioEventKind
    start: float
    end: float
    score: float


class Scene(BaseModel):
    index: int
    start: float
    end: float


class FaceSample(BaseModel):
    t: float
    boxes: list[tuple[float, float, float, float]]  # x, y, w, h normalisés [0,1]


# --- Sélection ---------------------------------------------------------------


class CandidateFeatures(BaseModel):
    duration_s: float = 0.0
    word_count: int = 0
    speech_density: float = 0.0  # mots/s
    peak_energy_z: float = 0.0
    laughter_sum: float = 0.0
    motion_z: float = 0.0
    scene_cuts: int = 0


class Candidate(BaseModel):
    id: str
    t0: float
    t1: float
    proposers: list[str] = Field(default_factory=list)  # P1|P2|P3|LLM_MAP
    features: CandidateFeatures = Field(default_factory=CandidateFeatures)
    excerpt: str = ""
    vlm_description: str | None = None


class ClipScore(BaseModel):
    hook: float = Field(ge=0, le=10)
    emotion: float = Field(ge=0, le=10)
    value: float = Field(ge=0, le=10)
    quotability: float = Field(ge=0, le=10)
    standalone: float = Field(ge=0, le=10)
    visual_payoff: float | None = None

    def weighted(self, w: dict[str, float]) -> float:
        return (
            w["hook"] * self.hook
            + w["emotion"] * self.emotion
            + w["value"] * self.value
            + w["quotability"] * self.quotability
            + w["standalone"] * self.standalone
        )


class ClipPart(BaseModel):
    """Un passage contigu, désigné par des IDs de phrases."""

    start_sentence_id: str
    end_sentence_id: str


class ClipDraft(BaseModel):
    """Sortie structurée du LLM judge — uniquement des IDs de phrases, jamais des temps.

    `parts` : 1 à 3 passages chronologiques non contigus assemblés en un seul clip
    (ex. une question + les meilleures réponses de plusieurs passants).
    """

    parts: list[ClipPart] = Field(min_length=1, max_length=3)
    hook_sentence_id: str
    hook_overlay: str = Field(max_length=80)
    title: str
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)
    scores: ClipScore
    reason: str = ""


class Segment(BaseModel):
    """Fenêtre temporelle source (timebase norm.mp4)."""

    t0: float
    t1: float

    @property
    def duration(self) -> float:
        return self.t1 - self.t0


class Clip(BaseModel):
    id: str  # "<video_id>-c01"
    video_id: str
    segments: list[Segment]  # chronologiques, non chevauchants
    hook_t: float  # début du premier mot du hook (timebase vidéo)
    hook_overlay: str
    title: str
    description: str
    hashtags: list[str]
    scores: ClipScore
    weighted_score: float
    reason: str = ""
    file_path: str = ""
    freeze_tail_s: float = 0.0  # gel de la dernière image, hors timebase source

    @property
    def t0(self) -> float:
        return self.segments[0].t0

    @property
    def t1(self) -> float:
        return self.segments[-1].t1

    @property
    def duration(self) -> float:
        return sum(s.duration for s in self.segments)

    @property
    def total_duration(self) -> float:
        """Durée du fichier rendu = concaténation des segments + gel de fin."""
        return self.duration + self.freeze_tail_s


class Selection(BaseModel):
    video_id: str
    clips: list[Clip]
    rejected_count: int = 0


# --- Légendes ----------------------------------------------------------------


class ClipCaption(BaseModel):
    clip_id: str
    title: str = ""
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)


class CaptionSet(BaseModel):
    video_id: str
    clips: list[ClipCaption] = Field(default_factory=list)


# --- Charte ------------------------------------------------------------------


class CaptionStyle(BaseModel):
    style: str = "karaoke"
    font: str = "Anton"
    font_size: int = 110
    primary_color: str = "&H00FFFFFF"
    highlight_color: str = "&H0000D7FF"
    outline_color: str = "&H00000000"
    outline: int = 7
    shadow: int = 3
    margin_v: int = 640
    max_words_per_line: int = 4
    uppercase: bool = True
    min_word_confidence: float = 0.4  # confiance moyenne minimale d'une ligne


class HookStyle(BaseModel):
    enabled: bool = True
    duration_s: float = 2.5
    font_size: int = 84
    margin_v: int = 320  # distance depuis le haut (alignment 8)


class ClipPrefs(BaseModel):
    duration_min_s: float = 10
    duration_target_s: float = 40
    duration_max_s: float = 75
    max_clips: int = 5
    # cible TOTALE de silence après le dernier mot : images réelles si la source
    # le permet, image gelée pour le reste
    tail_s: float = 1.0
    # longueur maximale de la légende assemblée (titre + description + hashtags) :
    # au-delà, les plateformes courtes la tronquent dans le fil
    caption_max_chars: int = 150


class ReframePrefs(BaseModel):
    mode: str = "face"  # face | center


class HashtagPrefs(BaseModel):
    base: list[str] = Field(default_factory=lambda: ["fyp"])
    banned_words: list[str] = Field(default_factory=list)


class Charte(BaseModel):
    creator: str = "default"
    language: str = "fr"
    tone: str = ""
    captions: CaptionStyle = Field(default_factory=CaptionStyle)
    hook: HookStyle = Field(default_factory=HookStyle)
    clips: ClipPrefs = Field(default_factory=ClipPrefs)
    reframe: ReframePrefs = Field(default_factory=ReframePrefs)
    hashtags: HashtagPrefs = Field(default_factory=HashtagPrefs)


# --- Manifest ----------------------------------------------------------------


class ClipManifestEntry(BaseModel):
    clip_id: str
    file: str
    title: str
    description: str
    hashtags: list[str]
    duration_s: float
    weighted_score: float
    source_t0: float
    source_t1: float


class Manifest(BaseModel):
    video_id: str
    source_url: str
    source_title: str
    charte: str
    generated_at: str
    total_cost_eur: float = 0.0
    clips: list[ClipManifestEntry]


def artifact_paths(data_dir: Path, video_id: str) -> dict[str, Path]:
    root = data_dir / video_id
    return {
        "root": root,
        "source": root / "source.mp4",
        "norm": root / "norm.mp4",
        "audio": root / "audio.wav",
        "proxy": root / "proxy480.mp4",
        "meta": root / "meta.json",
        "transcript": root / "transcript.json",
        "audio_events": root / "audio_events.json",
        "energy": root / "energy.json",
        "scenes": root / "scenes.json",
        "faces": root / "faces.json",
        "candidates": root / "candidates.json",
        "selection": root / "selection.json",
        "captions": root / "captions.json",
        "llm_cache": root / "llm_cache",
        "clips_dir": root / "clips",
        "manifest": root / "manifest.json",
        "review": root / "review.html",
    }
