"""Stockage en fichiers JSON (versionnés dans le dépôt, lus par le site)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_DATA = ROOT / "docs" / "data"
STATE = ROOT / "state" / "state.json"


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def job_id(company: str, url: str) -> str:
    return hashlib.sha1(f"{company}|{url}".encode()).hexdigest()[:12]


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


class Store:
    """Une liste d'offres. "main" = sites carrière (docs/data), "boards" = sites d'emploi (docs/data/boards)."""

    def __init__(self, name: str = "main"):
        self.dir = SITE_DATA if name == "main" else SITE_DATA / name
        self.state_path = STATE if name == "main" else STATE.with_name(f"{name}.json")
        self.jobs: dict[str, dict] = {j["id"]: j for j in _load(self.dir / "jobs.json", {}).get("jobs", [])}
        self.rejected: dict[str, dict] = {r["id"]: r for r in _load(self.dir / "rejected.json", {}).get("items", [])}
        self.health: dict[str, dict] = _load(self.dir / "health.json", {}).get("companies", {})
        self.state: dict = _load(self.state_path, {"seeded": []})
        self.elsewhere: set[tuple[str, str]] = set()   # offres déjà présentes dans l'autre liste

    def see_also(self, other_dir: Path):
        from .filters import norm
        for j in _load(other_dir / "jobs.json", {}).get("jobs", []):
            self.elsewhere.add((norm(j.get("company")), norm(j.get("title"))))

    # -- offres
    def has(self, jid: str) -> bool:
        return jid in self.jobs

    def touch(self, jid: str):
        self.jobs[jid]["last_seen"] = now()

    def add(self, job: dict):
        t = now()
        job.setdefault("first_seen", t)
        job["last_seen"] = t
        self.jobs[job["id"]] = job

    def similar(self, company: str, title: str) -> str | None:
        """Même offre déjà connue (même employeur, même intitulé), ex. publiée sur jobs.ch ET jobup.ch."""
        from .filters import norm
        key = (norm(company), norm(title))
        if key in self.elsewhere:
            return "ailleurs"
        for j in self.jobs.values():
            if (norm(j.get("company")), norm(j.get("title"))) == key:
                return j["id"]
        return None

    def remove(self, jid: str):
        self.jobs.pop(jid, None)

    def reject(self, jid: str, company: str, title: str, url: str, reason: str):
        self.rejected[jid] = {"id": jid, "company": company, "title": title, "url": url,
                              "reason": reason, "at": now()}

    # -- premier passage par entreprise (pas de rafale de notifs au démarrage)
    def is_seeded(self, company: str) -> bool:
        return company in self.state.get("seeded", [])

    def mark_seeded(self, company: str):
        self.state.setdefault("seeded", []).append(company)

    def save(self, meta: dict):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        jobs = sorted(self.jobs.values(), key=lambda j: j["first_seen"], reverse=True)
        jobs = [j for j in jobs if j["last_seen"] >= cutoff]           # on oublie après 60 j sans être vue
        rej = sorted(self.rejected.values(), key=lambda r: r["at"], reverse=True)
        rej = [r for r in rej if r["at"] >= cutoff][:1500]             # on retente après 60 j
        _save(self.dir / "jobs.json", {"updated": now(), "jobs": jobs})
        _save(self.dir / "rejected.json", {"updated": now(), "items": rej})
        _save(self.dir / "health.json", {"updated": now(), "companies": self.health})
        _save(self.dir / "meta.json", meta)
        _save(self.state_path, self.state)
