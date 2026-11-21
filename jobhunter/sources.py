"""Récupération des offres : flux RSS, pages HTML, pages rendues par un navigateur.

Chaque entreprise du config.yaml choisit une `source` :
  - rss  : un flux RSS/Atom (le plus fiable quand il existe, ex. Air France)
  - html : une ou plusieurs pages de liste ; `render: true` les ouvre dans un
           vrai navigateur (Chromium via Playwright) pour les sites en JavaScript.
"""
from __future__ import annotations

import html as html_lib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from itertools import product
from string import Formatter
from urllib.parse import quote_plus, urljoin, urlparse, urlunparse, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("jobwatch")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8,de;q=0.6"}
GENERIC_ANCHORS = {"voir", "voir l'offre", "postuler", "apply", "en savoir plus", "details", "détails",
                   "lire la suite", "more", "read more", "plus", "découvrir", "view job", "see job"}
DROP_PARAMS = {"src", "source", "gclid", "fbclid", "mode", "lcid", "lang"}


@dataclass
class Listing:
    url: str
    title: str
    context: str = ""          # texte autour du lien dans la liste (contrat, lieu…)
    published: str | None = None
    company: str | None = None  # entité précise si la source la donne (ex. Enedis sur le site EDF)
    employer: str | None = None  # employeur réel lu sur un site d'annonces (jobs.ch, jobup.ch…)
    detail: "Detail | None" = None  # fiche déjà lue par la source (évite de la relire)


@dataclass
class Detail:
    text: str = ""
    structured: str = ""       # infos fiables : JSON-LD (lieu, contrat), champs RSS
    title: str | None = None
    published: str | None = None
    employer: str | None = None   # hiringOrganization du JSON-LD
    extra: dict = field(default_factory=dict)


def clean_url(url: str) -> str:
    p = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
         if not k.lower().startswith("utm_") and k.lower() not in DROP_PARAMS]
    return urlunparse((p.scheme, p.netloc.lower(), p.path, "", urlencode(q), ""))


def squash(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


# ------------------------------------------------------------ date de publication
DATE_KEYS = ("datePosted", "DatePosted", "publicationDate", "posted_date", "postedDate", "PostedDate", "postedOn",
             "postingDate", "postingEffectiveDate", "publishedDate", "datePublished", "published_at", "publishedAt",
             "publication_date", "datePublication", "publishDate", "firstPublishedDate", "post_date_gmt",
             "post_date", "date_gmt", "start_date", "creationDate", "create_date", "createdAt", "created_at", "date")
MONTHS = {"janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
          "aout": 8, "août": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12,
          "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
          "september": 9, "october": 10, "november": 11, "december": 12,
          "januar": 1, "februar": 2, "märz": 3, "juni": 6, "juli": 7, "oktober": 10, "dezember": 12}
_LONG = re.compile(r"(?<!\d)(\d{1,2})(?:er)?\.?\s+(" + "|".join(MONTHS) + r")\s+(20\d\d)", re.I)
# Mentions de date de publication dans le texte d'une fiche
PUB_LABEL = re.compile(
    r"(?:publi[ée]e?s?\s*(?:le|on)?|date\s+de\s+(?:publication|parution|mise\s+en\s+ligne)|mise?\s+en\s+ligne\s+le"
    r"|posted\s*(?:on|date)?|date\s+posted|publication\s+date|ver[öo]ffentlicht\s*(?:am)?|publiziert\s*(?:am)?"
    r"|online\s+seit)\s*:?\s*", re.I)
_DMY = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](20\d\d)(?:[ T,àa]+(\d{1,2})[:h](\d{2}))?")
_ISO = re.compile(r"(20\d\d)-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?")


def parse_date(value) -> str | None:
    """Date de publication → texte ISO ("2026-10-16T09:41:00+00:00", ou "2026-10-16" sans heure)."""
    from datetime import datetime, timezone
    from email.utils import parsedate_to_datetime
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and value > 1e9:          # timestamp (s ou ms)
        ts = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(ts, timezone.utc).replace(microsecond=0).isoformat()
    s = str(value).strip()
    m = _ISO.search(s)
    if m:
        y, mo, d, hh, mm, ss, _, tz = m.groups()
        if not hh:
            return f"{y}-{mo}-{d}"
        tz = "+00:00" if tz in (None, "Z") else (tz if ":" in tz else tz[:3] + ":" + tz[3:])
        return f"{y}-{mo}-{d}T{hh}:{mm}:{ss or '00'}{tz}"
    try:                                                          # format RSS : "Tue, 20 Oct 2026 10:00:00 GMT"
        dt = parsedate_to_datetime(s)
        if dt:
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
    except Exception:
        pass
    m = _LONG.search(s)
    if m:
        d, mon, y = m.groups()
        return f"{y}-{MONTHS[mon.lower()]:02d}-{int(d):02d}"
    m = _DMY.search(s)
    if m:
        d, mo, y, hh, mm = m.groups()
        if 1 <= int(mo) <= 12 and 1 <= int(d) <= 31:
            base = f"{y}-{int(mo):02d}-{int(d):02d}"
            # heure locale (Paris) : on la garde sans fuseau, le site l'affichera telle quelle
            return f"{base}T{int(hh):02d}:{mm}:00" if hh else base
    return None


_REL = re.compile(r"(today|aujourd'hui|heute|yesterday|hier|gestern|(\d+)\+?\s*(?:days?|jours?|tagen?))", re.I)


def relative_date(text: str) -> str | None:
    """"Posted Today", "Posted 3 Days Ago", "Publié il y a 2 jours" → date du jour correspondant."""
    from datetime import date, timedelta
    m = _REL.search(text or "")
    if not m:
        return None
    word = m.group(1).lower()
    if m.group(2):
        n = int(m.group(2))
        if "+" in m.group(0) or n >= 30:          # "30+ Days Ago" : trop vague
            return None
    else:
        n = 0 if word in ("today", "aujourd'hui", "heute") else 1
    return (date.today() - timedelta(days=n)).isoformat()


def date_in_text(text: str) -> str | None:
    """Cherche "Publiée le 16/10/2026", "Date de publication : 16 octobre 2026", "Posted on …"."""
    for m in PUB_LABEL.finditer(text or ""):
        p = parse_date(text[m.end(): m.end() + 40])
        if p:
            return p
    return None


