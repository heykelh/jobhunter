"""CV adapté à UNE offre, à la demande (bouton « Générer mon CV » du site).

Lancé par le workflow GitHub « JobHunter CV » :
    python -m jobhunter.cv_ondemand --id <id de l'offre> --data main|boards

La fiche de l'offre est rouverte pour lire sa description, puis le CV est écrit
dans docs/data/cv/<id>.json (le seul fichier modifié, pour ne pas gêner les robots).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import cv as cvgen
from .__main__ import CONFIGS, LISTS, load_config
from .sources import Fetcher, detail_for
from .store import ROOT, SITE_DATA, _load

log = logging.getLogger("jobwatch")


def find_job(job_id: str, data: str) -> tuple[dict | None, str]:
    """Cherche l'offre dans la liste demandée, puis dans l'autre (au cas où)."""
    order = [data] + [n for n in LISTS if n != data]
    for name in order:
        d = SITE_DATA if name == "main" else SITE_DATA / name
        for j in _load(d / "jobs.json", {}).get("jobs", []):
            if j.get("id") == job_id:
                return j, name
    return None, data


def source_for(job: dict, cfg: dict) -> dict:
    """Bloc de config de la source qui a trouvé l'offre (pour savoir comment ouvrir sa fiche)."""
    want = job.get("via") or job.get("company")
    for c in cfg.get("companies", []):
        if c.get("name") == want:
            return c
    return {}


def run(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--data", default="main")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    job, data = find_job(args.id.strip(), args.data)
    if not job:
        log.error("Offre %s introuvable (déjà retirée du site ?)", args.id)
        return 1
    cfg = load_config(ROOT / CONFIGS.get(data, "config.yaml"))
    comp = source_for(job, cfg)
    text = ""
    if comp.get("details", True):
        fetcher = Fetcher(delay=0)
        try:
            d = detail_for(comp, fetcher, job["url"])
            text = (d.text if d else "") or ""
        except Exception as e:
            log.warning("Fiche illisible (%s) : CV fait avec l'intitulé seul", type(e).__name__)
        finally:
            fetcher.close()
    c = cvgen.generate(job, text)
    cvgen.publish_base()
    log.info("📄 CV généré pour « %s » (%s) : %s", job["title"], job["company"], c.get("methode"))
    return 0


if __name__ == "__main__":
    sys.exit(run())
