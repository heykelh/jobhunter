"""Point d'entrée : `python -m jobhunter` (veille normale) ou `python -m jobhunter --diagnose`.

--diagnose : n'ouvre aucune fiche et n'envoie aucune notif. Affiche, pour chaque
entreprise, combien de liens d'offres ont été trouvés et quelques titres. Sert à
vérifier qu'une source fonctionne (à lancer après avoir ajouté une entreprise).
--only "Air France" : ne traite qu'une entreprise.
"""
from __future__ import annotations

import argparse
import html
import json
import time
import logging
import sys
from pathlib import Path

import yaml

from . import cv as cvgen
from .ai_check import ExperienceAI
from .filters import Criteria, norm
from .notify import Notifier
from .sources import Fetcher, collect, fetch_detail
from .store import ROOT, SITE_DATA, Store, job_id, now, _save

log = logging.getLogger("jobwatch")

# À augmenter quand les règles de tri changent : les offres déjà affichées sont alors
# revérifiées (fiche rouverte) et retirées si elles ne passent plus.
RULES_VERSION = 2


def judge(crit: Criteria, ai: ExperienceAI, comp: dict, title: str, context: str, d) -> tuple[bool, str, object]:
    """Verdict complet d'une offre : règles (filters.py) puis, si elles laissent passer, contrôle IA."""
    structured = " ".join(filter(None, [context, d.structured if d else ""]))
    text = d.text if d else ""
    v = crit.evaluate(title, structured, text, comp.get("default_location"))
    if not v.ok:
        return False, v.reason, v
    res = ai.check(title, comp["name"], (structured + "\n" + text).strip())
    if res:
        rules = crit.country_rules.get(v.country, {}) or {}
        max_exp = int(rules.get("max_experience_years", crit.max_experience_years))
        years, level = res["years"], res["level"]
        too_much = (years is not None and years > max_exp) or level == "senior"
        if too_much and not crit.title_is_junior(title):
            label = f"≥ {years} ans" if years is not None else level
            return False, f"expérience demandée {label} (lu par l'IA) « {res['quote'][:110]} »", v
        if v.experience == "non précisée" and years is not None:
            v.experience = "débutant accepté" if years == 0 else f"{years} an{'s' if years > 1 else ''} min."
            v.junior = v.junior or years <= 1
    return True, "", v


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
    all_names = [c["name"] for c in companies]
    # Tour de rôle : on commence là où le passage précédent s'est arrêté (si coupé faute de temps)
    start = store.state.get("next_company", 0) % max(1, len(companies)) if not args.only else 0
    companies = companies[start:] + companies[:start]
    deadline = time.monotonic() + 60 * float(cfg.get("time_budget_minutes", 38))
    ai = ExperienceAI(enabled=cfg.get("experience_ai", True) and not args.diagnose,
                      budget=int(cfg.get("experience_ai_per_run", 40)))
    recheck_budget = int(cfg.get("recheck_per_company", 12))

    # Offres déjà affichées dont le titre ne passe plus (mots exclus ajoutés depuis) : on les retire
    if not args.diagnose:
        for jid, job in list(store.jobs.items()):
            job["title"] = html.unescape(job.get("title", ""))
            ok, reason = crit.title_check(job["title"])
            if not ok:
                store.remove(jid)
                store.reject(jid, job["company"], job["title"], job["url"], reason + " (retirée)")
                log.info("  retirée : %s — %s", job["title"], reason)

    cv_budget = int(cfg.get("cv_per_run", 15))   # CV générés par passage (nouvelles offres d'abord)
    fresh: list[dict] = []
    seeded_summary: list[str] = []
    diagnose: dict = {}
    try:
        for i, comp in enumerate(companies):
            name = comp["name"]
            if not args.diagnose and time.monotonic() > deadline:
                store.state["next_company"] = all_names.index(name)
                log.warning("⏱ Temps écoulé : %s et les suivantes passent en premier au prochain passage", name)
                break
            store.state["next_company"] = 0
            log.info("▶ %s", name)
            h = store.health.get(name, {})
            h.update({"checked_at": now(), "error": "", "warnings": []})
            try:
                listings, errors = collect(comp, fetcher, crit.keywords, crit.keyword_hit,
                                           None if args.diagnose else store.state)
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
                backfill = int(cfg.get("date_backfill_per_company", 10))
                rechecks = recheck_budget
                render_detail = comp.get("render_detail", comp.get("render", False))
                for l in matching:
                    l.title = html.unescape(l.title)
                    jid = job_id(name, l.url)
                    if store.has(jid):
                        store.touch(jid)
                        job = store.jobs[jid]
                        # Revérification avec les règles à jour (fiche rouverte)
                        if job.get("rv", 1) < RULES_VERSION and rechecks > 0:
                            rechecks -= 1
                            try:
                                dd = l.detail or (fetch_detail(fetcher, l.url, render=render_detail)
                                                  if comp.get("details", True) else None)
                                ok, reason, v = judge(crit, ai, comp, l.title, l.context, dd)
                            except Exception as e:
                                log.warning("  revérification impossible (%s) : %s", type(e).__name__, l.title)
                                ok, reason, v = True, "", None
                            if not ok:
                                store.remove(jid)
                                store.reject(jid, name, l.title, l.url, reason + " (retirée)")
                                log.info("  ✗ retirée : %s — %s", l.title, reason)
                                continue
                            if v is not None:
                                job.update({"zone": v.zone, "country": v.country, "contract": v.contract,
                                            "experience": v.experience, "junior": v.junior, "rv": RULES_VERSION})
                        if cv_budget > 0 and not cvgen.has_cv(jid) and cfg.get("cv_enabled", True):
                            cv_budget -= 1
                            try:
                                dd = fetch_detail(fetcher, l.url, render=render_detail) \
                                    if comp.get("details", True) else None
                                cvgen.generate(job, (dd.text if dd else "") or l.context)
                                log.info("  📄 CV généré : %s", l.title)
                            except Exception as e:
                                log.warning("  CV non généré (%s) : %s", type(e).__name__, l.title)
                        # Date de publication manquante sur une offre déjà connue : on la complète
                        if not job.get("published"):
                            if l.published:
                                job["published"] = l.published
                            elif backfill > 0 and comp.get("details", True) and job.get("date_tries", 0) < 3:
                                backfill -= 1
                                job["date_tries"] = job.get("date_tries", 0) + 1
                                try:
                                    dd = fetch_detail(fetcher, l.url, render=render_detail)
                                    if dd.published:
                                        job["published"] = dd.published
                                        log.info("  📅 %s → publiée %s", l.title, dd.published)
                                except Exception:
                                    pass
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
                    d = l.detail
                    if d is None and comp.get("details", True):   # details: false → infos de la liste seules
                        try:
                            d = fetch_detail(fetcher, l.url, render=render_detail)
                        except Exception as e:
                            log.warning("  fiche illisible (%s) : %s", type(e).__name__, l.url)
                    title = l.title
                    text = d.text if d else ""
                    ok, reason, v = judge(crit, ai, comp, title, l.context, d)
                    if not ok:
                        store.reject(jid, name, title, l.url, reason)
                        log.info("  ✗ %s — %s", title, reason)
                        continue
                    job = {"id": jid, "company": l.company or name, "title": title, "url": l.url,
                           "zone": v.zone, "country": v.country, "contract": v.contract, "experience": v.experience,
                           "junior": v.junior, "published": l.published or (d.published if d else None),
                           "seed": first_time, "rv": RULES_VERSION}
                    store.add(job)
                    kept += 1
                    if cv_budget > 0 and cfg.get("cv_enabled", True):
                        cv_budget -= 1
                        try:
                            c = cvgen.generate(job, text or l.context)
                            log.info("  📄 CV généré (%s)", c["methode"])
                        except Exception as e:
                            log.warning("  CV non généré (%s)", type(e).__name__)
                    log.info("  ✓ %s (%s, %s, %s, publiée %s)", title, v.zone, v.contract, v.experience,
                             job["published"] or "?")
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
            "companies": all_names}
    store.save(meta)
    cvgen.publish_base()
    log.info("\nTerminé : %d nouvelle(s) offre(s), %d notif(s) envoyée(s), %d contrôle(s) IA.",
             len(fresh), notifier.sent, ai.calls)
    return 0


if __name__ == "__main__":
    sys.exit(run())
