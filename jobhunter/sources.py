"""Récupération des offres : flux RSS, pages HTML, pages rendues par un navigateur.

Chaque entreprise du config.yaml choisit une `source` :
  - rss  : un flux RSS/Atom (le plus fiable quand il existe, ex. Air France)
  - html : une ou plusieurs pages de liste ; `render: true` les ouvre dans un
           vrai navigateur (Chromium via Playwright) pour les sites en JavaScript.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from itertools import product
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


@dataclass
class Detail:
    text: str = ""
    structured: str = ""       # infos fiables : JSON-LD (lieu, contrat), champs RSS
    title: str | None = None
    published: str | None = None
    extra: dict = field(default_factory=dict)


def clean_url(url: str) -> str:
    p = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
         if not k.lower().startswith("utm_") and k.lower() not in DROP_PARAMS]
    return urlunparse((p.scheme, p.netloc.lower(), p.path, "", urlencode(q), ""))


def squash(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


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
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(wait_ms)
            for _ in range(scroll):
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(1200)
            return page.content()
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


def _anchor_title(a) -> str:
    t = squash(a.get_text(" ", strip=True))
    if len(t) < 4 or len(t) > 200 or t.lower() in GENERIC_ANCHORS:
        h = a.find(["h1", "h2", "h3", "h4", "strong", "span"])
        t2 = squash(h.get_text(" ", strip=True)) if h else ""
        t = t2 or squash(a.get("title") or a.get("aria-label") or "")
    return t[:200]


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
        if (title.lower() in GENERIC_ANCHORS or len(title) < 4) and ctx:
            title = ctx[:140]
        if not title:
            continue
        old = found.get(url)
        if not old or (len(old.title) < 6 <= len(title)):
            found[url] = Listing(url=url, title=title, context=ctx if ctx != title else "")
    # Certains sites (Phenom, Cornerstone…) mettent les offres dans un JSON embarqué
    for script in soup.find_all("script", type="application/ld+json"):
        for jp in _jobpostings(script.string or ""):
            url = clean_url(urljoin(base_url, jp.get("url") or ""))
            if jp.get("title") and url.startswith("http") and url not in found:
                found[url] = Listing(url=url, title=squash(jp["title"]), context=_jp_struct(jp))
    return list(found.values())


def fetch_rss(fetcher: Fetcher, url: str) -> list[Listing]:
    xml = fetcher.get(url)
    soup = BeautifulSoup(xml, "xml")
    out = []
    for it in soup.find_all(["item", "entry"]):
        title = squash(it.title.get_text()) if it.title else ""
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
                               published=pub.get_text().strip() if pub else None))
    return out


def collect(comp: dict, fetcher: Fetcher, keywords: list[str], keyword_hit) -> tuple[list[Listing], list[str]]:
    """Renvoie (offres trouvées, erreurs par URL)."""
    src = comp.get("source", "html")
    listings: dict[str, Listing] = {}
    errors = []
    for url in expand_urls(comp, keywords):
        try:
            if src == "rss":
                items = fetch_rss(fetcher, url)
            else:
                html = fetcher.get(url, render=comp.get("render", False),
                                   wait_ms=comp.get("wait_ms", 3000), scroll=comp.get("scroll", 0))
                items = harvest_links(html, url, comp.get("link_pattern"), keyword_hit)
            for it in items:
                listings.setdefault(it.url, it)
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
    try:
        html = fetcher.get(url)
    except Exception:
        if not render:
            raise
    soup = BeautifulSoup(html, "lxml") if html else None
    text = _page_text(soup) if soup else ""
    if render and len(text) < 600:
        html = fetcher.get(url, render=True, wait_ms=2500)
        soup = BeautifulSoup(html, "lxml")
        text = _page_text(soup)
    d = Detail(text=text)
    for script in soup.find_all("script", type="application/ld+json") if soup else []:
        jps = _jobpostings(script.string or script.get_text() or "")
        if jps:
            jp = jps[0]
            d.structured = _jp_struct(jp)
            d.title = squash(jp.get("title"))
            d.published = jp.get("datePosted")
            desc = BeautifulSoup(str(jp.get("description") or ""), "lxml").get_text(" ")
            if len(desc) > 200:
                d.text = squash(desc) + " " + text[:2000]
            break
    return d


def _page_text(soup: BeautifulSoup) -> str:
    # On retire menus, pieds de page et formulaires de recherche (leurs listes de
    # régions/contrats fausseraient la détection du lieu et du contrat).
    for t in soup(["script", "style", "noscript", "svg", "nav", "footer", "form", "select", "option"]):
        t.decompose()
    main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    return squash(main.get_text(" ", strip=True))[:20000]
