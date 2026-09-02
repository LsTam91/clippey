"""Configuration application (clippey.toml + variables d'env CLIPPEY_*)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseModel):
    base_url: str = "https://api.deepseek.com/v1"
    api_key: str = ""
    model: str = "deepseek-chat"
    # €/1M tokens — à re-piner à chaque changement de modèle, sinon le compteur ment
    price_in_eur_per_mtok: float = 0.13
    price_out_eur_per_mtok: float = 0.26
    max_cost_per_video_eur: float = 0.50
    timeout_s: float = 120.0


class ASRConfig(BaseModel):
    model_repo: str = "mlx-community/whisper-large-v3-turbo"
    no_speech_threshold: float = 0.6
    logprob_threshold: float = -1.0
    sentence_pause_s: float = 0.8


class RankingWeights(BaseModel):
    hook: float = 0.35
    emotion: float = 0.20
    value: float = 0.15
    quotability: float = 0.15
    standalone: float = 0.15
    score_floor: float = 6.0


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CLIPPEY_", env_nested_delimiter="__", extra="ignore"
    )

    data_dir: Path = Path("data")
    ffmpeg_path: str = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
    ffprobe_path: str = "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"
    fonts_dir: Path = Path("fonts")
    language: str = "fr"
    cookies_from_browser: str = ""  # ex. "firefox" si bot-check YouTube

    llm: LLMConfig = Field(default_factory=LLMConfig)
    asr: ASRConfig = Field(default_factory=ASRConfig)
    ranking: RankingWeights = Field(default_factory=RankingWeights)


def load_config() -> AppConfig:
    import tomllib

    for name in ("clippey.local.toml", "clippey.toml"):
        p = Path(name)
        if p.exists():
            with p.open("rb") as f:
                return AppConfig(**tomllib.load(f))
    return AppConfig()
