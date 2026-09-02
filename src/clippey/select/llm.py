"""Unique point d'accès réseau LLM : client OpenAI-compatible avec cache disque,
retry-réparation JSON et compteur de coûts (le budget est une assertion, pas un espoir)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
from pydantic import BaseModel, ValidationError

from ..config import LLMConfig
from ..db import Db


class BudgetExceededError(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, cfg: LLMConfig, db: Db, video_id: str, step: str, cache_dir: Path) -> None:
        if not cfg.api_key:
            raise LLMError(
                "Pas de clé API LLM. Renseigner CLIPPEY_LLM__API_KEY (et au besoin "
                "CLIPPEY_LLM__BASE_URL / CLIPPEY_LLM__MODEL)."
            )
        self.cfg = cfg
        self.db = db
        self.video_id = video_id
        self.step = step
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)

    def chat_json[T: BaseModel](
        self,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.3,
    ) -> T:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        last_error = ""
        for _ in range(3):
            raw = self._complete(messages, temperature)
            try:
                return schema.model_validate(json.loads(_strip_fences(raw)))
            except (json.JSONDecodeError, ValidationError) as e:
                last_error = str(e)
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Ta réponse n'est pas un JSON valide conforme au schéma demandé. "
                            f"Erreur : {last_error[:500]}\n"
                            "Réponds UNIQUEMENT avec le JSON corrigé, sans texte autour."
                        ),
                    }
                )
        raise LLMError(f"JSON invalide après 3 tentatives : {last_error[:300]}")

    def _complete(self, messages: list[dict], temperature: float) -> str:
        key = hashlib.sha256(
            json.dumps({"m": self.cfg.model, "msgs": messages}, sort_keys=True).encode()
        ).hexdigest()
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            cached = json.loads(cache_file.read_text())
            self.db.record_llm_call(
                self.video_id,
                self.step,
                self.cfg.model,
                key[:16],
                cached["tokens_in"],
                cached["tokens_out"],
                0.0,
                cached=True,
            )
            return cached["content"]

        spent = self.db.video_cost_eur(self.video_id)
        if spent >= self.cfg.max_cost_per_video_eur:
            raise BudgetExceededError(
                f"Budget dépassé pour {self.video_id} : {spent:.3f} € "
                f"≥ {self.cfg.max_cost_per_video_eur} €"
            )

        resp = httpx.post(
            f"{self.cfg.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.cfg.api_key}"},
            json={
                "model": self.cfg.model,
                "messages": messages,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            },
            timeout=self.cfg.timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        tokens_in = int(usage.get("prompt_tokens", 0))
        tokens_out = int(usage.get("completion_tokens", 0))
        cost = (
            tokens_in * self.cfg.price_in_eur_per_mtok
            + tokens_out * self.cfg.price_out_eur_per_mtok
        ) / 1_000_000
        self.db.record_llm_call(
            self.video_id,
            self.step,
            self.cfg.model,
            key[:16],
            tokens_in,
            tokens_out,
            cost,
            cached=False,
        )
        cache_file.write_text(
            json.dumps({"content": content, "tokens_in": tokens_in, "tokens_out": tokens_out})
        )
        return content


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return text.strip()