def find_date(obj, depth: int = 0) -> str | None:
    if isinstance(obj, dict):
        for k in DATE_KEYS:
            if k == "date" and not _first(obj, TITLE_KEYS):   # "date" seul : seulement sur un objet-offre
                continue
            if k in obj:
                p = parse_date(obj[k])
                if p:
                    return p
        if depth < 2:
            for v in obj.values():
                if isinstance(v, dict):
                    p = find_date(v, depth + 1)
                    if p:
                        return p
    return None


# --------------------------------------------------------------------------- fetch
class Fetcher:
    def __init__(self, delay: float = 1.0):
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self.delay = delay
        self._pw = None
        self._browser = None
        self._ctx = None
        self._last: dict[str, float] = {}
        self.json_calls: list[str] = []   # appels JSON vus pendant le dernier rendu (pour --diagnose)
        self.json_payloads: list = []     # (url, données) des réponses JSON du dernier rendu
        self.diag: list[str] = []         # remarques pour --diagnose
        self.dump_dir = None              # --diagnose : dossier où garder le HTML des pages sans offre
        self.page_info: str = ""          # titre de page + nb de liens du dernier rendu

    def _polite(self, url: str):
        host = urlparse(url).netloc
        wait = self.delay - (time.time() - self._last.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.time()

    def get(self, url: str, render: bool = False, wait_ms: int = 3000, scroll: int = 0) -> str:
        self._polite(url)
        if not render:
            r = self.s.get(url, timeout=30)
            r.raise_for_status()
            if not r.encoding or r.encoding.lower() == "iso-8859-1":
                r.encoding = r.apparent_encoding
            return r.text
        return self._render(url, wait_ms, scroll)

    def _render(self, url: str, wait_ms: int, scroll: int) -> str:
        if self._browser is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            self._ctx = self._browser.new_context(user_agent=UA, locale="fr-FR",
                                                  viewport={"width": 1366, "height": 900})
        page = self._ctx.new_page()
        self.json_calls = []
        self.json_payloads = []
        responses = []

        def on_response(resp):
            try:
                ct = resp.headers.get("content-type", "")
                if "json" in ct and resp.request.resource_type in ("xhr", "fetch"):
                    self.json_calls.append(f"{resp.request.method} {resp.status} {resp.url[:250]}")
                    responses.append(resp)
            except Exception:
                pass

        page.on("response", on_response)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            # Bandeau cookies : on tente d'accepter pour débloquer la liste
            for label in ("Tout accepter", "Accepter", "Accept all", "Accept", "J'accepte", "Alle akzeptieren"):
                try:
                    btn = page.get_by_role("button", name=label, exact=False).first
                    if btn.is_visible(timeout=500):
                        btn.click(timeout=1500)
                        break
                except Exception:
                    pass
            # Si le clic nous a emmenés ailleurs (page "confidentialité"…), on revient à la liste
            try:
                if urlparse(page.url).path.rstrip("/") != urlparse(url).path.rstrip("/"):
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(wait_ms)
            for _ in range(scroll):
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(1200)
            html = page.content()
            try:
                self.page_info = f"titre « {page.title()[:80]} », {page.locator('a').count()} liens <a>"
            except Exception:
                self.page_info = ""
            # Réponses JSON de la page (les sites en JavaScript y chargent souvent leurs offres)
            for resp in responses[:60]:
                try:
                    self.json_payloads.append((resp.url, resp.json()))
                except Exception:
                    pass
            return html
        finally:
            page.close()

    def close(self):
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass


# ------------------------------------------------------------------------- listing
def expand_urls(comp: dict, keywords: list[str]) -> list[str]:
    """Remplit {q} avec chaque mot-clé et {offset}/{page} avec les valeurs du config."""
    urls = comp.get("urls") or ([comp["url"]] if comp.get("url") else [])
    out = []
    for u in urls:
        qs = [quote_plus(k) for k in (comp.get("search_terms") or keywords)] if "{q}" in u else [None]
        offs = comp.get("offsets", [0]) if "{offset}" in u else [None]
        pages = comp.get("pages", [1]) if "{page}" in u else [None]
        for q, o, p in product(qs, offs, pages):
            x = u
            if q is not None:
                x = x.replace("{q}", q)
            if o is not None:
                x = x.replace("{offset}", str(o))
            if p is not None:
                x = x.replace("{page}", str(p))
            out.append(x)
    return list(dict.fromkeys(out))


TITLE_PREFIX = re.compile(r"^\s*(?:ref\.?\s*:?\s*)?\d{4}-\d{3,}\s*[-–:]\s*", re.I)
TITLE_SUFFIX = re.compile(r"\s*(?:la description du poste|stellenbeschreibung|job description|d[ée]couvrir|"
                          r"voir l'offre|postuler|en savoir plus|lire la suite)\s*$", re.I)


def clean_title(t: str) -> str:
    t = TITLE_PREFIX.sub("", squash(html_lib.unescape(html_lib.unescape(t or ""))))
    for _ in range(2):
        t = TITLE_SUFFIX.sub("", t)
    return t.strip(" -–|·")


def _anchor_title(a) -> str:
    # Lien qui englobe toute une carte : on préfère le titre (h1-h4) qu'elle contient
    h = a.find(["h1", "h2", "h3", "h4"])
    if h and len(squash(h.get_text(" ", strip=True))) >= 4:
        return clean_title(h.get_text(" ", strip=True))[:200]
    # Carte sans titre balisé (entreprise, intitulé, lieu, contrat…) : l'intitulé est
    # en général le morceau de texte le plus long
    parts = [squash(s) for s in a.stripped_strings]
    parts = [p for p in parts if 4 <= len(p) <= 160]
    if len(parts) >= 3:
        return clean_title(max(parts, key=len))[:200]
    t = squash(a.get_text(" ", strip=True))
    if len(t) < 4 or len(t) > 200 or t.lower() in GENERIC_ANCHORS:
        h = a.find(["strong", "span"])
        t2 = squash(h.get_text(" ", strip=True)) if h else ""
        t = t2 or squash(a.get("title") or a.get("aria-label") or "")
    return clean_title(t)[:200]


def _context(a) -> str:
    node = a
    best = ""
    for _ in range(5):
        node = node.parent
        if node is None or node.name in ("body", "html", "main"):
            break
        txt = squash(node.get_text(" ", strip=True))
        if len(txt) > 700:
            break
        best = txt
        if node.name in ("li", "article", "tr"):
            break
    return best


def harvest_links(html: str, base_url: str, link_pattern: str | None, keyword_hit) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    rx = re.compile(link_pattern, re.I) if link_pattern else None
    base_host = urlparse(base_url).netloc.split(":")[0].removeprefix("www.")
    found: dict[str, Listing] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        url = clean_url(urljoin(base_url, href))
        if not url.startswith("http"):
            continue
        title = _anchor_title(a)
        if rx:
            if not rx.search(url):
                continue
        else:  # sans motif : même domaine + titre qui contient un mot-clé
            host = urlparse(url).netloc.removeprefix("www.")
            if base_host not in host or not keyword_hit(title):
                continue
        ctx = _context(a)
        own = squash(a.get_text(" ", strip=True))
        if len(own) > len(ctx):  # lien-carte : les infos (contrat, lieu) sont dans le lien lui-même
            ctx = own[:700]
        if (title.lower() in GENERIC_ANCHORS or len(title) < 4) and ctx:
            title = ctx[:140]
        if not title:
            continue
        old = found.get(url)
        better = (not old or (len(old.title) < 6 <= len(title))
                  or (keyword_hit(title) and not keyword_hit(old.title)))
        if better:
            if old and len(old.context) > len(ctx):
                ctx = old.context
            m = _DMY.search(ctx) or _ISO.search(ctx)
            found[url] = Listing(url=url, title=title, context=ctx if ctx != title else "",
                                 published=parse_date(m.group(0)) if m else None)
        elif old and len(ctx) > len(old.context):
            old.context = ctx
    # Certains sites (Phenom, Cornerstone…) mettent les offres dans un JSON embarqué
    for script in soup.find_all("script", type="application/ld+json"):
        for jp in _jobpostings(script.string or ""):
            url = clean_url(urljoin(base_url, jp.get("url") or ""))
            if jp.get("title") and url.startswith("http") and url not in found:
                found[url] = Listing(url=url, title=squash(jp["title"]), context=_jp_struct(jp))
    return list(found.values())


# ----------------------------------------------------------- offres dans du JSON
TITLE_KEYS = ("title", "post_title", "jobTitle", "job_title", "JobTitle", "Title", "postingTitle", "displayJobTitle",
              "intitule", "intitulePoste", "titre", "libelle", "name", "label")
URL_KEYS = ("url", "jobUrl", "job_url", "applyUrl", "detailUrl", "detailsUrl", "externalUrl", "absolute_url",
            "canonicalUrl", "canonical_url", "seoUrl", "link", "href", "permalink", "jobLink", "directlink",
            "Url", "URL")
EMBEDDED_URL = re.compile(r"https?://[^\s\"'|<>]+")


def _first(d: dict, keys) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _find_link(o: dict) -> str:
    link = _first(o, URL_KEYS)
    if link:
        return link
    for v in o.values():                       # un niveau plus bas : {"links": {"directlink": …}}
        if isinstance(v, dict):
            link = _first(v, URL_KEYS)
            if link:
                return link
    for k in ("docid", "uri", "sourceurl", "originalurl"):   # ex. "collection|https://…"
        v = o.get(k)
        if isinstance(v, str):
            m = EMBEDDED_URL.search(v)
            if m:
                return m.group(0)
    return ""


def _flat_text(d, depth: int = 0) -> str:
    """Valeurs texte courtes d'un objet (lieu, contrat, expérience…) pour le filtrage."""
    out = []
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, (str, int, float)) and not isinstance(v, bool):
                s = str(v)
                if 1 < len(s) <= 120 and not s.startswith("http"):
                    out.append(s)
            elif depth < 3:
                out.append(_flat_text(v, depth + 1))
    elif isinstance(d, list) and depth < 3:
        out += [_flat_text(x, depth + 1) if isinstance(x, (dict, list)) else str(x) for x in d[:6]]
    return squash(" ".join(o for o in out if o))[:700]


