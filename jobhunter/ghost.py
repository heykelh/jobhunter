"""Annonces fantômes : offres republiées en boucle, en ligne depuis des mois, viviers déguisés…

Chaque liste garde un historique des publications (docs/data[/boards]/history.json) :
pour chaque couple employeur + intitulé, les périodes pendant lesquelles une annonce
a été vue en ligne. Une annonce qui disparaît puis revient (même intitulé, même
employeur), qui reste en ligne des mois, ou dont le texte parle de « vivier » marque
des points. À partir de `ghost.min_score` points, l'offre quitte la liste normale pour
la section « Annonces fantômes » du site et ne déclenche plus de notif.

Signaux (points) :
  republiée 2 fois ou plus (3 publications successives)          2
  republiée 1 fois après avoir disparu                            1
  en ligne depuis plus de `long_days` (90 j)                      2
  en ligne depuis plus de `old_days` (60 j)                       1
  date de publication rafraîchie (même annonce, date avancée)     1
  texte de vivier / candidature spontanée / "postes réguliers"    2
  cabinet qui cache son client ("pour l'un de nos clients")       1
  même intitulé publié 3 fois ou plus en même temps               1
  employeur listé dans `ghost.employers` (ta liste noire)         2
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .filters import norm
from .store import _load, _save, now

GAP_DAYS = 3          # une annonce absente plus de 3 jours puis revenue = republiée
KEEP_DAYS = 240       # l'historique garde 8 mois

POOL_RE = re.compile(
    r"vivier|candidatures? spontanee|cvtheque|pour (?:de )?(?:nos |vos )?futurs? (?:besoins|recrutements|postes|opportunites)"
    r"|anticiper (?:nos|les) (?:futurs? )?(?:besoins|recrutements)|recrut(?:ons|e) (?:en permanence|tout au long de l'annee|regulierement)"
    r"|postes? (?:a pourvoir|ouverts?) (?:regulierement|toute l'annee|en continu)|offre permanente|annonce permanente"
    r"|talent (?:pool|community|network)|join our talent|future (?:opportunities|openings|vacancies|roles)"
    r"|evergreen|pipeline (?:of|for) (?:talent|candidates|future)|always (?:looking|hiring|interested in)"
    r"|general application|speculative application|open application|initiativbewerbung|talentpool"
)
AGENCY_RE = re.compile(
    r"(?:pour|chez) (?:l'un|l'une|un|une) de nos clients|notre client(?:e)?,? (?:un|une|leader|acteur|groupe|societe|entreprise|grand|important)"
    r"|pour le compte (?:de notre|d'un|d'une) client|our client(?:,| is| a)|on behalf of (?:our|a) client|client confidentiel|confidential client"
    r"|cabinet de recrutement|recruitment agency|agence de recrutement"
)
TITLE_NOISE = re.compile(
    r"\((?:h|f|m|w|d|x|all|tous|toutes|e)[^)]{0,12}\)|\b[hf]\s*/\s*[fh](?:\s*/\s*[xd])?\b|\bm\s*/\s*w\s*/\s*d\b|\bw\s*/\s*m\s*/\s*d\b"
    r"|\d{2,3}\s*-\s*\d{2,3}\s*%|\d{2,3}\s*%|\(?\b(?:cdi|cdd)\b\)?"
)


def title_key(company: str, title: str) -> str:
    t = TITLE_NOISE.sub(" ", norm(title))
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return norm(company) + "|" + t


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _days(a: str | None, b: str | None) -> float:
    da, db = _dt(a), _dt(b)
    return (db - da).total_seconds() / 86400 if da and db else 0.0


class History:
    """Périodes de mise en ligne, par employeur + intitulé."""

    def __init__(self, path: Path, others: list[Path] = ()):
        self.path = path
        self.items: dict[str, list[dict]] = _load(path, {}).get("items", {})
        # l'autre liste (sites carrière ↔ sites d'emploi), en lecture seule
        self.others: list[dict] = [_load(p, {}).get("items", {}) for p in others]

    def seen(self, job: dict, at: str | None = None):
        at = at or job.get("last_seen") or now()
        periods = self.items.setdefault(title_key(job["company"], job["title"]), [])
        mine = [p for p in periods if p["id"] == job["id"]]
        if mine and _days(mine[-1]["last"], at) <= GAP_DAYS:
            p = mine[-1]
            p["last"] = max(p["last"], at)
            if job.get("published"):
                p["pubs"] = sorted(set(p.get("pubs", [])) | {job["published"][:10]})[-6:]
            return
        periods.append({"id": job["id"], "url": job.get("url"), "first": job.get("first_seen") if not mine else at,
                        "last": at, "pubs": [job["published"][:10]] if job.get("published") else []})

    def periods(self, key: str) -> list[dict]:
        out = list(self.items.get(key, []))
        for o in self.others:
            out += o.get(key, [])
        return sorted(out, key=lambda p: p["first"] or "")

    def save(self):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
        items = {}
        for k, ps in self.items.items():
            ps = [p for p in ps if (p.get("last") or "") >= cutoff]
            if ps:
                items[k] = ps
        _save(self.path, {"updated": now(), "items": items})


def _fr(d: str) -> str:
    """2026-08-07 → 07/08/2026"""
    return "/".join(reversed(d[:10].split("-"))) if d else ""


def reposts(periods: list[dict]) -> tuple[int, list[str]]:
    """Nombre de retours en ligne, sous une NOUVELLE adresse, après une absence de plus de GAP_DAYS jours.
    La même annonce (même adresse) qui revient ne compte pas : c'est souvent le site qui était en panne."""
    count, dates, last_end, ids = 0, [], None, set()
    for p in periods:
        known = p["id"] in ids
        ids.add(p["id"])
        if not known and last_end and _days(last_end, p["first"]) > GAP_DAYS:
            count += 1
            dates.append((p["first"] or "")[:10])
        last_end = max(last_end or "", p["last"] or "")
    return count, dates


