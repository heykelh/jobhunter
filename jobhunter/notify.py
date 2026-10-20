"""Notifications ntfy (https://ntfy.sh) — publication en JSON pour bien gérer les accents."""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger("jobwatch")


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
        if not jobs:
            return
        if len(jobs) > self.max_per_run:
            lines = [f"• {j['company']} — {j['title']}" for j in jobs[:25]]
            self.send(f"{len(jobs)} nouvelles offres", "\n".join(lines), click=self.site_url or None,
                      tags=["briefcase"], priority=4)
            return
        for j in jobs:
            msg = f"{j['company']} · {j['zone']} · {j['contract']} · {j['experience']}"
            actions = [{"action": "view", "label": "Voir l'offre", "url": j["url"]}]
            if self.site_url:
                actions.append({"action": "view", "label": "Mon site", "url": self.site_url})
            self.send(j["title"], msg, click=j["url"], tags=["briefcase"], priority=4, actions=actions)
