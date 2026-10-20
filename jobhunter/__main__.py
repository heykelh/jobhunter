"""Point d'entrée : `python -m jobhunter` (veille normale) ou `python -m jobhunter --diagnose`.

--diagnose : n'ouvre aucune fiche et n'envoie aucune notif. Affiche, pour chaque
entreprise, combien de liens d'offres ont été trouvés et quelques titres. Sert à
vérifier qu'une source fonctionne (à lancer après avoir ajouté une entreprise).
--only "Air France" : ne traite qu'une entreprise.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml

from .filters import Criteria, norm
from .notify import Notifier
from .sources import Fetcher, collect, fetch_detail
from .store import ROOT, SITE_DATA, Store, job_id, now, _save

log = logging.getLogger("jobwatch")


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def run(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnose", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    cfg = load_config(Path(args.config))
    crit = Criteria.from_config(cfg)
    fetcher = Fetcher(delay=float(cfg.get("delay_seconds", 1.5)))
    store = Store()
    notifier = Notifier(cfg)
    alert_after = int(cfg.get("alert_after_failures", 6))
    companies = [c for c in cfg.get("companies", []) if c.get("enabled", True)]
    if args.only:
        companies = [c for c in companies if c["name"].lower() == args.only.lower()]

    fresh: list[dict] = []
    seeded_summary: list[str] = []
    diagnose: dict = {}
    try:
        for comp in companies:
            name = comp["name"]
            log.info("▶ %s", name)
            h = store.health.get(name, {})
            h.update({"checked_at": now(), "error": "", "warnings": []})
            try:
                listings, errors = collect(comp, fetcher, crit.keywords, crit.keyword_hit)
                must = [norm(x) for x in comp.get("context_must_contain", [])]
                if must:
                    listings = [l for l in listings if any(m in norm(l.title + " " + l.context) for m in must)]
                matching = [l for l in listings if crit.keyword_hit(l.title)]
                h["links_found"], h["keyword_matches"] = len(listings), len(matching)
                h["warnings"] = errors[:5]
                log.info("  %d liens, %d avec mots-clés%s", len(listings), len(matching),
                         f", {len(errors)} URL en erreur" if errors else "")

                if args.diagnose:
                    diagnose[name] = {"links_found": len(listings), "keyword_matches": len(matching),
                                      "errors": errors,
                                      "sample_all": [l.title for l in listings[:10]],
                                      "sample_matching": [{"title": l.title, "url": l.url, "context": l.context[:200]}
                                                          for l in matching[:10]]}
                    for l in matching[:8]:
                        log.info("    · %s  →  %s", l.title, l.url)
                    if not matching:
                        for l in listings[:5]:
                            log.info("    (tout) %s  →  %s", l.title, l.url)
                    for line in fetcher.diag[:6]:
                        log.info("    %s", line)
                    diagnose[name]["json"] = fetcher.diag[:10]
                    if len(matching) < 3 and comp.get("render"):
                        noise = ("google", "analytics", "doubleclick", "facebook", "linkedin", "hotjar",
                                 "didomi", "onetrust", "cookie", "consent", "tagcommander", "contentsquare")
                        calls = [c for c in fetcher.json_calls if not any(n in c.lower() for n in noise)]
                        log.info("    [page] %s", fetcher.page_info or "?")
                        for c in calls[:12]:
                            log.info("    [json] %s", c)
                        diagnose[name]["page_info"] = fetcher.page_info
                        diagnose[name]["json_calls"] = calls[:30]
                    continue

                if not listings and errors:
                    raise RuntimeError(errors[0])

                first_time = not store.is_seeded(name)
                kept, details_done = 0, 0
                max_details = int(comp.get("max_details", cfg.get("max_details_per_company", 25)))
                if first_time:  # au 1er passage on ingère tout le stock existant, sans notif
                    max_details = max(max_details, 120)
                for l in matching:
                    jid = job_id(name, l.url)
                    if store.has(jid):
                        store.touch(jid)
                        continue
                    if jid in store.rejected:
                        continue
                    ok, reason = crit.title_check(l.title)
                    if not ok:
                        store.reject(jid, name, l.title, l.url, reason)
                        continue
                    if details_done >= max_details:  # le reste sera traité au prochain passage
                        continue
                    details_done += 1
                    try:
                        d = fetch_detail(fetcher, l.url, render=comp.get("render_detail", comp.get("render", False)))
                    except Exception as e:
                        log.warning("  fiche illisible (%s) : %s", type(e).__name__, l.url)
                        d = None
                    title = l.title
                    structured = " ".join(filter(None, [l.context, d.structured if d else ""]))
                    text = d.text if d else ""
                    v = crit.evaluate(title, structured, text, comp.get("default_location"))
                    if not v.ok:
                        store.reject(jid, name, title, l.url, v.reason)
                        log.info("  ✗ %s — %s", title, v.reason)
                        continue
                    job = {"id": jid, "company": name, "title": title, "url": l.url,
                           "zone": v.zone, "contract": v.contract, "experience": v.experience,
                           "junior": v.junior, "published": (d.published if d else None) or l.published,
                           "seed": first_time}
                    store.add(job)
                    kept += 1
                    log.info("  ✓ %s (%s, %s, %s)", title, v.zone, v.contract, v.experience)
                    if not first_time or cfg.get("notify", {}).get("first_run", False):
                        fresh.append(job)
                if first_time:
                    store.mark_seeded(name)
                    if kept:
                        seeded_summary.append(f"{name} : {kept}")
                h["kept_this_run"] = kept
                h["status"] = "ok" if listings else "vide"
                if listings:
                    h["last_ok"] = now()
                    h["failures"] = 0
                else:
                    h["failures"] = h.get("failures", 0) + 1
            except Exception as e:
                h["status"] = "erreur"
                h["error"] = f"{type(e).__name__}: {str(e)[:300]}"
                h["failures"] = h.get("failures", 0) + 1
                log.error("  ERREUR %s", h["error"])
            if not args.diagnose and h.get("failures") == alert_after:
                notifier.send(f"⚠ Source {name} en panne",
                              f"Aucune offre lue depuis {alert_after} passages. Dernière erreur : "
                              f"{h.get('error') or 'page vide (le site a peut-être changé)'}",
                              tags=["warning"], priority=3, click=notifier.site_url or None)
            store.health[name] = h
    finally:
        fetcher.close()

    if args.diagnose:
        _save(SITE_DATA / "diagnose.json", {"at": now(), "companies": diagnose})
        log.info("\nDiagnostic écrit dans docs/data/diagnose.json")
        return 0

    notifier.new_jobs(fresh)
    if seeded_summary:
        notifier.send("JobHunter est en route ✅",
                      "Offres déjà en ligne ajoutées au site (sans notif) : " + ", ".join(seeded_summary)
                      + ". Tu seras notifié pour chaque nouvelle offre à partir de maintenant.",
                      click=notifier.site_url or None, tags=["tada"])
    meta = {"updated": now(), "keywords": crit.keywords, "contracts": crit.contracts,
            "zones": sorted(crit.zone_labels), "max_experience_years": crit.max_experience_years,
            "companies": [c["name"] for c in companies]}
    store.save(meta)
    log.info("\nTerminé : %d nouvelle(s) offre(s), %d notif(s) envoyée(s).", len(fresh), notifier.sent)
    return 0


if __name__ == "__main__":
    sys.exit(run())
