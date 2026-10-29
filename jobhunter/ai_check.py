"""Deuxième contrôle de l'expérience demandée, par IA (Groq, gratuit).

Les règles (filters.py) attrapent les formulations courantes. L'IA lit la fiche
comme un humain pour les cas tordus ("expérience réussie sur un poste similaire",
"you bring a strong background in…"). Elle doit citer la phrase exacte de la fiche ;
si la citation n'existe pas dans le texte, sa réponse est ignorée (pas d'invention).
Sans clé GROQ_API_KEY, ce contrôle est simplement sauté.
"""
from __future__ import annotations

import json
import logging
import os
import re

import requests

from .filters import norm

log = logging.getLogger("jobwatch")

SYSTEM = (
    "Tu lis une offre d'emploi et tu indiques l'expérience professionnelle MINIMUM exigée du candidat "
    "pour CE poste. Réponds uniquement en JSON : "
    '{"annees_min": int ou null, "niveau": "debutant" | "junior" | "confirme" | "senior" | "inconnu", '
    '"citation": "phrase exacte de l\'offre, recopiée mot pour mot, 200 caractères max"}. '
    "Règles : si une fourchette est donnée (ex. 3 à 5 ans), annees_min = la borne basse. "
    "Si plusieurs exigences, prends la plus élevée. Les stages et l'alternance comptent comme débutant. "
    "Une formule sans chiffre comme 'expérience significative', 'solide expérience', 'plusieurs années', "
    "'proven track record', 'mehrjährige Erfahrung' = niveau confirme et annees_min = 3. "
    "'Première expérience', 'jeune diplômé', 'débutant accepté' = niveau junior et annees_min = 0 ou 1. "
    "L'ancienneté de l'entreprise (ex. 'fort de 100 ans d'expérience') n'est PAS une exigence. "
    "Si l'offre ne dit rien sur l'expérience : annees_min null, niveau inconnu, citation vide."
)


class ExperienceAI:
    def __init__(self, enabled: bool = True, budget: int = 40):
        self.key = os.getenv("GROQ_API_KEY")
        self.enabled = bool(enabled and self.key)
        self.budget = budget
        self.calls = 0

    def check(self, title: str, company: str, text: str) -> dict | None:
        """Renvoie {"years": int|None, "level": str, "quote": str} ou None (pas d'avis fiable)."""
        if not self.enabled or self.calls >= self.budget or len(text or "") < 300:
            return None
        self.calls += 1
        from .llm import LLMError, chat_json
        try:
            out = chat_json(SYSTEM, f"Intitulé : {title}\nEntreprise : {company}\n\n{text[:6000]}", temperature=0, timeout=45)
        except LLMError as e:
            if "401" in str(e) or "clé" in str(e):
                self.enabled = False          # clé refusée ou quota atteint : inutile de continuer ce passage
            return None
        quote = str(out.get("citation") or "").strip()
        level = str(out.get("niveau") or "inconnu").lower()
        years = out.get("annees_min")
        try:
            years = None if years in (None, "", "null") else int(years)
        except (TypeError, ValueError):
            years = None
        # Garde-fou : la citation doit exister dans la fiche, sinon on ne croit pas l'IA
        if not quote or not _quoted(quote, text):
            return None
        if years is None and level in ("confirme", "senior"):
            years = 3
        return {"years": years, "level": level, "quote": quote[:200]}


def _quoted(quote: str, text: str) -> bool:
    q = re.sub(r"[^a-z0-9]+", " ", norm(quote)).strip()
    t = re.sub(r"[^a-z0-9]+", " ", norm(text))
    if len(q) < 8:
        return False
    if q in t:
        return True
    # tolérance : 3 morceaux de 4 mots consécutifs de la citation retrouvés dans la fiche
    w = q.split()
    chunks = [" ".join(w[i:i + 4]) for i in range(0, max(1, len(w) - 3), 2)]
    return sum(c in t for c in chunks) >= min(3, len(chunks))
