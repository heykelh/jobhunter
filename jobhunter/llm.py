"""Appel commun à l'IA Groq (gratuite), pour les CV et le contrôle de l'expérience.

En cas d'échec, la raison exacte est gardée (clé refusée, modèle retiré, quota) et
affichée dans les logs et dans l'onglet Sources du site. Si le modèle demandé n'existe
plus chez Groq, on essaie les suivants de la liste.
"""
from __future__ import annotations

import json
import logging
import os

import requests

log = logging.getLogger("jobwatch")
URL = "https://api.groq.com/openai/v1/chat/completions"
FALLBACK_MODELS = ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "qwen/qwen3-32b", "llama-3.1-8b-instant"]
STATUS = {"ok": 0, "errors": 0, "last_error": "", "model": ""}
_dead: set[str] = set()


class LLMError(Exception):
    pass


def _models() -> list[str]:
    first = os.getenv("GROQ_MODEL", "").strip()
    out = ([first] if first else []) + FALLBACK_MODELS
    return [m for i, m in enumerate(out) if m and m not in out[:i] and m not in _dead]


def chat_json(system: str, user: str, temperature: float = 0.3, timeout: int = 60) -> dict:
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        raise LLMError("pas de clé GROQ_API_KEY")
    last = ""
    for model in _models():
        try:
            r = requests.post(URL, headers={"Authorization": f"Bearer {key}"}, timeout=timeout,
                              json={"model": model, "temperature": temperature,
                                    "response_format": {"type": "json_object"},
                                    "messages": [{"role": "system", "content": system},
                                                 {"role": "user", "content": user}]})
        except requests.RequestException as e:
            last = f"réseau : {type(e).__name__}"
            break
        if r.status_code == 200:
            try:
                out = json.loads(r.json()["choices"][0]["message"]["content"])
            except Exception as e:
                last = f"réponse illisible ({type(e).__name__})"
                continue
            STATUS["ok"] += 1
            STATUS["model"] = model
            return out
        body = r.text[:200].replace("\n", " ")
        last = f"HTTP {r.status_code} ({model}) : {body}"
        if r.status_code in (400, 404) and ("model" in body.lower() or "decommission" in body.lower()):
            _dead.add(model)                      # modèle retiré ou inconnu : on essaie le suivant
            continue
        break                                     # 401 clé refusée, 429 quota… : inutile d'insister
    STATUS["errors"] += 1
    STATUS["last_error"] = last
    log.warning("  IA Groq en échec : %s", last)
    raise LLMError(last)
