"""CV optimisé pour chaque offre.

1. Le code choisit (règles, pas d'IA) les projets et l'ordre des compétences selon les mots de l'offre.
2. Si une clé Groq est fournie (secret GROQ_API_KEY), l'IA reformule le titre, le profil et les
   puces des projets avec le vocabulaire de l'offre. Le code vérifie ensuite qu'elle n'a rien
   inventé (aucun chiffre ni outil absent du CV de base) ; sinon on garde la version d'origine.
3. Le résultat est écrit dans docs/data/cv/<id>.json ; le site le rend modifiable et l'exporte en Word.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re

import requests

from .filters import norm
from .store import ROOT, SITE_DATA, _save, now

log = logging.getLogger("jobwatch")
BASE_PATH = ROOT / "cv" / "base_cv.json"
CV_DIR = SITE_DATA / "cv"
N_PROJECTS = 4
FORBIDDEN_WORDS = ("harnais", "deterministe", "reconversion", "passionne", "disponible immediatement")

# Vocabulaire repéré dans les offres, pour signaler les mots-clés absents du CV
VOCAB = [
    "python", "sql", "power bi", "tableau", "looker", "excel", "vba", "sas", "r", "dax", "spark", "databricks",
    "snowflake", "dbt", "airflow", "azure", "aws", "gcp", "docker", "kubernetes", "terraform", "git", "api",
    "etl", "elt", "data lake", "data warehouse", "datamart", "modélisation", "machine learning", "ia",
    "intelligence artificielle", "llm", "rag", "statistiques", "prévision", "data quality", "qualité des données",
    "gouvernance", "data steward", "lignage", "métadonnées", "catalogue", "rgpd", "ai act", "bcbs 239",
    "conformité", "audit", "contrôle", "risque", "reporting", "tableaux de bord", "kpi", "dashboard",
    "pilotage", "agile", "scrum", "jira", "recette", "spécifications", "cahier des charges", "moa", "amoa",
    "business analyst", "pricing", "revenue management", "yield", "anglais", "allemand", "sap", "salesforce",
    "dataiku", "alteryx", "qlik", "talend", "informatica", "mongodb", "postgresql", "oracle", "fastapi",
    "next.js", "javascript", "typescript", "scikit-learn", "tensorflow", "pytorch", "nlp",
]


def load_base() -> dict:
    return json.loads(BASE_PATH.read_text(encoding="utf-8"))


def clean_text(s: str) -> str:
    """Règles de mise en forme : pas de tiret long ni demi-cadratin, espaces propres."""
    s = (s or "").replace(" — ", " : ").replace(" – ", " : ")
    s = s.replace("—", "-").replace("–", "-").replace("‒", "-")
    return re.sub(r"[ \t]+", " ", s).strip()


def job_title_for_cv(title: str) -> str:
    t = re.sub(r"\((?:[HFhfMmWwDdXx]\s*/\s*)+[HFhfMmWwDdXx]\)|\b[HF]\s*/\s*[HF]\b|\b[mwd]\s*/\s*[mwd](?:\s*/\s*[mwd])?\b",
               "", title or "")
    t = re.sub(r"\s*[-–|]\s*(CDI|CDD).*$", "", t, flags=re.I)
    return clean_text(re.sub(r"\s{2,}", " ", t)).strip(" -,:")


def _hits(text: str, words) -> int:
    n = 0
    for w in words:
        w = norm(w)
        if w and re.search(r"(?<![a-z0-9])" + re.escape(w), text):
            n += 1
    return n


def select(base: dict, title: str, description: str) -> dict:
    """Partie sans IA : choix et ordre des projets et des compétences."""
    t_title, t_all = norm(title), norm(title + " " + description)
    scored = []
    for i, p in enumerate(base["projets"]):
        s = 3 * _hits(t_title, p.get("tags", [])) + _hits(t_all, p.get("tags", []))
        s += _hits(t_all, re.split(r"[,()/]", p.get("stack", "")))
        scored.append((s, -i, p))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    projets = [copy.deepcopy(p) for _, _, p in scored[:N_PROJECTS]]

    groupes = []
    for g in base["competences"]:
        items = sorted(g["items"], key=lambda it: -_hits(t_all, re.split(r"[()/,]", it) + [it]))
        score = sum(_hits(t_all, re.split(r"[()/,]", it) + [it]) for it in g["items"])
        groupes.append((score, {"groupe": g["groupe"], "items": items}))
    groupes.sort(key=lambda x: -x[0])

    domaines = [g["groupe"].lower() for s, g in groupes if s > 0][:2] or ["analyse de données"]
    titre = job_title_for_cv(title)
    profil = base["profil_modele"].format(titre=titre or "Profil data", domaines=" et ".join(domaines))
    cv_text = norm(json.dumps(base, ensure_ascii=False))
    manquants = [w for w in VOCAB if _hits(t_all, [w]) and not _hits(cv_text, [w])]
    return {"titre": titre, "profil": clean_text(profil), "competences": [g for _, g in groupes],
            "projets": projets, "mots_cles_manquants": manquants[:15]}


# ------------------------------------------------------------------- reformulation IA
def _numbers(s: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", s or ""))


def _safe(new: str, source: str, maxlen: int = 260) -> bool:
    """Refuse une phrase de l'IA qui ajoute un chiffre ou un mot interdit."""
    n = norm(new)
    if not new or len(new) > maxlen or any(w in n for w in FORBIDDEN_WORDS):
        return False
    return _numbers(new) <= _numbers(source)


