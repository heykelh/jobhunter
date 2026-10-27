"""Score de correspondance entre une offre et le CV de base.

On repère dans la fiche les compétences d'un vocabulaire data (cv.VOCAB) et on regarde
lesquelles figurent dans cv/base_cv.json (compétences, projets, expériences).
score = compétences demandées que tu as / compétences demandées repérées.
"""
from __future__ import annotations

import json
import re

from .filters import norm

# Mots trop ambigus pour un score (une lettre, sigles courants dans d'autres sens)
SKIP = {"r", "ia", "api", "moa", "audit", "contrôle", "risque"}
ALIASES = {  # écriture dans l'offre → écritures acceptées dans le CV
    "power bi": ["power bi", "powerbi"], "tableaux de bord": ["tableaux de bord", "tableau de bord", "dashboard"],
    "dashboard": ["dashboard", "tableau de bord"], "qualité des données": ["qualité des données", "data quality"],
    "data quality": ["data quality", "qualité des données"], "machine learning": ["machine learning", "scikit-learn"],
    "intelligence artificielle": ["intelligence artificielle", "rag", "llm", "machine learning"],
    "postgresql": ["postgresql", "postgres"], "etl": ["etl"], "elt": ["elt"], "kpi": ["kpi", "indicateur"],
}
_cv_cache: dict = {}


# "Tableau" (le logiciel) ≠ "tableau de bord"
SPECIAL = {"tableau": r"(?<![a-z0-9])tableau(?!x)(?! de bord)(?![a-z0-9])"}


def _has(text: str, word: str) -> bool:
    rx = SPECIAL.get(word) or r"(?<![a-z0-9])" + re.escape(norm(word)) + r"(?![a-z0-9])"
    return bool(re.search(rx, text))


def _cv_text() -> str:
    if "t" not in _cv_cache:
        from .cv import load_base
        _cv_cache["t"] = norm(json.dumps(load_base(), ensure_ascii=False))
    return _cv_cache["t"]


def compute(title: str, description: str) -> dict | None:
    from .cv import VOCAB
    offer = norm((title or "") + " " + (description or ""))
    if len(offer) < 200:
        return None
    cv = _cv_text()
    asked = [w for w in VOCAB if w not in SKIP and _has(offer, w)]
    if len(asked) < 3:
        return None
    have = [w for w in asked if any(_has(cv, a) for a in ALIASES.get(w, [w]))]
    missing = [w for w in asked if w not in have]
    return {"score": round(100 * len(have) / len(asked)), "have": have[:10], "missing": missing[:10]}