def _unwrap(y: dict) -> dict:
    """{"data": {...offre...}} → {...offre...}"""
    if not _first(y, TITLE_KEYS):
        for v in y.values():
            if isinstance(v, dict) and _first(v, TITLE_KEYS):
                return v
    return y


def _job_lists(data):
    """Trouve les listes d'au moins 2 objets qui ressemblent à des offres (ont un titre)."""
    stack = [data]
    while stack:
        x = stack.pop()
        if isinstance(x, list):
            dicts = [_unwrap(y) for y in x if isinstance(y, dict)]
            if len(dicts) >= 2 and sum(1 for y in dicts if _first(y, TITLE_KEYS)) >= max(2, len(dicts) // 2):
                yield dicts
            stack.extend(y for y in x if isinstance(y, (list, dict)))
        elif isinstance(x, dict):
            stack.extend(v for v in x.values() if isinstance(v, (list, dict)))


def _html_strings(data, out=None):
    """Morceaux de HTML renvoyés dans du JSON (ex. résultats de recherche VINCI)."""
    out = [] if out is None else out
    if isinstance(data, str):
        if "href=" in data and len(data) > 200:
            out.append(data)
    elif isinstance(data, dict):
        for v in data.values():
            _html_strings(v, out)
    elif isinstance(data, list):
        for v in data:
            _html_strings(v, out)
    return out


IMG_EXT = re.compile(r"\.(?:jpe?g|png|gif|webp|svg|pdf|mp4)$", re.I)


class _Blank(dict):
    def __missing__(self, key):
        return ""


COMPANY_KEYS = ("nomCommercial", "nomEntreprise", "raisonSociale", "company", "companyName", "company_name", "employer", "employerName", "hiringOrganization",
                "organization", "organisation", "advertiser")


def _employer(o: dict) -> str | None:
    for k in COMPANY_KEYS:
        v = o.get(k)
        if isinstance(v, dict):
            v = v.get("name") or v.get("displayName") or v.get("title")
        if isinstance(v, str) and 2 <= len(v.strip()) <= 120:
            return squash(v)
    return None


def listings_from_json(data, base_url: str, url_template: str | None = None) -> tuple[list[Listing], dict | None]:
    """Renvoie (offres, exemple d'objet sans lien exploitable — pour le diagnostic)."""
    out, sample = [], None
    for objs in _job_lists(data):
        for o in objs:
            title = clean_title(_first(o, TITLE_KEYS))
            if not (4 <= len(title) <= 200):
                continue
            link = _find_link(o)
            if url_template:
                fields = [f for _, f, _, _ in Formatter().parse(url_template) if f]
                if all(str(o.get(f, "")).strip() for f in fields):
                    flat = _Blank({k: v for k, v in o.items() if isinstance(v, (str, int, float))})
                    link = url_template.format_map(flat)
                else:
                    link = ""
            if not link:
                sample = sample or o
                continue
            url = clean_url(urljoin(base_url, link))
            if IMG_EXT.search(urlparse(url).path):
                continue
            if url.startswith("http") and not url.rstrip("/").endswith(urlparse(url).netloc):
                out.append(Listing(url=url, title=title, context=_flat_text(o), published=find_date(o),
                                   employer=_employer(o)))
            else:
                sample = sample or o
    return out, sample


PHENOM_RE = re.compile(r"phApp\.ddo\s*=\s*(\{.*?\});\s*\n", re.S)


STATE_RE = re.compile(r"window\.(?:__INIT__|__PRELOADED_STATE__|__INITIAL_STATE__|__APOLLO_STATE__|__DATA__)\s*=\s*\{")


def _balanced(src: str, start: int) -> str | None:
    """Objet JSON qui commence à src[start] == '{' (tient compte des chaînes)."""
    depth, i, n, in_str, esc = 0, start, len(src), False, False
    while i < n:
        c = src[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1
    return None


def inline_json(html: str):
    """JSON d'offres embarqué dans la page (sites Phenom, Next.js, JobCloud…)."""
    for rx in (PHENOM_RE, re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)):
        m = rx.search(html)
        if m:
            try:
                yield json.loads(m.group(1))
            except Exception:
                pass
    for m in STATE_RE.finditer(html or ""):     # window.__INIT__ = {...} (jobs.ch, jobup.ch)
        raw = _balanced(html, m.end() - 1)
        if raw:
            try:
                yield json.loads(re.sub(r"(?<=[:\[,])\s*undefined(?=\s*[,}\]])", "null", raw))
            except Exception:
                pass


def fetch_rss(fetcher: Fetcher, url: str) -> list[Listing]:
    xml = fetcher.get(url)
    soup = BeautifulSoup(xml, "xml")
    out = []
    for it in soup.find_all(["item", "entry"]):
        title = clean_title(it.title.get_text()) if it.title else ""
        link = ""
        if it.link:
            link = it.link.get("href") or it.link.get_text()
        desc_tag = it.find(["description", "summary", "content"])
        desc = BeautifulSoup(desc_tag.get_text(), "lxml").get_text(" ") if desc_tag else ""
        cats = " ".join(c.get_text(" ") for c in it.find_all("category"))
        pub = it.find(["pubDate", "published", "updated"])
        if title and link:
            out.append(Listing(url=clean_url(link.strip()), title=title,
                               context=squash(cats + " " + desc)[:1500],
                               published=parse_date(pub.get_text()) if pub else None))
    return out


# ---------------------------------------------------------------- Workday (API JSON)
def collect_workday(comp: dict, fetcher: Fetcher, keywords: list[str], keyword_hit=None) -> tuple[list[Listing], list[str]]:
    """Sites Workday (ex. Eiffage) : API publique POST …/wday/cxs/<tenant>/<site>/jobs."""
    api, public = comp["api"].rstrip("/"), comp["public_url"].rstrip("/")
    out, errors = {}, []
    # Certains sites Workday exigent désormais la session (cookies + jeton CSRF) de la page publique
    headers = {"Accept": "application/json", "Content-Type": "application/json", "Origin": re.sub(r"(https://[^/]+).*", r"\1", public),
               "Referer": public, "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"}
    try:
        fetcher.s.get(public, timeout=30)
        tok = fetcher.s.cookies.get("CALYPSO_CSRF_TOKEN")
        if tok:
            headers["X-CALYPSO-CSRF-TOKEN"] = tok
    except Exception:
        pass
    denied = 0
    for q in comp.get("search_terms") or keywords:
        page_full = True
        for offset in comp.get("offsets", [0, 20]):
            if not page_full:
                break                                    # page précédente incomplète : rien plus loin
            try:
                payload = {"appliedFacets": comp.get("facets", {}), "limit": 20, "offset": offset, "searchText": q}
                for attempt in range(3):
                    fetcher._polite(api)
                    time.sleep(1.5)                      # Workday limite le nombre de requêtes par minute
                    r = fetcher.s.post(api, json=payload, headers=headers, timeout=30)
                    if r.status_code != 429:
                        break
                    wait = r.headers.get("Retry-After", "")
                    time.sleep(min(60, int(wait)) if wait.isdigit() else 15 * (attempt + 1))
                if r.status_code in (401, 403, 429):
                    denied += 1
                r.raise_for_status()
                posts = r.json().get("jobPostings", [])
                page_full = len(posts) >= 20
                for jp in posts:
                    path = jp.get("externalPath") or ""
                    if not path or not jp.get("title"):
                        continue
                    url = clean_url(public + path)
                    ctx = squash(" ".join([jp.get("locationsText") or ""] + [str(x) for x in jp.get("bulletFields") or []]))
                    out.setdefault(url, Listing(url=url, title=clean_title(jp["title"]), context=ctx,
                                                published=relative_date(jp.get("postedOn") or "")))
            except Exception as e:
                errors.append(f"{api} [{q}/{offset}] → {type(e).__name__}: {str(e)[:120]}")
    fetcher.diag.append(f"[workday] {len(out)} offres via l'API")
    if not out and denied:
        # API refusée : on ouvre la page publique dans le navigateur et on lit les liens des offres
        fetcher.diag.append("[workday] API refusée (401/403/429) : lecture de la page publique avec le navigateur")
        alt = {**comp, "source": "html", "render": True, "wait_ms": comp.get("wait_ms", 6000),
               "urls": [public + "?q={q}"], "link_pattern": comp.get("link_pattern", r"/job/")}
        listings, errs = collect(alt, fetcher, keywords, keyword_hit or (lambda t: True))
        return listings, (errs if not listings else [])
    return list(out.values()), errors


def _html_to_text(h: str) -> str:
    return squash(BeautifulSoup(h or "", "lxml").get_text(" "))


def fetch_workday_detail(comp: dict, fetcher: Fetcher, url: str) -> Detail:
    """Fiche Workday lue par l'API (…/wday/cxs/<tenant>/<site>/job/…) : texte complet sans navigateur."""
    api, public = comp["api"].rstrip("/"), comp["public_url"].rstrip("/")
    path = url[len(public):] if url.startswith(public) else "/job/" + url.split("/job/", 1)[-1]
    api_url = api[: -len("/jobs")] + path if api.endswith("/jobs") else api + path
    fetcher._polite(api_url)
    r = fetcher.s.get(api_url, headers={"Accept": "application/json"}, timeout=30)
    if r.status_code >= 400:
        return fetch_detail(fetcher, url)                   # repli : la page publique
    info = (r.json() or {}).get("jobPostingInfo") or {}
    d = Detail(text=_html_to_text(info.get("jobDescription")), title=clean_title(info.get("title") or "") or None)
    locs = [info.get("location") or ""] + list(info.get("additionalLocations") or [])
    d.structured = squash(" · ".join(filter(None, locs + [info.get("country", {}).get("descriptor") if isinstance(info.get("country"), dict) else "",
                                                         info.get("timeType") or "", info.get("remoteType") or ""])))
    d.published = parse_date(info.get("startDate")) or relative_date(info.get("postedOn") or "")
    org = (r.json() or {}).get("hiringOrganization") or {}
    d.employer = org.get("name") if isinstance(org, dict) else None
    return d


# ------------------------------------------------------------- France Travail (API officielle)
FT_TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire"
FT_SEARCH = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
_ft_token: dict = {}


def _francetravail_token(fetcher: Fetcher) -> str:
    import os
    cid, secret = os.getenv("FT_CLIENT_ID", "").strip(), os.getenv("FT_CLIENT_SECRET", "").strip()
    if not cid or not secret:
        raise RuntimeError("clés France Travail absentes : ajoute les secrets GitHub FT_CLIENT_ID et FT_CLIENT_SECRET")
    if _ft_token.get("exp", 0) > time.time() + 30:
        return _ft_token["tok"]
    r = fetcher.s.post(FT_TOKEN_URL, timeout=30, data={"grant_type": "client_credentials", "client_id": cid,
                                                       "client_secret": secret, "scope": "api_offresdemploiv2 o2dsoffre"})
    r.raise_for_status()
    js = r.json()
    _ft_token.update(tok=js["access_token"], exp=time.time() + int(js.get("expires_in", 1400)))
    return _ft_token["tok"]


def collect_francetravail(comp: dict, fetcher: Fetcher, keywords: list[str]) -> tuple[list[Listing], list[str]]:
    """API « Offres d'emploi v2 » de France Travail : ses offres et celles de ses sites partenaires
    (description complète fournie : aucune fiche à rouvrir)."""
    out, errors = {}, []
    try:
        tok = _francetravail_token(fetcher)
    except Exception as e:
        return [], [f"France Travail → {type(e).__name__}: {str(e)[:160]}"]
    params_base = {"typeContrat": ",".join(comp.get("contracts", ["CDI", "CDD"])), "sort": 1,
                   "publieeDepuis": comp.get("published_within_days", 14), "range": "0-149"}
    params_base.update(comp.get("params", {"region": "11"}))          # 11 = Île-de-France
    for q in comp.get("search_terms") or keywords:
        try:
            fetcher._polite(FT_SEARCH)
            r = fetcher.s.get(FT_SEARCH, params={**params_base, "motsCles": q}, timeout=30,
                              headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"})
            if r.status_code == 204:                                   # aucune offre
                continue
            r.raise_for_status()
            for o in r.json().get("resultats", []):
                url = ((o.get("origineOffre") or {}).get("urlOrigine")
                       or f"https://candidat.francetravail.fr/offres/recherche/detail/{o['id']}")
                lieu = (o.get("lieuTravail") or {}).get("libelle") or ""
                contrat = o.get("typeContratLibelle") or o.get("typeContrat") or ""
                xp = o.get("experienceLibelle") or ""
                partners = ", ".join(p.get("nom", "") for p in (o.get("origineOffre") or {}).get("partenaires") or [])
                d = Detail(text=squash(o.get("description") or ""),
                           structured=squash(" · ".join(filter(None, [lieu, contrat, o.get("typeContrat"), xp]))),
                           title=clean_title(o.get("intitule") or ""), published=parse_date(o.get("dateCreation")),
                           employer=(o.get("entreprise") or {}).get("nom"))
                if partners:
                    d.extra["partenaires"] = partners
                out.setdefault(url, Listing(url=url, title=d.title, context=d.structured, published=d.published,
                                            employer=d.employer, detail=d))
        except Exception as e:
            errors.append(f"France Travail [{q}] → {type(e).__name__}: {str(e)[:140]}")
    fetcher.diag.append(f"[france-travail] {len(out)} offres via l'API")
    return list(out.values()), (errors if not out else [])


# ------------------------------------------------------------- SmartRecruiters
SR_API = "https://api.smartrecruiters.com/v1/companies"


def collect_smartrecruiters(comp: dict, fetcher: Fetcher, keyword_hit=None) -> tuple[list[Listing], list[str]]:
    """API publique SmartRecruiters : toutes les offres d'une entreprise dans les pays suivis,
    triées ensuite par mots-clés sur l'intitulé (moins de requêtes qu'une recherche par mot-clé)."""
    cid = comp["company_id"]
    out, errors = {}, []
    for country in comp.get("countries", ["fr", "ch", "lu"]):
        offset, total = 0, 1
        while offset < min(total, int(comp.get("max_postings", 400))):
            url = f"{SR_API}/{cid}/postings?country={country}&limit=100&offset={offset}"
            try:
                fetcher._polite(url)
                r = fetcher.s.get(url, headers={"Accept": "application/json"}, timeout=30)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                errors.append(f"{url} → {type(e).__name__}: {str(e)[:120]}")
                break
            total = int(data.get("totalFound") or 0)
            items = data.get("content") or []
            for p in items:
                title = clean_title(p.get("name") or "")
                if not title or (keyword_hit and not keyword_hit(title)):
                    continue
                loc = p.get("location") or {}
                where = loc.get("fullLocation") or ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
                ctx = squash(" · ".join(filter(None, [where, (p.get("typeOfEmployment") or {}).get("label"),
                                                      (p.get("experienceLevel") or {}).get("label")])))
                link = f"https://jobs.smartrecruiters.com/{cid}/{p['id']}"
                out.setdefault(link, Listing(url=link, title=title, context=ctx, published=parse_date(p.get("releasedDate")),
                                             employer=(p.get("company") or {}).get("name")))
            if not items:
                break
            offset += 100
    fetcher.diag.append(f"[smartrecruiters] {len(out)} offres avec mots-clés via l'API ({cid})")
    return list(out.values()), (errors if not out else [])


def fetch_smartrecruiters_detail(fetcher: Fetcher, url: str) -> Detail:
    m = re.search(r"smartrecruiters\.com/([^/]+)/(\d+)", url)
    if not m:
        return fetch_detail(fetcher, url)
    api = f"{SR_API}/{m.group(1)}/postings/{m.group(2)}"
    fetcher._polite(api)
    r = fetcher.s.get(api, headers={"Accept": "application/json"}, timeout=30)
    if r.status_code >= 400:
        return fetch_detail(fetcher, url)
    p = r.json() or {}
    sec = ((p.get("jobAd") or {}).get("sections") or {})
    text = " ".join(_html_to_text((sec.get(k) or {}).get("text")) for k in
                    ("jobDescription", "qualifications", "additionalInformation", "companyDescription"))
    loc = p.get("location") or {}
    d = Detail(text=squash(text), title=clean_title(p.get("name") or "") or None)
    d.structured = squash(" · ".join(filter(None, [loc.get("fullLocation") or ", ".join(filter(None, [loc.get("city"), loc.get("country")])),
                                                   (p.get("typeOfEmployment") or {}).get("label"),
                                                   (p.get("experienceLevel") or {}).get("label")])))
    d.published = parse_date(p.get("releasedDate"))
    d.employer = (p.get("company") or {}).get("name")
    return d


# ------------------------------------------------------------- Reed.co.uk (Londres)
REED_API = "https://www.reed.co.uk/api/1.0"


def _reed_auth():
    import os
    key = os.getenv("REED_API_KEY", "").strip()
    return (key, "") if key else None


def _money(v) -> int | None:
    try:
        return int(float(v)) if v not in (None, "", 0) else None
    except (TypeError, ValueError):
        return None


def salary_text(lo, hi, cur: str = "GBP") -> str:
    sym = {"GBP": "£", "EUR": "€", "CHF": "CHF "}.get((cur or "GBP").upper(), "")
    f = lambda n: f"{sym}{n:,}".replace(",", " ")
    if lo and hi and lo != hi:
        return f"{f(lo)} - {f(hi)}"
    return f(hi or lo) if (hi or lo) else ""


def collect_reed(comp: dict, fetcher: Fetcher, keywords: list[str]) -> tuple[list[Listing], list[str]]:
    """API officielle et gratuite de Reed.co.uk (clé personnelle : secret REED_API_KEY)."""
    auth = _reed_auth()
    if not auth:
        return [], ["Reed : pas de clé (secret GitHub REED_API_KEY) — source ignorée"]
    out, errors = {}, []
    for q in comp.get("search_terms") or keywords:
        params = {"keywords": q, "locationName": comp.get("location", "London"),
                  "distanceFromLocation": comp.get("distance_miles", 15), "resultsToTake": 100}
        if comp.get("direct_employers_only", True):
            params["postedByDirectEmployer"] = "true"
        if comp.get("min_salary"):
            params["minimumSalary"] = comp["min_salary"]
        try:
            fetcher._polite(REED_API)
            r = fetcher.s.get(REED_API + "/search", params=params, auth=auth, timeout=30)
            r.raise_for_status()
            for jp in r.json().get("results", []):
                jid, title = jp.get("jobId"), clean_title(jp.get("jobTitle") or "")
                if not jid or not title:
                    continue
                url = jp.get("jobUrl") or f"https://www.reed.co.uk/jobs/{jid}"
                lo, hi = _money(jp.get("minimumSalary")), _money(jp.get("maximumSalary"))
                ctx = squash(" ".join(str(x) for x in (jp.get("locationName"), salary_text(lo, hi, jp.get("currency")),
                                                       jp.get("jobDescription")) if x))
                out.setdefault(str(jid), Listing(url=clean_url(url), title=title, context=ctx,
                                                 published=parse_date(jp.get("date")),
                                                 employer=squash(jp.get("employerName") or "") or None))
        except Exception as e:
            errors.append(f"Reed [{q}] → {type(e).__name__}: {str(e)[:120]}")
    fetcher.diag.append(f"[reed] {len(out)} offres via l'API")
    return list(out.values()), errors


def fetch_reed_detail(fetcher: Fetcher, url: str) -> Detail:
    m = re.search(r"/(\d{6,})(?:[/?#]|$)", url)
    if not m:
        raise ValueError("identifiant Reed introuvable")
    fetcher._polite(REED_API)
    r = fetcher.s.get(f"{REED_API}/jobs/{m.group(1)}", auth=_reed_auth(), timeout=30)
    r.raise_for_status()
    j = r.json()
    desc = squash(BeautifulSoup(j.get("jobDescription") or "", "lxml").get_text(" "))
    contract = (j.get("contractType") or "").lower()
    kind = {"permanent": "permanent", "temporary": "fixed-term temporary contract", "contract": "freelance"}.get(contract, contract)
    lo = _money(j.get("yearlyMinimumSalary") or j.get("minimumSalary"))
    hi = _money(j.get("yearlyMaximumSalary") or j.get("maximumSalary"))
    d = Detail(text=desc, structured=squash(f"{j.get('locationName') or ''} {kind}"),
               title=j.get("jobTitle"), published=parse_date(j.get("datePosted") or j.get("date")),
               employer=squash(j.get("employerName") or "") or None)
    d.extra = {"salary_min": lo, "salary_max": hi, "currency": j.get("currency") or "GBP",
               "salary": salary_text(lo, hi, j.get("currency") or "GBP") or squash(j.get("salary") or "")}
    return d


def detail_for(comp: dict, fetcher: Fetcher, url: str) -> Detail:
    """Fiche complète, selon la source."""
    if comp.get("source") == "reed":
        return fetch_reed_detail(fetcher, url)
    if comp.get("source") == "workday" and not comp.get("render_detail"):
        try:
            return fetch_workday_detail(comp, fetcher, url)
        except Exception:
            pass
    if comp.get("source") == "smartrecruiters":
        return fetch_smartrecruiters_detail(fetcher, url)
    return fetch_detail(fetcher, url, render=comp.get("render_detail", comp.get("render", False)))


# ------------------------------------------- numéros d'offres consécutifs (ex. EDF)
def collect_sequence(comp: dict, fetcher: Fetcher, state: dict) -> tuple[list[Listing], list[str]]:
    """Pour les sites dont la liste est inaccessible mais dont les fiches ont un numéro croissant
    (EDF : /offre/detail/2026-182699). On lit les numéros suivant le dernier connu.

    La numérotation a des trous (numéros pris par d'autres sites du groupe) : si rien n'est trouvé
    après max_miss numéros, on saute en avant par bonds (+50, +100, +200…) pour retrouver le front
    des nouvelles offres, puis on reprend la lecture numéro par numéro."""
    key = comp["name"]
    st = state.setdefault("sequence", {}).setdefault(key, {})
    last = max(int(st.get("last", 0)), int(comp.get("start", 0)))
    max_probe, max_miss = int(comp.get("max_probe", 60)), int(comp.get("max_miss", 30))
    bad = [w.lower() for w in comp.get("skip_titles", ["maintenance", "introuvable", "erreur", "error", "404"])]
    out, errors = [], []
    tried = 0

    def probe(n: int):
        nonlocal tried
        tried += 1
        url = comp["url_template"].format(n=n)
        try:
            fetcher._polite(url)
            r = fetcher.s.get(url, timeout=30)
            if r.status_code >= 400:
                return None
            soup = BeautifulSoup(r.text, "lxml")
            h = soup.find("h1") or soup.find("h2")
            title = clean_title(re.sub(r"\s*\(\d{4}-\d+\)\s*$", "", squash(h.get_text(" ")) if h else ""))
            if not title or any(w in title.lower() for w in bad) or \
                    (comp.get("not_found_text") and comp["not_found_text"].lower() in r.text.lower()):
                return None
            detail = Detail(text=_page_text(BeautifulSoup(r.text, "lxml")))
            detail.published = date_in_text(detail.text)
            company = next((c for c in comp.get("companies", []) if c.lower() in detail.text[:3000].lower()), None)
            return Listing(url=clean_url(url), title=title, context=detail.text[:1500],
                           published=detail.published, company=company, detail=detail)
        except Exception as e:
            errors.append(f"{url} → {type(e).__name__}: {str(e)[:120]}")
            return None

    def scan(start: int):
        """Lit start+1, start+2… jusqu'à max_miss numéros vides d'affilée. Renvoie le dernier numéro trouvé."""
        n, misses, best = start, 0, None
        while tried < max_probe and misses < max_miss:
            n += 1
            l = probe(n)
            if l:
                out.append(l)
                misses, best = 0, n
            else:
                misses += 1
        return best

    best = scan(last)
    jumped = None
    if best is None and tried < max_probe:
        # bonds en avant tous les 250 numéros (4 numéros testés à chaque fois) ; on garde le plus loin qui répond
        front, empty_after = None, 0
        for i in range(1, 25):
            if tried > max_probe - 4:
                break
            base = last + 250 * i
            hit = next((n for n in range(base, base + 4) if (l := probe(n)) and not out.append(l)), None)
            if hit:
                front, empty_after = hit, 0
            elif front is not None:
                empty_after += 1
                if empty_after >= 2:
                    break
        if front is not None:
            jumped = front
            best = scan(front) or front
    if best and best > last:
        st["last"] = best
    fetcher.diag.append(f"[séquence] départ {last}, {tried} numéros lus, {len(out)} offres, dernier trouvé {best}"
                        + (f" (saut jusqu'à {jumped})" if jumped else ""))
    return out, errors


def _dump(fetcher, name: str, url: str, html: str):
    """--diagnose : garde la page reçue (sans offre trouvée) dans docs/data/diag/ pour l'analyser."""
    try:
        from pathlib import Path
        d = Path(fetcher.dump_dir)
        d.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        calls = "\n".join(fetcher.json_calls[:60])
        (d / f"{slug}.html").write_text(f"<!-- {url}\n{calls}\n-->\n" + (html or "")[:600_000], encoding="utf-8")
    except Exception:
        pass


def collect(comp: dict, fetcher: Fetcher, keywords: list[str], keyword_hit,
            state: dict | None = None) -> tuple[list[Listing], list[str]]:
    """Renvoie (offres trouvées, erreurs par URL)."""
    src = comp.get("source", "html")
    if src in ("workday", "sequence", "reed", "smartrecruiters", "francetravail"):
        fetcher.diag = []
        if src == "smartrecruiters":
            return collect_smartrecruiters(comp, fetcher, keyword_hit)
        if src == "francetravail":
            return collect_francetravail(comp, fetcher, keywords)
        if src == "workday":
            return collect_workday(comp, fetcher, keywords, keyword_hit)
        if src == "reed":
            return collect_reed(comp, fetcher, keywords)
        return collect_sequence(comp, fetcher, state if state is not None else {})
    listings: dict[str, Listing] = {}
    errors = []
    fetcher.diag = []
    tpl = comp.get("url_template")
    link_rx = comp.get("link_pattern")
    for url in expand_urls(comp, keywords):
        try:
            if src == "rss":
                items = fetch_rss(fetcher, url)
                json_items = []
            else:
                render = comp.get("render", False)
                fetcher.json_payloads = []
                if src == "json":                       # API JSON appelée directement
                    html = ""
                    payloads = [(url, json.loads(fetcher.get(url)))]
                    items = []
                else:
                    html = fetcher.get(url, render=render,
                                       wait_ms=comp.get("wait_ms", 3000), scroll=comp.get("scroll", 0))
                    items = harvest_links(html, url, link_rx, keyword_hit)
                    if not items and fetcher.dump_dir:
                        _dump(fetcher, comp["name"], url, html)
                    payloads = list(fetcher.json_payloads) if render else []
                    payloads += [("(page)", d) for d in inline_json(html)]
                # Offres trouvées dans les réponses JSON ou le JSON embarqué
                json_items = []
                for src_url, data in payloads:
                    js, sample = listings_from_json(data, url, tpl)
                    for frag in _html_strings(data):    # HTML de résultats renvoyé dans du JSON
                        js += harvest_links(frag, url, link_rx, keyword_hit)
                    jpat = comp.get("json_url_pattern") or link_rx
                    if jpat:
                        js = [j for j in js if re.search(jpat, j.url, re.I)]
                    if js:
                        fetcher.diag.append(f"[json-offres] {len(js)} offres dans {src_url[:120]} "
                                            f"(ex. « {js[0].title} » → {js[0].url}, publiée {js[0].published or '?'})")
                        json_items += js
                    elif sample:
                        keys = ", ".join(list(sample.keys())[:25])
                        fetcher.diag.append(f"[json-sans-lien] {src_url[:120]} — clés : {keys} — exemple : "
                                            f"{json.dumps(sample, ensure_ascii=False)[:500]}")
            # Le JSON est plus fiable (titre, date) que les liens de la page : il passe en premier
            for it in json_items + items:
                old = listings.get(it.url)
                if not old:
                    listings[it.url] = it
                else:
                    old.published = old.published or it.published
                    if len(it.context) > len(old.context):
                        old.context = it.context
        except Exception as e:  # une URL en panne n'arrête pas les autres
            errors.append(f"{url} → {type(e).__name__}: {str(e)[:160]}")
            log.warning("  ! %s", errors[-1])
    return list(listings.values()), errors


# -------------------------------------------------------------------------- détail
def _jobpostings(raw: str):
    try:
        data = json.loads(raw)
    except Exception:
        return []
    stack, out = [data], []
    while stack:
        x = stack.pop()
        if isinstance(x, list):
            stack.extend(x)
        elif isinstance(x, dict):
            t = x.get("@type")
            if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                out.append(x)
            stack.extend(v for k, v in x.items() if k in ("@graph", "itemListElement", "item", "mainEntity"))
    return out


def _jp_struct(jp: dict) -> str:
    bits = []
    locs = jp.get("jobLocation") or []
    for loc in locs if isinstance(locs, list) else [locs]:
        addr = (loc or {}).get("address") or {}
        if isinstance(addr, dict):
            bits += [str(addr.get(k, "")) for k in ("addressLocality", "addressRegion", "postalCode", "addressCountry")]
        elif isinstance(addr, str):
            bits.append(addr)
    et = jp.get("employmentType")
    bits += et if isinstance(et, list) else [str(et or "")]
    if jp.get("experienceRequirements"):
        bits.append(json.dumps(jp["experienceRequirements"], ensure_ascii=False)[:300])
    s = squash(" ".join(b for b in bits if b and b != "None"))
    s = (s.replace("FULL_TIME", "").replace("PART_TIME", "")
          .replace("INTERN", "stage").replace("TEMPORARY", "CDD").replace("CONTRACTOR", "freelance"))
    return squash(s)


def fetch_detail(fetcher: Fetcher, url: str, render: bool = False) -> Detail:
    html = ""
    fetcher.json_payloads = []
    try:
        html = fetcher.get(url)
    except Exception:
        if not render:
            raise
    if render and len(_page_text(BeautifulSoup(html, "lxml")) if html else "") < 600:
        html = fetcher.get(url, render=True, wait_ms=2500)
    soup = BeautifulSoup(html or "", "lxml")
    d = Detail()
    # 1) Données structurées (à lire avant de nettoyer la page, qui retire les <script>)
    for meta in soup.find_all("meta"):
        key = (meta.get("property") or meta.get("name") or meta.get("itemprop") or "").lower()
        if key in ("article:published_time", "dateposted", "datepublished", "date", "dc.date", "og:published_time"):
            d.published = d.published or parse_date(meta.get("content"))
    desc = ""
    for script in soup.find_all("script", type="application/ld+json"):
        jps = _jobpostings(script.string or script.get_text() or "")
        if jps:
            jp = jps[0]
            d.structured = _jp_struct(jp)
            d.title = squash(jp.get("title"))
            d.published = parse_date(jp.get("datePosted")) or d.published
            d.employer = _employer(jp)
            desc = squash(BeautifulSoup(str(jp.get("description") or ""), "lxml").get_text(" "))
            break
    for data in inline_json(html or ""):
        d.published = d.published or find_date(data)
    # 2) Texte de la fiche
    text = _page_text(soup)
    # Description JSON-LD + TOUTE la page : les critères (expérience, contrat) sont souvent
    # dans un encadré à part, loin après la description (ex. Crédit Agricole)
    d.text = (desc + " \n " + text[:20000]) if len(desc) > 200 else text[:25000]
    if not d.published:
        d.published = date_in_text(text)
    # 3) Fiche chargée en JavaScript : la date est souvent dans ses réponses JSON
    if not d.published:
        for _, data in fetcher.json_payloads:
            if isinstance(data, dict):
                d.published = find_date(data)
                if d.published:
                    break
    return d


def _page_text(soup: BeautifulSoup) -> str:
    # On retire menus, pieds de page et formulaires de recherche (leurs listes de
    # régions/contrats fausseraient la détection du lieu et du contrat).
    for t in soup(["script", "style", "noscript", "svg", "nav", "footer", "form", "select", "option"]):
        t.decompose()
    main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    return squash(main.get_text(" ", strip=True))[:20000]