def rewrite_with_llm(cv: dict, base: dict, title: str, company: str, description: str) -> str:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return "règles seules (pas de clé GROQ_API_KEY)"
    payload = {
        "offre": {"intitule": title, "entreprise": company, "texte": description[:5000]},
        "profil_actuel": cv["profil"],
        "projets": [{"id": p["id"], "titre": p["titre"], "puces": p["puces"]} for p in cv["projets"]],
        "experience": "13 ans au Groupe SNCF (SNCF Réseau, SFERIS) en environnement critique ; "
                      "Master Data Engineer / Data Product Manager Bac+5 Mines Paris - PSL ; 15+ projets data.",
    }
    system = (
        "Tu adaptes un CV français à une offre d'emploi. Réponds uniquement en JSON : "
        '{"titre": str, "profil": str, "projets": [{"id": str, "puces": [str, str]}]}. '
        "Règles strictes : n'invente aucun chiffre, outil, diplôme, client ni expérience ; reformule seulement "
        "les faits fournis avec le vocabulaire de l'offre. Profil : 3 phrases maximum, ton factuel et mesuré, "
        "ni arrogant ni demandeur, sans le mot reconversion, sans mention de disponibilité. "
        "Ne mets pas l'IA en avant si l'offre ne le demande pas. Interdits : tirets longs (utilise les deux-points), "
        "les mots harnais et déterministe. Chaque puce fait moins de 200 caractères. Accents français corrects."
    )
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"), "temperature": 0.3,
                  "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]},
            timeout=60)
        r.raise_for_status()
        out = json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        log.warning("  CV : reformulation IA indisponible (%s), version règles conservée", type(e).__name__)
        return f"règles seules (IA en échec : {type(e).__name__})"

    source = json.dumps(base, ensure_ascii=False) + " " + title + " " + description
    changed = 0
    t = clean_text(str(out.get("titre", "")))
    if t and len(t) <= 90 and _safe(t, source):
        cv["titre"] = t
        changed += 1
    p = clean_text(str(out.get("profil", "")))
    if _safe(p, source, maxlen=600):
        cv["profil"] = p
        changed += 1
    by_id = {x.get("id"): x for x in out.get("projets", []) if isinstance(x, dict)}
    for proj in cv["projets"]:
        new = by_id.get(proj["id"], {}).get("puces") or []
        orig = proj["puces"]
        src = " ".join(orig) + " " + proj.get("stack", "") + " " + proj["titre"]
        kept = [clean_text(str(x)) if _safe(clean_text(str(x)), src) else o
                for x, o in zip(new, orig)]
        if kept and kept != orig:
            proj["puces"] = kept + orig[len(kept):]
            changed += 1
    return f"règles + reformulation IA ({changed} blocs adaptés)"


def generate(job: dict, description: str) -> dict:
    base = load_base()
    cv = select(base, job["title"], description)
    cv["methode"] = rewrite_with_llm(cv, base, job["title"], job["company"], description)
    cv.update({"job_id": job["id"], "entreprise": job["company"], "intitule_offre": job["title"],
               "url_offre": job["url"], "genere_le": now()})
    _save(CV_DIR / f"{job['id']}.json", cv)
    return cv


def has_cv(job_id: str) -> bool:
    return (CV_DIR / f"{job_id}.json").exists()


def publish_base():
    """Copie le CV de base vers le site (l'éditeur s'en sert pour ajouter des projets)."""
    try:
        _save(CV_DIR / "base.json", load_base())
    except Exception as e:
        log.warning("CV de base illisible : %s", e)
