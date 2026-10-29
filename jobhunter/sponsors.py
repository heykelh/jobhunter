"""Registre officiel britannique des employeurs autorisés à sponsoriser un visa de travail.

Source : https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers
(fichier CSV mis à jour presque chaque jour par le Home Office). Il est téléchargé une fois
par passage, seulement si une offre au Royaume-Uni doit être vérifiée.

Pour chaque offre à Londres, on cherche l'employeur dans le registre :
  "skilled"  → l'employeur peut sponsoriser un visa Skilled Worker
  "other"    → l'employeur a une licence, mais pas pour le Skilled Worker
  False      → l'employeur n'est pas dans le registre (pas de visa possible chez lui)
  None       → impossible à dire (nom d'employeur absent ou registre indisponible)
"""
from __future__ import annotations

import csv
import io
import logging
import re

from .filters import norm

log = logging.getLogger("jobwatch")
PAGE = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
SUFFIXES = re.compile(r"\b(?:limited|ltd|plc|llp|lp|llc|inc|incorporated|group|holdings?|uk|u\.k\.|gb|"
                      r"europe|international|services|the|t/a|trading as)\b")


def key(name: str) -> str:
    n = norm(name).replace("&", " and ")
    n = re.sub(r"\(.*?\)", " ", n)
    n = SUFFIXES.sub(" ", n)
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


class SponsorRegister:
    def __init__(self, session):
        self.s = session
        self.by_key: dict[str, set[str]] | None = None
        self.failed = False

    def _load(self):
        if self.by_key is not None or self.failed:
            return
        try:
            html = self.s.get(PAGE, timeout=30).text
            m = re.search(r'href="(https://assets\.publishing\.service\.gov\.uk/[^"]+\.csv)"', html)
            if not m:
                raise RuntimeError("lien CSV introuvable sur la page du registre")
            raw = self.s.get(m.group(1), timeout=120).content.decode("utf-8-sig", errors="replace")
            self.by_key = parse_register(raw)
            log.info("  Registre des sponsors UK : %d employeurs", len(self.by_key))
        except Exception as e:
            self.failed = True
            log.warning("  Registre des sponsors UK indisponible (%s)", type(e).__name__)

    def status(self, employer: str | None):
        if not employer:
            return None
        self._load()
        if not self.by_key:
            return None
        return lookup(self.by_key, employer)


def parse_register(raw: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for row in csv.DictReader(io.StringIO(raw)):
        name = row.get("Organisation Name") or row.get("Organisation name") or ""
        route = row.get("Route") or ""
        k = key(name)
        if k:
            out.setdefault(k, set()).add(route.strip())
    return out


def lookup(by_key: dict[str, set[str]], employer: str):
    k = key(employer)
    if not k:
        return None
    routes = by_key.get(k)
    if routes is None and (len(k.split()) >= 2 or len(k) >= 6):   # "Barclays" ↔ "Barclays Bank UK PLC"
        cands = [v for kk, v in by_key.items() if kk.startswith(k + " ")]
        routes = set().union(*cands) if cands else None
    if routes is None:
        return False
    return "skilled" if any("skilled worker" in r.lower() for r in routes) else "other"
