"""Notifications ntfy (https://ntfy.sh) — publication en JSON pour bien gérer les accents."""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger("jobwatch")


def fmt_published(p: str | None) -> str:
    """"2026-10-16T09:41:00+00:00" → "16/10 à 11:41" (heure de Paris) ; "2026-10-16" → "16/10/2026"."""
    if not p:
        return ""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        if len(p) == 10:
            y, m, d = p.split("-")
            return f"{d}/{m}/{y}"
        dt = datetime.fromisoformat(p)
        if dt.tzinfo:
            dt = dt.astimezone(ZoneInfo("Europe/Paris"))
        return dt.strftime("%d/%m à %H:%M")
    except Exception:
        return ""


FLAGS = {"France": "🇫🇷", "Suisse": "🇨🇭", "Luxembourg": "🇱🇺", "Malaisie": "🇲🇾", "Oman": "🇴🇲", "Royaume-Uni": "🇬🇧"}


def country_of(j: dict) -> str:
    from .filters import COUNTRY
    return j.get("country") or COUNTRY.get(j.get("zone"), j.get("zone") or "?")


def flag(j: dict) -> str:
    return FLAGS.get(country_of(j), "🌍")


class Notifier:
    def __init__(self, cfg: dict):
        n = cfg.get("notify", {}) or {}
        self.server = (os.getenv("NTFY_SERVER") or n.get("server") or "https://ntfy.sh").rstrip("/")
        self.topic = os.getenv("NTFY_TOPIC") or n.get("topic") or ""
        self.token = os.getenv("NTFY_TOKEN") or ""
        self.site_url = cfg.get("site_url") or ""
        self.max_per_run = int(n.get("max_per_run", 15))
        self.sent = 0

    @property
    def enabled(self) -> bool:
        return bool(self.topic)

    def send(self, title: str, message: str, click: str | None = None, tags=None, priority: int = 3,
             actions: list | None = None):
        if not self.enabled:
            log.info("[ntfy désactivé] %s — %s", title, message)
            return
        body = {"topic": self.topic, "title": title[:250], "message": message[:3500],
                "priority": priority, "tags": tags or []}
        if click:
            body["click"] = click
        if actions:
            body["actions"] = actions
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            r = requests.post(self.server, json=body, headers=headers, timeout=20)
            r.raise_for_status()
            self.sent += 1
        except Exception as e:
            log.warning("ntfy en échec : %s", e)

    def new_jobs(self, jobs: list[dict]):
        """Une notif par offre, avec le drapeau du pays en tête pour les distinguer d'un coup d'œil."""
        if not jobs:
            return
        if len(jobs) > self.max_per_run:
            lines = [f"{flag(j)} {j['company']} — {j['title']}" for j in jobs[:25]]
            self.send(f"{len(jobs)} nouvelles offres", "\n".join(lines), click=self.site_url or None,
                      tags=["briefcase"], priority=4)
            return
        for j in jobs:
            msg = f"{flag(j)} {country_of(j).upper()} · {j['company']} · {j['zone']} · {j['contract']} · {j['experience']}"
            if j.get("salary"):
                msg += f" · {j['salary']}"
            if j.get("sponsor") is not None:
                msg += "\n" + {"skilled": "✅ Employeur sponsor de visa Skilled Worker",
                                "other": "⚠ Licence de sponsor, mais pas pour le Skilled Worker"}.get(j["sponsor"], "⛔ Employeur absent du registre des sponsors de visa")
            if j.get("published"):
                msg += f"\nPubliée le {fmt_published(j['published'])}"
            actions = [{"action": "view", "label": "Voir l'offre", "url": j["url"]}]
            if self.site_url:
                actions.append({"action": "view", "label": "Mon site", "url": self.site_url})
            self.send(f"{flag(j)} {j['title']}", msg, click=j["url"], tags=["briefcase"], priority=4, actions=actions)
