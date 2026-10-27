"""Filtres : mots-clés, titre exclu, contrat, expérience, zone géographique.

Tout le texte est normalisé (minuscules, sans accents) avant comparaison,
donc "Analyste", "ANALYST" et "analyste" se valent.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s.lower()).strip()


def words_re(words, prefix: bool = False) -> re.Pattern | None:
    """Regex qui trouve un des mots. prefix=True : 'analyst' trouve aussi 'analyste'."""
    parts = []
    for w in words or []:
        w = norm(str(w))
        if not w:
            continue
        parts.append(re.escape(w).replace(r"\ ", r"[\s\-]+"))
    if not parts:
        return None
    tail = "" if prefix else r"(?![a-z0-9])"
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(parts) + ")" + tail)


# --------------------------------------------------------------------------- zones
ZONES: dict[str, re.Pattern] = {
    "Île-de-France": re.compile(
        r"ile[\s\-]de[\s\-]france|(?<![a-z])idf(?![a-z])|(?<![a-z])paris(?![a-z])|la defense"
        r"|(?<!\d)(?:75|77|78|91|92|93|94|95)\d{3}(?!\d)|\((?:75|77|78|91|92|93|94|95)\)"
        r"|hauts[\s\-]de[\s\-]seine|seine[\s\-]saint[\s\-]denis|val[\s\-]de[\s\-]marne|val[\s\-]d'?oise"
        r"|yvelines|essonne|seine[\s\-]et[\s\-]marne"
        r"|saint[\s\-]denis|la plaine|nanterre|courbevoie|puteaux|montrouge|issy[\s\-]les|boulogne[\s\-]billancourt"
        r"|guyancourt|saint[\s\-]quentin[\s\-]en[\s\-]yvelines|massy|evry|creteil|noisy|marne[\s\-]la[\s\-]vallee"
        r"|montreuil|ivry|rueil|levallois|clichy|saint[\s\-]ouen|roissy|orly|cergy|versailles|velizy"
        r"|chatillon|vanves|pantin|bobigny|clamart|meudon|saclay|palaiseau|charenton|nogent|vincennes"
        r"|neuilly|suresnes|gennevilliers|colombes|antony|torcy|lagny|chessy|serris|bussy|meaux|melun"
        r"|saint[\s\-]cloud|sevres|boissy|fontenay|bagnolet|aubervilliers|tremblay|beauchamp|trappes"
    ),
    "Luxembourg": re.compile(
        r"luxembourg|luxemburg|esch[\s\-]sur[\s\-]alzette|bettembourg|leudelange|kirchberg|bertrange"
        r"|strassen|howald|differdange|dudelange|ettelbruck|mersch|wasserbillig|bissen|belval"
    ),
    "Suisse": re.compile(
        r"suisse|switzerland|schweiz|svizzera|geneve|geneva|genf|lausanne|zurich|(?<![a-z])bern(?![a-z])"
        r"|berne|basel|(?<![a-z])bale(?![a-z])|lugano|fribourg|neuchatel|luzern|lucerne|(?<![a-z])sion(?![a-z])"
        r"|winterthur|olten|(?<![a-z])biel|bienne|st\.? ?gallen|(?<![a-z])zug(?![a-z])|renens|yverdon|(?<![a-z])chur(?![a-z])"
        r"|opfikon|wallisellen|altstetten|oerlikon|schlieren|dubendorf"
    ),
    "Malaisie": re.compile(
        r"malaysia|malaisie|kuala[\s\-]lumpur|(?<![a-z])kl(?![a-z]) sentral|petaling[\s\-]jaya|cyberjaya|putrajaya"
        r"|selangor|penang|pulau pinang|johor|shah alam|subang|bangsar|mont kiara"
    ),
    "Oman": re.compile(
        r"(?<![a-z])oman(?![a-z])|sultanate of oman|muscat|mascate|(?<![a-z])sohar(?![a-z])|salalah|(?<![a-z])duqm(?![a-z])"
        r"|(?<![a-z])nizwa(?![a-z])|(?<![a-z])sur(?![a-z]), oman|al[\s\-]khuwair|(?<![a-z])ruwi(?![a-z])"
    ),
}
ZONE_KEYS = {"ile-de-france": "Île-de-France", "idf": "Île-de-France",
             "luxembourg": "Luxembourg", "suisse": "Suisse", "switzerland": "Suisse",
             "malaisie": "Malaisie", "malaysia": "Malaisie", "oman": "Oman"}
# Catégorie (pays) affichée sur le site pour chaque zone
COUNTRY = {"Île-de-France": "France", "Luxembourg": "Luxembourg", "Suisse": "Suisse",
           "Malaisie": "Malaisie", "Oman": "Oman"}

# Lieux clairement hors zones : sert à écarter une offre dont la fiche
# dit "Lisbonne" même si le pied de page mentionne "Paris".
ELSEWHERE = re.compile(
    r"(?<![a-z])(?:portugal|lisbo|porto(?![a-z])|london|londres|united kingdom|royaume[\s\-]uni|(?<![a-z])uk(?![a-z])|india|inde(?![a-z])"
    r"|bangalore|mumbai|chennai|singapore|singapour|hong kong|new york|usa|united states|etats[\s\-]unis"
    r"|belgique|belgium|bruxelles|brussels|spain|espagne|madrid|italy|italie|milan|germany|allemagne"
    r"|frankfurt|munich|poland|pologne|warsaw|maroc|morocco|casablanca|tunisie|canada|montreal|dubai|uae"
    r"|lyon|marseille|toulouse|bordeaux|lille|nantes|rennes|strasbourg|nice(?![a-z])|montpellier|grenoble"
    r"|auvergne|occitanie|nouvelle[\s\-]aquitaine|hauts[\s\-]de[\s\-]france|grand est|bretagne|normandie"
    r"|provence|pays de la loire|centre[\s\-]val|bourgogne)"
)


def detect_zone(text: str) -> str | None:
    t = norm(text)
    for label, rx in ZONES.items():
        if rx.search(t):
            return label
    return None


# ------------------------------------------------------------------------ contrats
CONTRACT_RE = {
    "CDI": re.compile(r"(?<![a-z])cdi(?![a-z])|duree indeterminee|(?<![a-z])permanent|regular position"
                      r"|unbefristet|festanstellung|indefinite"),
    "CDD": re.compile(r"(?<![a-z])cdd(?![a-z])|duree determinee|fixed[\s\-]term|(?<![a-z])befristet"
                      r"|temporary contract|contrat temporaire"),
}
OTHER_CONTRACT = re.compile(
    r"(?<![a-z])stage(?![a-z])|stagiaire|internship|(?<![a-z])intern(?![a-z])|alternance|apprentissage|apprenticeship"
    r"|v\.i\.e|(?<![a-z])vie(?![a-z]) ?(?:contract|contrat)|interim|freelance|praktikum|lehrstelle|werkstudent"
    r"|professionnalisation|convention de stage"
)


def detect_contracts(text: str) -> set[str]:
    t = norm(text)
    return {k for k, rx in CONTRACT_RE.items() if rx.search(t)}


# ---------------------------------------------------------------------- expérience
EXP_WORD = re.compile(r"experi|erfahrung|esperienz|seniorit")
UNIT = r"(?:ans?|annees?|years?|yrs|jahren?|jahre)"
# "trois ans", "five years", "drei Jahre" : on convertit les nombres écrits en lettres
NUM_WORDS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8, "dix": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "seven": 7, "eight": 8, "ten": 10,
    "ein": 1, "einem": 1, "zwei": 2, "drei": 3, "vier": 4, "funf": 5, "sechs": 6, "sieben": 7, "acht": 8, "zehn": 10,
}
_NUMW = re.compile(r"(?<![a-z])(" + "|".join(sorted(NUM_WORDS, key=len, reverse=True)) + r")(?=[\s\-]*(?:\+|\(|a |-|to |bis )?[\s\-]*(?:\d|"
                   + "|".join(NUM_WORDS) + r")?[\s\-]*" + UNIT + r"(?![a-z]))")
RANGE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*(?:a|-|to|bis|et|ou|/)\s*(\d{1,2})\s*\+?\s*" + UNIT + r"(?![a-z])")
UPTO_RE = re.compile(r"(?:jusqu'a|up to|maximum|max\.?|moins de|less than|bis zu|under)\s*(\d{1,2})\s*" + UNIT + r"(?![a-z])")
SINGLE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*\+?\s*" + UNIT + r"(?![a-z])")
PLUS_RE = re.compile(r"(?:plus de|more than|over|uber|mehr als)\s*(\d{1,2})\s*" + UNIT + r"(?![a-z])")
# Champ étiqueté de la fiche : "Niveau d'expérience minimum : 3 - 5 ans", "Experience level: Mid-Senior"…
LABEL_RE = re.compile(
    r"(?:niveau (?:minimum |min\.? )?d'experiences?(?: minimum| min\.?| requis[e]?| souhaite[e]?)?"
    r"|experiences? (?:requise|souhaitee|minimum|min\.?|demandee|professionnelle requise)"
    r"|annees? d'experience|experience level|level of experience|seniority level|years of experience"
    r"|required experience|berufserfahrung|erfahrungsstufe|karrierestufe)\s*:?\s*(.{0,40})"
)
LEVEL_SENIOR = re.compile(r"^\W*(?:confirme|experimente|senior|expert|mid[\s\-]?senior|intermediaire|intermediate"
                          r"|professionnel confirme|berufserfahren|erfahren|manager|11 ans|plus de)")
LEVEL_JUNIOR = re.compile(r"^\W*(?:debutant|junior|jeune diplome|entry|associate|graduate|berufseinsteiger"
                          r"|einsteiger|aucune|sans experience|0\b|moins d'un an|less than)")
# Formules sans chiffre qui veulent dire "plusieurs années" (= 3 ans par défaut)
SIGNIFICANT_RE = re.compile(
    r"experience (?:significative|solide|confirmee|consequente|approfondie|averee|probante|reussie de plusieurs"
    r"|de plusieurs annees|professionnelle significative|minimum de plusieurs)|(?:solide|forte|longue|riche|vaste) experience"
    r"|plusieurs annees d'experience|several years of (?:professional |relevant )?experience|extensive experience"
    r"|proven (?:track record|experience)|significant experience|substantial experience|solid experience"
    r"|mehrjahrige|langjahrige|fundierte (?:berufs)?erfahrung"
)
JUNIOR_RE = re.compile(
    r"junior|debutant|jeune diplome|young graduate|recent graduate|graduate program|entry[\s\-]level|premiere experience"
    r"|first experience|sortie d'ecole|berufseinsteiger|(?<![a-z])einsteiger|0 ?(?:a|-) ?[12] ans"
)
IMPLIED_YEARS = 3


def _words_to_digits(t: str) -> str:
    return _NUMW.sub(lambda m: str(NUM_WORDS[m.group(1)]), t)


def detect_experience(text: str) -> tuple[int | None, bool]:
    years, junior, _ = explain_experience(text)
    return years, junior


def _snip(t: str, a: int, b: int) -> str:
    return t[max(0, a - 45): b + 25].strip()


def explain_experience(text: str) -> tuple[int | None, bool, str]:
    """Renvoie (années minimum demandées ou None, mention junior/débutant ?, extrait qui justifie).

    Règle volontairement stricte : si la fiche cite plusieurs durées d'expérience,
    on retient la PLUS EXIGEANTE (une offre "0-2 ans" qui demande ailleurs "5 ans en
    gestion de projet" est écartée). Un champ étiqueté ("Niveau d'expérience : 3 - 5 ans")
    passe avant tout le reste."""
    t = _words_to_digits(norm(text))
    junior = bool(JUNIOR_RE.search(t))

    # 1) Champ étiqueté
    for m in LABEL_RE.finditer(t):
        val = m.group(1)
        nums = [int(x) for x in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", val[:25])]
        ex = _snip(t, m.start(), m.start() + len(m.group(0)) - len(val) + 25)
        if nums and re.search(UNIT, val[:30]):
            return min(nums[0], 20), junior or nums[0] == 0, ex
        if LEVEL_SENIOR.search(val):
            return IMPLIED_YEARS, junior, ex
        if LEVEL_JUNIOR.search(val):
            return 0, True, ex

    # 2) Durées trouvées près du mot "expérience"
    lows: list[tuple[int, str]] = []
    taken: list[tuple[int, int]] = []

    def near_exp(a: int, b: int) -> bool:
        return bool(EXP_WORD.search(t[max(0, a - 70): b + 70]))

    def overlaps(a: int, b: int) -> bool:
        return any(a < y and b > x for x, y in taken)

    for rx, kind in ((UPTO_RE, "upto"), (PLUS_RE, "plus"), (RANGE_RE, "range"), (SINGLE_RE, "single")):
        for m in rx.finditer(t):
            a, b = m.span()
            # "De 6 à 10 ans" (étiquette SNCF) compte même sans le mot "expérience"
            tagged = kind == "range" and t[max(0, a - 3):a] == "de "
            if overlaps(a, b) or not (near_exp(a, b) or tagged):
                continue
            n = 0 if kind == "upto" else int(m.group(1)) + (1 if kind == "plus" else 0)
            taken.append((a, b))
            if n > 15:          # "fort de 30 ans d'expérience" : l'entreprise, pas le poste
                continue
            lows.append((n, _snip(t, a, b)))
    if lows:
        n, ex = max(lows, key=lambda x: x[0])
        return n, junior, ex

    # 3) "solide expérience", "several years of experience"…
    m = SIGNIFICANT_RE.search(t)
    if m:
        return IMPLIED_YEARS, junior, _snip(t, *m.span())
    return None, junior, ""


# ------------------------------------------------------------------------- critères
@dataclass
class Verdict:
    ok: bool
    reason: str = ""
    contract: str = "?"
    experience: str = "non précisée"
    zone: str = "?"
    junior: bool = False
    country: str = "?"


@dataclass
class Criteria:
    keywords: list[str]
    exclude_title: list[str] = field(default_factory=list)
    contracts: list[str] = field(default_factory=lambda: ["CDI", "CDD"])
    max_experience_years: int = 2
    zones: list[str] = field(default_factory=lambda: ["ile-de-france", "luxembourg", "suisse"])
    unknown_contract: str = "keep"
    unknown_experience: str = "keep"
    unknown_location: str = "drop"
    country_rules: dict = field(default_factory=dict)   # réglages propres à un pays (contrats, expérience)

    def __post_init__(self):
        self.kw_re = words_re(self.keywords, prefix=True)
        self.ex_re = words_re(self.exclude_title)
        self.zone_labels = {ZONE_KEYS.get(norm(z), z) for z in self.zones}
        self.contracts = [c.upper() for c in self.contracts]

    @classmethod
    def from_config(cls, cfg: dict) -> "Criteria":
        keys = ("keywords", "exclude_title", "contracts", "max_experience_years", "zones",
                "unknown_contract", "unknown_experience", "unknown_location", "country_rules")
        return cls(**{k: cfg[k] for k in keys if k in cfg})

    # 1) Filtre rapide sur le titre (avant d'ouvrir la fiche)
    def keyword_hit(self, title: str) -> bool:
        return bool(self.kw_re and self.kw_re.search(norm(title)))

    def title_is_junior(self, title: str) -> bool:
        return bool(JUNIOR_RE.search(norm(title)))

    def title_check(self, title: str) -> tuple[bool, str]:
        if not self.keyword_hit(title):
            return False, "hors mots-clés"
        if re.search(r"(?<![A-Za-z])V\.?I\.?E(?![A-Za-z])", title or ""):
            return False, "titre exclu (VIE)"
        m = self.ex_re.search(norm(title)) if self.ex_re else None
        if m:
            return False, f"titre exclu ({m.group(0)})"
        return True, ""

    # 2) Verdict complet avec la fiche
    def evaluate(self, title: str, structured: str, text: str, default_zone: str | None = None) -> Verdict:
        ok, reason = self.title_check(title)
        if not ok:
            return Verdict(False, reason)
        v = Verdict(True)
        nt = norm(title)

        # 1) Lieu (il décide du pays, donc des règles à appliquer)
        zone = None
        if structured:
            zone = detect_zone(structured)
            if not zone and ELSEWHERE.search(norm(structured)):
                return Verdict(False, "lieu hors zones")
        if not zone:
            zone = detect_zone(title) or detect_zone(text[:4000])
        if not zone and default_zone:
            zone = ZONE_KEYS.get(norm(default_zone), default_zone)
        if zone:
            if zone not in self.zone_labels:
                return Verdict(False, f"lieu hors zones ({zone})")
            v.zone = zone
            v.country = COUNTRY.get(zone, zone)
        elif self.unknown_location == "drop":
            return Verdict(False, "lieu inconnu ou hors zones")
        rules = self.country_rules.get(v.country, {}) or {}
        contracts = [c.upper() for c in rules.get("contracts", self.contracts)]
        max_exp = int(rules.get("max_experience_years", self.max_experience_years))
        unknown_contract = rules.get("unknown_contract", self.unknown_contract)

        # 2) Contrat : d'abord les infos structurées (liste, JSON-LD, flux RSS), puis le texte
        found = detect_contracts(structured)
        if not found and OTHER_CONTRACT.search(norm(structured)):
            return Verdict(False, "contrat hors CDI/CDD (stage, alternance…)")
        if not found:
            found = detect_contracts(text)
        if found:
            wanted = [c for c in contracts if c in found]
            if not wanted:
                return Verdict(False, "contrat " + "/".join(sorted(found)))
            v.contract = "/".join(wanted)
        elif unknown_contract == "drop":
            return Verdict(False, "contrat non précisé")

        # 3) Expérience
        years, junior, evidence = explain_experience(structured + " \n " + text)
        v.junior = junior or bool(JUNIOR_RE.search(nt))
        title_junior = bool(JUNIOR_RE.search(nt))
        if years is not None:
            if years > max_exp and not title_junior:
                return Verdict(False, f"expérience demandée ≥ {years} ans" + (f" « {evidence[:110]} »" if evidence else ""))
            v.experience = "débutant accepté" if years == 0 else f"{years} an{'s' if years > 1 else ''} min."
        elif v.junior:
            v.experience = "junior / débutant"
        elif self.unknown_experience == "drop":
            return Verdict(False, "expérience non précisée")
        if v.junior and years:
            v.experience += " · junior"
        return v