def text_signals(text: str) -> list[str]:
    """Signaux lus dans la fiche (à l'ajout de l'offre, quand le texte est disponible)."""
    t = norm(text or "")[:20000]
    out = []
    m = POOL_RE.search(t)
    if m:
        out.append("pool:" + t[max(0, m.start() - 30): m.end() + 30].strip())
    m = AGENCY_RE.search(t)
    if m:
        out.append("agency:" + t[max(0, m.start() - 20): m.end() + 30].strip())
    return out


def assess(job: dict, hist: History, cfg: dict, same_title_now: int = 1) -> dict | None:
    g = cfg.get("ghost", {}) or {}
    if g.get("enabled", True) is False:
        return None
    old_days, long_days = int(g.get("old_days", 60)), int(g.get("long_days", 90))
    score, reasons = 0, []
    key = title_key(job["company"], job["title"])
    periods = hist.periods(key)
    n, dates = reposts(periods)
    if n >= 2:
        score += 2
        reasons.append(f"republiée {n} fois (retours en ligne le {', '.join(_fr(d) for d in dates[-3:])})")
    elif n == 1:
        score += 1
        reasons.append(f"republiée après avoir disparu (retour le {_fr(dates[0])})")
    t = now()
    # ancienneté de CETTE annonce (les publications précédentes comptent déjà comme republications)
    starts = [x for x in [job.get("published"), job.get("first_seen")] + [p.get("first") for p in periods if p["id"] == job["id"]] if x]
    since = min(starts) if starts else None
    age = _days(since, t) if since else 0
    if age >= long_days:
        score += 2
        reasons.append(f"en ligne depuis {int(age)} jours (depuis le {_fr(since)})")
    elif age >= old_days:
        score += 1
        reasons.append(f"en ligne depuis {int(age)} jours (depuis le {_fr(since)})")
    pubs = sorted({d for p in periods if p["id"] == job["id"] for d in p.get("pubs", [])})
    if len(pubs) >= 2 and _days(pubs[0], pubs[-1]) >= 7:
        score += 1
        reasons.append(f"date de publication rafraîchie ({_fr(pubs[0])} → {_fr(pubs[-1])}) : l'annonce est remontée artificiellement")
    for s in job.get("ghost_text", []):
        kind, _, quote = s.partition(":")
        if kind == "pool":
            score += 2
            reasons.append(f"annonce de vivier « {quote[:100]} »")
        elif kind == "agency":
            score += 1
            reasons.append(f"cabinet qui cache son client « {quote[:90]} »")
    if same_title_now >= 3:
        score += 1
        reasons.append(f"même intitulé publié {same_title_now} fois en même temps")
    black = [norm(e) for e in g.get("employers", []) or []]
    if any(b and b in norm(job["company"]) for b in black):
        score += 2
        reasons.append("employeur de ta liste « annonces fantômes » (config.yaml → ghost.employers)")
    if score >= int(g.get("min_score", 2)):
        return {"score": score, "reasons": reasons, "reposts": n, "since": (since or "")[:10]}
    return None


def refresh(store, hist: History, cfg: dict, run_start: str) -> int:
    """Met à jour l'historique avec les offres vues pendant ce passage et recalcule les fantômes."""
    for job in store.jobs.values():
        if (job.get("last_seen") or "") >= run_start:
            hist.seen(job)
    counts: dict[str, int] = {}
    for job in store.jobs.values():
        k = title_key(job["company"], job["title"])
        counts[k] = counts.get(k, 0) + 1
    n = 0
    for job in store.jobs.values():
        g = assess(job, hist, cfg, counts[title_key(job["company"], job["title"])])
        if g:
            job["ghost"] = g
            n += 1
        else:
            job.pop("ghost", None)
    hist.save()
    return n
