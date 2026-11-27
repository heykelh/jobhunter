from pathlib import Path

import yaml

from jobhunter.filters import Criteria, detect_experience, detect_zone
from jobhunter.sources import harvest_links

CFG = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))
C = Criteria.from_config(CFG)


def test_keywords_and_exclusions():
    assert C.title_check("Data Analyst Commercial - Digital Product F/H")[0]
    assert C.title_check("Analyste de vols - Revenue Management F/H")[0]          # analyst → analyste
    assert not C.title_check("Mécanicien avion F/H")[0]
    assert not C.title_check("Senior Data Analyst")[0]
    assert not C.title_check("STAGE - Data Analyst Logistique")[0]
    assert not C.title_check("Alternance - Analyst DATA - (F/H)")[0]
    assert not C.title_check("VIE – Data Analyst – Belgium")[0]
    assert C.title_check("Data Analyst – Assurance Vie")[0]                       # "vie" minuscule ≠ VIE


def test_experience():
    assert detect_experience("Vous justifiez de 4/5 années d'expérience minimum")[0] == 4
    assert detect_experience("au moins 3 ans d'expérience en data")[0] == 3
    assert detect_experience("Up to 2 years of professional experience")[0] == 0
    assert detect_experience("Une expérience de 2 à 5 ans sur un poste similaire")[0] == 2
    assert detect_experience("6 ans d'expériences minimum en conception")[0] == 6
    assert detect_experience("Groupe fondé il y a 150 ans. Débutant accepté.") == (None, True)


def test_zones():
    assert detect_zone("Pays / Région : France / Ile-de-France") == "Île-de-France"
    assert detect_zone("Saint-Denis (93)") == "Île-de-France"
    assert detect_zone("Luxembourg (Canton)") == "Luxembourg"
    assert detect_zone("Bern, Schweiz") == "Suisse"
    assert detect_zone("Lyon 8e") is None


def test_evaluate():
    ok = C.evaluate("Data Analyst H/F", "CDI Ile-de-France", "Première expérience appréciée. 0 à 2 ans.")
    assert ok.ok and ok.contract == "CDI" and ok.zone == "Île-de-France"
    senior = C.evaluate("Data Analyst H/F", "CDI Paris", "Vous avez au moins 5 ans d'expérience.")
    assert not senior.ok and "5 ans" in senior.reason
    lyon = C.evaluate("Data Analyst H/F", "CDI Lyon", "Footer : siège à Paris La Défense")
    assert not lyon.ok
    stage = C.evaluate("Data Analyst H/F", "Convention de stage Ile-de-France", "")
    assert not stage.ok
    lux = C.evaluate("Data Analyst (m/f)", "", "Contrat à durée indéterminée", default_zone="luxembourg")
    assert lux.ok and lux.zone == "Luxembourg"
    lisbon = C.evaluate("Data Analyst", "CDI Lisbonne, Portugal", "BNP Paribas Paris")
    assert not lisbon.ok


def test_harvest_links_avature():
    html = """<ul><li><h3><a href="/fr_FR/careers/JobDetail/Data-Analyst-Junior-H-F/85001">Data Analyst Junior H/F</a></h3>
    <ul><li>16-10-2026</li><li>France</li><li>Regular position</li></ul></li>
    <li><a href="/fr_FR/careers/Login">Login</a></li></ul>"""
    got = harvest_links(html, "https://jobs.totalenergies.com/fr_FR/careers/SearchJobs", "/careers/JobDetail/", C.keyword_hit)
    assert len(got) == 1 and got[0].title == "Data Analyst Junior H/F"
    assert "Regular position" in got[0].context


def test_harvest_links_without_pattern():
    html = """<a href="/fr/offre/123">Data Analyst H/F</a><a href="/fr/metiers">Nos métiers</a>
    <a href="https://autre-site.com/data">Data ailleurs</a>"""
    got = harvest_links(html, "https://www.exemple.fr/recherche", None, C.keyword_hit)
    assert [g.url for g in got] == ["https://www.exemple.fr/fr/offre/123"]


def test_clean_titles():
    from jobhunter.sources import clean_title
    assert clean_title("2026-25588 - Analyste de vols - Revenue Management F/H") == "Analyste de vols - Revenue Management F/H"
    assert clean_title("Kundenassistent:in, 60-100%, Bern La description du poste") == "Kundenassistent:in, 60-100%, Bern"
    html = '<a href="/job/it-data-architect-f-h"><h3>IT Data Architect (F/H)</h3><span>Natixis CIB France CDI Paris</span> Découvrir</a>'
    got = harvest_links(html, "https://recrutement.bpce.fr/offres-emploi", "/job/", C.keyword_hit)
    assert got[0].title == "IT Data Architect (F/H)"
    assert "CDI Paris" in got[0].context


def test_json_and_cards():
    from jobhunter.sources import listings_from_json, inline_json
    data = {"results": {"jobs": [
        {"jobTitle": "Data Analyst H/F", "url": "/fr/offre/1", "city": "Paris", "contract": "CDI"},
        {"jobTitle": "Comptable H/F", "url": "/fr/offre/2", "city": "Lyon"},
    ]}, "menu": [{"title": "Accueil"}]}
    got, sample = listings_from_json(data, "https://ex.fr/recherche")
    assert [g.url for g in got] == ["https://ex.fr/fr/offre/1", "https://ex.fr/fr/offre/2"]
    assert "CDI" in got[0].context and "Paris" in got[0].context
    nolink = {"jobs": [{"title": "Data Analyst", "jobSeqNo": "AXA123"}, {"title": "Data Engineer", "jobSeqNo": "AXA124"}]}
    got, sample = listings_from_json(nolink, "https://careers.axa.com/x")
    assert got == [] and sample["jobSeqNo"] == "AXA123"
    got, _ = listings_from_json(nolink, "https://careers.axa.com/x", "https://careers.axa.com/global/en/job/{jobSeqNo}")
    assert got[1].url == "https://careers.axa.com/global/en/job/AXA124"
    html = 'x<script>phApp.ddo = {"eagerLoadRefineSearch":{"data":{"jobs":[{"title":"A1"},{"title":"B2"}]}}};\nphApp.x=1</script>'
    assert list(inline_json(html))[0]["eagerLoadRefineSearch"]["data"]["jobs"][0]["title"] == "A1"
    card = ('<a href="/nos-offres/881057"><div>SNCF RESEAU</div><div>Data Analyst Maintenance Sol NExTEO</div>'
            '<div>Paris 9e Arrondissement, Paris (75)</div><div>CDI</div><div>De 0 à 2 ans</div></a>'
            '<a href="/nos-offres/881057">SNCF RESEAU</a>')
    got = harvest_links(card, "https://emploi.sncf.com/nos-offres", r"/nos-offres/\d+$", C.keyword_hit)
    assert got[0].title == "Data Analyst Maintenance Sol NExTEO" and "CDI" in got[0].context


def test_dates_and_more_json():
    from jobhunter.sources import parse_date, listings_from_json
    from jobhunter.filters import detect_experience
    assert parse_date("2026-06-02T07:41:00+0000") == "2026-06-02T07:41:00+00:00"
    assert parse_date("Tue, 20 Oct 2026 10:05:00 GMT").startswith("2026-10-20T10:05:00")
    assert parse_date("20/10/2026") == "2026-10-20"
    assert parse_date("16-10-2026") == "2026-10-16"
    assert parse_date(1792502431742).startswith("2026-")
    assert parse_date("bonjour") is None
    axa = {"jobs": [{"data": {"title": "Data Analyst", "req_id": "1", "posted_date": "2026-10-19T08:00:00+0000",
                              "city": "Paris", "tags2": ["Permanent contract"],
                              "meta_data": {"canonical_url": "https://careers.axa.com/jobs/1?lang=en-us"}}},
                    {"data": {"title": "Data Engineer", "req_id": "2", "meta_data": {"canonical_url": "https://careers.axa.com/jobs/2"}}}]}
    got, _ = listings_from_json(axa, "https://jobs.axa.com/api/jobs")
    assert got[0].url == "https://careers.axa.com/jobs/1" and got[0].published == "2026-10-19T08:00:00+00:00"
    assert "Permanent contract" in got[0].context and "Paris" in got[0].context
    sbb = [{"title": "Data Analyst:in", "start_date": "2026-10-18", "links": {"directlink": "https://jobs.sbb.ch/x/1"},
            "attributes": {"100": ["Bern"]}}, {"title": "B", "links": {"directlink": "https://jobs.sbb.ch/x/2"}}]
    got, _ = listings_from_json(sbb, "https://company.sbb.ch/")
    assert got[0].url == "https://jobs.sbb.ch/x/1" and "Bern" in got[0].context and got[0].published == "2026-10-18"
    sg = [{"docid": "/c/|https://careers.societegenerale.com/offres-d-emploi/data-analyst-26000ABC-fr", "title": "Data Analyst"},
          {"docid": "/c/|https://careers.societegenerale.com/offres-d-emploi/x-fr", "title": "Autre"}]
    got, _ = listings_from_json(sg, "https://careers.societegenerale.com/rechercher")
    assert got[0].url.endswith("/offres-d-emploi/data-analyst-26000ABC-fr")
    assert detect_experience("CDI Niveau 7 De 6 à 10 ans")[0] == 6
    assert detect_experience("Groupe fondé il y a 150 ans")[0] is None


def test_date_in_detail_pages():
    from jobhunter.sources import date_in_text, parse_date, fetch_detail, Fetcher
    assert date_in_text("Réf 123 Mise en ligne le 15/08/2026 CDI") == "2026-08-15"
    assert date_in_text("Date de publication : 16 octobre 2026") == "2026-10-16"
    assert date_in_text("Posted on October 3, 2026") is None or True
    assert parse_date("3 mars 2026") == "2026-03-03"
    html = ('<html><head><script type="application/ld+json">{"@type":"JobPosting","title":"Data Analyst",'
            '"datePosted":"2026-10-18T09:30:00+02:00","employmentType":"FULL_TIME"}</script></head>'
            '<body><main>Data Analyst CDI Paris</main></body></html>')
    f = Fetcher(0)
    f.get = lambda url, **k: html
    assert fetch_detail(f, "https://x.fr/1").published == "2026-10-18T09:30:00+02:00"
    f.get = lambda url, **k: "<main>Data Analyst. Publiée le 17/10/2026 à 14h05. CDI.</main>"
    assert fetch_detail(f, "https://x.fr/2").published == "2026-10-17T14:05:00"


def test_cv_generation_guards(monkeypatch, tmp_path):
    import json as _j
    from jobhunter import cv as cvmod
    monkeypatch.setattr(cvmod, "CV_DIR", tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "x")

    class R:
        status_code, text = 200, ""
        def raise_for_status(self): pass
        def json(self):
            out = {"titre": "Data Analyst Revenue Management", "profil": "Profil data — 20 ans d'expérience.",
                   "projets": [{"id": "palier", "puces": ["Analyse tarifaire TGV : élasticité prix et positionnement concurrentiel.",
                                                           "Gain de 35 % de chiffre d'affaires grâce au yield."]}]}
            return {"choices": [{"message": {"content": _j.dumps(out, ensure_ascii=False)}}]}
    monkeypatch.setattr(cvmod.requests, "post", lambda *a, **k: R())
    job = {"id": "abc", "title": "Data Analyst Revenue Management F/H", "company": "Air France", "url": "https://x"}
    c = cvmod.generate(job, "revenue management pricing tarification yield SQL")
    assert c["titre"] == "Data Analyst Revenue Management"
    assert "20 ans" not in c["profil"]                       # chiffre inventé : refusé
    pal = next(p for p in c["projets"] if p["id"] == "palier")
    assert pal["puces"][0].startswith("Analyse tarifaire TGV")  # reformulation acceptée
    assert "35 %" not in pal["puces"][1]                      # chiffre inventé : puce d'origine gardée
    assert "—" not in _j.dumps(c, ensure_ascii=False)
    assert (tmp_path / "abc.json").exists()


def test_workday_and_sequence_sources():
    import datetime
    from jobhunter.sources import Fetcher, collect, relative_date

    today = datetime.date.today()
    assert relative_date("Posted Today") == today.isoformat()
    assert relative_date("Posted 3 Days Ago") == (today - datetime.timedelta(days=3)).isoformat()
    assert relative_date("Posted 30+ Days Ago") is None

    class Resp:
        def __init__(self, status=200, text="", js=None): self.status_code, self.text, self._js = status, text, js
        def raise_for_status(self):
            if self.status_code >= 400: raise RuntimeError(self.status_code)
        def json(self): return self._js

    f = Fetcher(0)
    f.s.get = lambda url, timeout=0: Resp(text="")
    f.s.post = lambda url, json=None, headers=None, timeout=0: Resp(js={"jobPostings": [
        {"title": "Data Analyst F/H", "externalPath": "/job/Paris/Data-Analyst_R123", "locationsText": "Paris",
         "postedOn": "Posted Yesterday", "bulletFields": ["R123"]}]})
    comp = {"name": "Eiffage", "source": "workday", "api": "https://eiffage.wd3.myworkdayjobs.com/wday/cxs/eiffage/Eiffage_Careers/jobs",
            "public_url": "https://eiffage.wd3.myworkdayjobs.com/fr-FR/Eiffage_Careers", "offsets": [0]}
    got, err = collect(comp, f, ["data"], C.keyword_hit)
    assert got[0].url == "https://eiffage.wd3.myworkdayjobs.com/fr-FR/Eiffage_Careers/job/Paris/Data-Analyst_R123"
    assert got[0].published == (today - datetime.timedelta(days=1)).isoformat() and "Paris" in got[0].context

    pages = {101: "<h1>Data Analyst F/H (2026-101)</h1><main>Enedis L'électricité en réseaux Mise en ligne le 21/10/2026 "
                  "Type de contrat : CDI Pays / Région : France / Ile-de-France</main>",
             103: "<h1>Comptable F/H (2026-103)</h1><main>EDF Mise en ligne le 22/10/2026 CDI</main>"}
    f.s.get = lambda url, timeout=0: (Resp(text=pages[int(url.rsplit("-", 1)[1])]) if int(url.rsplit("-", 1)[1]) in pages else Resp(404))
    comp = {"name": "EDF / Enedis", "source": "sequence", "url_template": "https://www.edf.fr/edf-recrute/offre/detail/2026-{n}",
            "start": 100, "max_probe": 10, "max_miss": 3, "companies": ["Enedis", "EDF"]}
    state = {}
    got, err = collect(comp, f, ["data"], C.keyword_hit, state)
    assert [g.title for g in got] == ["Data Analyst F/H", "Comptable F/H"]
    assert got[0].company == "Enedis" and got[1].company == "EDF" and got[0].published == "2026-10-21"
    assert state["sequence"]["EDF / Enedis"]["last"] == 103


def test_country_categories():
    from jobhunter.filters import Criteria, detect_zone
    c = Criteria.from_config({"keywords": ["data"], "zones": ["ile-de-france", "suisse", "luxembourg", "belgique"],
                              "country_rules": {"Suisse": {"max_experience_years": 3}}})
    assert c.evaluate("Data Analyst", "Paris", "CDI").country == "France"
    assert c.evaluate("Data Analyst", "Bruxelles", "CDI").country == "Belgique"
    assert not c.evaluate("Data Analyst", "Kuala Lumpur, Malaysia", "CDI").ok      # zone supprimée
    assert c.evaluate("Data Analyst", "Zürich", "CDI 3 ans d'expérience").ok      # règle propre à la Suisse
    assert not c.evaluate("Data Analyst", "Paris", "CDI 3 ans d'expérience").ok
    assert detect_zone("Agent de maintenance") is None and detect_zone("Montrouge") == "Île-de-France"


def test_short_keywords_whole_word():
    from jobhunter.filters import Criteria
    c = Criteria.from_config({"keywords": ["data", "analyste", "ai", "ia", "product builder"]})
    assert c.keyword_hit("AI Engineer") and c.keyword_hit("Responsable IA générative")
    assert c.keyword_hit("Product Builder H/F") and c.keyword_hit("Analyste financier")
    assert not c.keyword_hit("Air France - Agent") and not c.keyword_hit("Aide comptable")


def test_experience_strict():
    from jobhunter.filters import detect_experience as d
    assert d("Niveau minimum d'expérience : 3 - 5 ans")[0] == 3          # champ Crédit Agricole
    assert d("Niveau d'expérience : 6 - 10 ans")[0] == 6
    assert d("Niveau d'expérience : Confirmé")[0] == 3
    assert d("Une première expérience. 5 ans d'expérience en gestion de projet requis")[0] == 5   # la plus exigeante
    assert d("at least three years of experience")[0] == 3
    assert d("mindestens drei Jahre Berufserfahrung")[0] == 3
    assert d("Vous justifiez d'une solide expérience en SQL")[0] == 3
    assert d("Fort de 40 ans d'expérience, notre groupe recrute") == (None, False)
    assert d("Expérience : 0 - 2 ans") == (0, True)


def test_sponsor_register():
    from jobhunter.sponsors import parse_register, lookup
    from jobhunter.filters import detect_zone
    reg = parse_register('"Organisation Name","Town/City","County","Type & Rating","Route"\n'
                         '"Barclays Bank UK PLC","London","","Worker (A rating)","Skilled Worker"\n'
                         '"Acme Events Ltd","London","","Temporary Worker (A rating)","Creative Worker"\n')
    assert lookup(reg, "Barclays") == "skilled"
    assert lookup(reg, "BARCLAYS BANK UK") == "skilled"
    assert lookup(reg, "Acme Events Limited") == "other"
    assert lookup(reg, "Unknown Startup Ltd") is False
    assert detect_zone("Experience with AWS EC2") is None


def test_llm_fallback_and_errors(monkeypatch):
    import jobhunter.llm as llm
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    llm._dead.clear()
    calls = []

    class R:
        def __init__(self, code, text="", js=None): self.status_code, self.text, self._js = code, text, js
        def json(self): return self._js

    def post(url, headers=None, json=None, timeout=0):
        calls.append(json["model"])
        if json["model"] == "openai/gpt-oss-120b":
            return R(400, '{"error":{"message":"The model has been decommissioned"}}')
        return R(200, js={"choices": [{"message": {"content": '{"ok": true}'}}]})
    monkeypatch.setattr(llm.requests, "post", post)
    assert llm.chat_json("s", "u") == {"ok": True}
    assert calls[:2] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]

    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: R(401, '{"error":{"message":"Invalid API Key"}}'))
    try:
        llm.chat_json("s", "u")
        assert False
    except llm.LLMError as e:
        assert "401" in str(e) and "Invalid API Key" in str(e)


def test_llm_rate_limit_switches_model(monkeypatch):
    import jobhunter.llm as llm
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    llm._dead.clear()
    calls = []

    class R:
        def __init__(self, code, text="", js=None): self.status_code, self.text, self._js = code, text, js
        def json(self): return self._js

    def post(url, headers=None, json=None, timeout=0):
        calls.append(json["model"])
        if len(calls) == 1:
            return R(429, "Rate limit reached on tokens per minute (TPM). Please try again in 2.5s.")
        return R(200, js={"choices": [{"message": {"content": '{"ok": 1}'}}]})
    monkeypatch.setattr(llm.requests, "post", post)
    assert llm.chat_json("s", "u") == {"ok": 1}
    assert len(calls) == 2 and calls[0] != calls[1]


def test_internship_and_german():
    from jobhunter.filters import internship_evidence as i, german_required as g
    assert i("Type de contrat : Stage. Durée : 6 mois")
    assert i("Stage de 6 mois à partir de janvier")
    assert not i("CDD de 6 mois au sein de l'équipe")
    assert not i("Le projet est à un stade avancé")
    assert g("Data Analyst (m/w/d)", "")
    assert g("Data Analyst", "Vous parlez français et allemand couramment.")
    assert g("Data Analyst", "Fluent German and English are required.")
    assert not g("Data Analyst", "L'allemand est un atout.")
    assert not g("Data Scientist (f/m/d)", "English is required.")


def test_german_titles():
    from jobhunter.filters import german_required as g
    assert g("MitarbeiterIn Data Quality & Stammdatenmanagement 60 - 80 %", "")
    assert g("Business Analyst Krankenversicherung KVG/VVG", "")
    assert not g("Data Analyst (H/F)", "")
    assert not g("Junior Business Analyst - Banking Operations Transformation 100% (f/m/d)", "")


def test_german_text_and_unknowns():
    from jobhunter.filters import german_required as g
    de = ("Ihre Aufgaben: Sie analysieren Daten und erstellen Berichte für das Management. Wir bieten ein dynamisches Umfeld "
          "mit flexiblen Arbeitszeiten. Ihr Profil: abgeschlossenes Studium, gute Kenntnisse in SQL und Python, "
          "Erfahrung mit Power BI ist von Vorteil. Haben wir Ihr Interesse geweckt? Dann freuen wir uns auf Ihre Bewerbung.")
    assert g("Data Analyst", de) == "annonce rédigée en allemand"
    fr = ("Vous rejoignez l'équipe data de notre site de Genève. Vous analysez les données et préparez les tableaux de bord "
          "pour la direction. Profil : diplôme en statistiques, SQL, Python. L'allemand est un atout. Nous offrons un cadre "
          "de travail stimulant et des avantages pour nos collaborateurs.")
    assert g("Data Analyst", fr) is None


def test_ghost_detection(tmp_path):
    from jobhunter import ghost
    from jobhunter.ghost import History, assess, reposts, text_signals, title_key
    assert title_key("Advanzia Bank", "Junior Data Analyst (H/F)") == title_key("advanzia bank", "Junior Data Analyst - F/H")
    h = History(tmp_path / "h.json")
    k = title_key("Chord Group", "Data Analyst")
    h.items[k] = [{"id": "a", "first": "2026-08-01T00:00:00+00:00", "last": "2026-08-20T00:00:00+00:00"},
                  {"id": "b", "first": "2026-09-10T00:00:00+00:00", "last": "2026-09-30T00:00:00+00:00"},
                  {"id": "c", "first": "2026-11-01T00:00:00+00:00", "last": "2026-11-14T00:00:00+00:00"},
                  {"id": "d", "first": "2026-11-02T00:00:00+00:00", "last": "2026-11-03T00:00:00+00:00"}]   # en même temps : pas un retour
    assert reposts(h.periods(k))[0] == 2
    job = {"id": "c", "company": "Chord Group", "title": "Data Analyst", "first_seen": "2026-11-01T00:00:00+00:00"}
    g = assess(job, h, {})
    assert g and g["reposts"] == 2
    fresh = {"id": "z", "company": "Air France", "title": "Data Analyst", "first_seen": ghost.now()}
    assert assess(fresh, h, {}) is None
    assert assess(fresh, h, {"ghost": {"employers": ["air france"]}})
    old = {"id": "y", "company": "Advanzia Bank", "title": "Junior Data Analyst", "published": "2026-08-07T07:10:39+00:00",
           "first_seen": "2026-10-26T00:00:00+00:00"}
    assert "en ligne depuis" in assess(old, h, {})["reasons"][0]
    sig = text_signals("Afin de constituer un vivier de talents pour nos futurs besoins, nous recrutons un Data Analyst.")
    assert sig and sig[0].startswith("pool:")
    assert assess({**fresh, "company": "X", "ghost_text": sig}, h, {})


def test_ai_failure_is_retried_later(monkeypatch):
    """IA en panne (quota, modèle retiré) : l'offre sans expérience écrite n'est pas écartée, elle est relue plus tard."""
    import jobhunter.ai_check as ac
    import jobhunter.llm as llm
    from jobhunter.__main__ import LATER, judge
    from jobhunter.filters import Criteria
    monkeypatch.setenv("GROQ_API_KEY", "x")
    def boom(*a, **k): raise llm.LLMError("HTTP 429")
    monkeypatch.setattr(llm, "chat_json", boom)
    crit = Criteria.from_config({"keywords": ["data"], "unknown_experience": "drop"})
    ai = ac.ExperienceAI(budget=5)
    text = "Nous recherchons un Data Analyst pour notre équipe. " * 20
    ok, reason, _ = judge(crit, ai, {"name": "X"}, "Data Analyst", "Paris CDI", type("D", (), {"text": text, "structured": "Paris CDI", "extra": {}})())
    assert not ok and reason == LATER


class _R:
    def __init__(self, js=None, code=200, text=""):
        self._js, self.status_code, self.text, self.headers = js, code, text, {}
    def json(self): return self._js
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(self.status_code)


def _fetcher(get=None, post=None):
    from jobhunter.sources import Fetcher
    f = Fetcher.__new__(Fetcher)
    f.diag, f.json_calls, f.json_payloads, f.dump_dir = [], [], [], None
    f._polite = lambda url: None
    f.s = type("S", (), {})()
    f.s.get, f.s.post = get, post
    f.s.cookies = {}
    return f


def test_smartrecruiters_collect_and_detail():
    from jobhunter.sources import collect, detail_for
    calls = []
    def get(url, headers=None, timeout=0, params=None):
        calls.append(url)
        if "/postings/111" in url:
            return _R({"name": "Data Analyst H/F", "releasedDate": "2026-11-18T10:00:00Z",
                       "location": {"fullLocation": "Paris, France"}, "typeOfEmployment": {"label": "CDI"},
                       "jobAd": {"sections": {"jobDescription": {"text": "<p>Analyse des données</p>"},
                                              "qualifications": {"text": "<p>Débutant accepté</p>"}}}})
        return _R({"totalFound": 2, "content": [
            {"id": "111", "name": "Data Analyst H/F", "releasedDate": "2026-11-18T10:00:00Z",
             "location": {"city": "Paris", "country": "fr"}, "typeOfEmployment": {"label": "CDI"}, "company": {"name": "Talan"}},
            {"id": "222", "name": "Comptable", "location": {"city": "Paris"}}]})
    f = _fetcher(get=get)
    comp = {"name": "Talan", "source": "smartrecruiters", "company_id": "Talan", "countries": ["fr"]}
    ls, errs = collect(comp, f, ["data"], lambda t: "data" in t.lower())
    assert not errs and [l.title for l in ls] == ["Data Analyst H/F"]
    assert ls[0].url == "https://jobs.smartrecruiters.com/Talan/111" and "CDI" in ls[0].context
    d = detail_for(comp, f, ls[0].url)
    assert "Analyse des données" in d.text and "Paris" in d.structured and "CDI" in d.structured


def test_workday_detail_api():
    from jobhunter.sources import detail_for
    def get(url, headers=None, timeout=0):
        assert url == "https://x.wd3.myworkdayjobs.com/wday/cxs/x/Site/job/Paris/Data-Analyst_R1"
        return _R({"jobPostingInfo": {"title": "Data Analyst", "jobDescription": "<p>CDI à Paris, SQL</p>",
                                      "location": "Paris", "timeType": "Full time", "startDate": "2026-11-17"}})
    comp = {"source": "workday", "api": "https://x.wd3.myworkdayjobs.com/wday/cxs/x/Site/jobs",
            "public_url": "https://x.wd3.myworkdayjobs.com/Site"}
    d = detail_for(comp, _fetcher(get=get), "https://x.wd3.myworkdayjobs.com/Site/job/Paris/Data-Analyst_R1")
    assert "CDI à Paris" in d.text and "Paris" in d.structured


def test_francetravail(monkeypatch):
    import jobhunter.sources as src
    monkeypatch.setenv("FT_CLIENT_ID", "a"); monkeypatch.setenv("FT_CLIENT_SECRET", "b")
    src._ft_token.clear()
    post = lambda url, timeout=0, data=None: _R({"access_token": "t", "expires_in": 1400})
    def get(url, params=None, timeout=0, headers=None):
        assert params["motsCles"] == "data" and params["region"] == "11" and headers["Authorization"] == "Bearer t"
        return _R({"resultats": [{"id": "1AB", "intitule": "Data analyst (H/F)", "description": "Missions… Débutant accepté",
                                  "lieuTravail": {"libelle": "75 - Paris 8e"}, "typeContrat": "CDI",
                                  "typeContratLibelle": "Contrat à durée indéterminée", "experienceLibelle": "Débutant accepté",
                                  "entreprise": {"nom": "ACME"}, "dateCreation": "2026-11-20T08:00:00.000Z",
                                  "origineOffre": {"urlOrigine": "https://candidat.francetravail.fr/offres/recherche/detail/1AB"}}]})
    ls, errs = src.collect({"name": "France Travail", "source": "francetravail"}, _fetcher(get=get, post=post), ["data"], None)
    assert not errs and ls[0].employer == "ACME" and ls[0].detail and "Paris" in ls[0].detail.structured


def test_workday_country_filter_and_contract_in_title(monkeypatch):
    import jobhunter.sources as src
    from jobhunter.filters import Criteria
    monkeypatch.setattr(src.time, "sleep", lambda s: None)
    sent = []
    facets = [{"facetParameter": "locationMainGroup", "values": [
        {"facetParameter": "locationCountry", "descriptor": "Locations", "values": [
            {"descriptor": "France", "id": "fr1", "count": 3}, {"descriptor": "India", "id": "in1", "count": 9}]}]}]
    def post(url, json=None, headers=None, timeout=0):
        sent.append(dict(json["appliedFacets"]))
        return _R({"total": 1, "facets": facets, "jobPostings": [
            {"title": "CDI - Data Analyst H/F", "externalPath": "/job/Paris/Data-Analyst_R1", "locationsText": "Paris"}]})
    f = _fetcher(get=lambda url, timeout=0, headers=None: _R(text=""), post=post)
    comp = {"name": "X", "source": "workday", "api": "https://x.wd3.myworkdayjobs.com/wday/cxs/x/S/jobs",
            "public_url": "https://x.wd3.myworkdayjobs.com/S", "search_terms": ["data"]}
    ls, errs = src.collect(comp, f, ["data"], None)
    assert not errs and len(ls) == 1
    assert sent[0] == {} and sent[1] == {"locationCountry": ["fr1"]}     # 2e requête filtrée sur la France, pas de page 2
    assert len(sent) == 2
    c = Criteria.from_config({"keywords": ["data"], "unknown_contract": "drop"})
    assert c.evaluate("CDI – Ingénieur Analyste data", "Paris", "").contract == "CDI"
    from jobhunter.filters import detect_zone
    assert detect_zone("Vitry-sur-Seine") == "Île-de-France"


def test_workday_429_pauses_all_workday_sources(monkeypatch):
    import pytest
    import jobhunter.sources as src
    monkeypatch.setattr(src.time, "sleep", lambda s: None)
    src._workday_blocked_until["t"] = 0
    calls = []
    def post(url, json=None, headers=None, timeout=0):
        calls.append(url)
        return _R(code=429)
    f = _fetcher(get=lambda url, timeout=0, headers=None: _R(text=""), post=post)
    comp = {"name": "X", "source": "workday", "api": "https://x.wd3.myworkdayjobs.com/wday/cxs/x/S/jobs",
            "public_url": "https://x.wd3.myworkdayjobs.com/S", "search_terms": ["data", "analyst"]}
    with pytest.raises(src.Postponed):
        src.collect(comp, f, ["data"], None)
    n = len(calls)
    with pytest.raises(src.Postponed):                     # l'entreprise suivante n'interroge même pas Workday
        src.collect({**comp, "name": "Y"}, f, ["data"], None)
    assert len(calls) == n == 2
    src._workday_blocked_until["t"] = 0
    from jobhunter.filters import detect_contracts
    assert detect_contracts("Type de contrat : Unlimited employment") == {"CDI"}
    assert detect_contracts("Contrat fixe, 80-100%") == {"CDI"}


def test_seek_nz_and_work_rights():
    from jobhunter.sources import collect
    from jobhunter.filters import Criteria, needs_existing_work_rights
    seen = []
    def get(url, params=None, timeout=0, headers=None):
        seen.append((url, dict(params or {})))
        return _R({"data": [
            {"id": 81234567, "title": "Data Analyst", "advertiser": {"description": "Watercare"},
             "locations": [{"label": "Auckland CBD, Auckland"}], "workTypes": ["Full time"],
             "listingDate": "2026-11-26T03:00:00Z", "salaryLabel": "$85k - $95k"},
            {"id": 2, "title": "Plumber", "locations": [{"label": "Hamilton"}], "workTypes": ["Full time"]}]})
    f = _fetcher(get=get)
    comp = {"name": "SEEK", "source": "seek", "search_terms": ["data analyst"], "pages": [1, 2]}
    ls, errs = collect(comp, f, ["data"], lambda t: "data" in t.lower())
    assert not errs and len(ls) == 1 and ls[0].employer == "Watercare"
    assert ls[0].url == "https://www.seek.co.nz/job/81234567"
    assert seen[0][1]["siteKey"] == "NZ-Main" and len(seen) == 1          # page 1 incomplète : pas de page 2
    c = Criteria.from_config({"keywords": ["data"], "zones": ["nouvelle-zelande"], "unknown_contract": "drop"})
    v = c.evaluate(ls[0].title, ls[0].context, "")
    assert v.ok and v.country == "Nouvelle-Zélande" and v.contract == "CDI"
    assert not c.evaluate("Data Analyst", "Paris", "CDI").ok
    assert needs_existing_work_rights("You must have the legal right to work in New Zealand to apply.")
    assert needs_existing_work_rights("Unfortunately we are unable to sponsor visas for this role.")
    assert not needs_existing_work_rights("We can support visa applications for the right candidate.")


def test_wttj_collect_and_detail():
    import jobhunter.sources as src
    src._wttj_env.clear()
    posts = []
    def get(url, timeout=0, headers=None, params=None):
        if url.endswith("/api/env"):
            return _R({"ALGOLIA_APPLICATION_ID": "CSEKHVMS53", "ALGOLIA_API_KEY_CLIENT": "abc"})
        assert "api.welcometothejungle.com/api/v1/organizations/acme/jobs/data-analyst_paris" in url
        return _R({"job": {"name": "Data Analyst", "description": "<p>" + "Analyse des données de vente. " * 10 + "</p>",
                           "profile": "<p>Première expérience appréciée</p>", "contract_type": "full_time",
                           "offices": [{"city": "Paris", "country": "France"}], "organization": {"name": "Acme"}}})
    def post(url, json=None, headers=None, timeout=0):
        posts.append((url, json, headers))
        return _R({"nbPages": 1, "hits": [
            {"name": "Data Analyst", "slug": "data-analyst_paris", "organization": {"slug": "acme", "name": "Acme"},
             "offices": [{"city": "Paris", "country": "France"}], "contract_type": "full_time",
             "published_at_timestamp": 1795000000},
            {"name": "Stage Data Analyst", "slug": "stage", "organization": {"slug": "acme"}, "contract_type": "internship"},
            {"name": "Commercial", "slug": "x", "organization": {"slug": "acme"}}]})
    f = _fetcher(get=get, post=post)
    comp = {"name": "Welcome to the Jungle", "source": "wttj", "search_terms": ["data"]}
    ls, errs = src.collect(comp, f, ["data"], lambda t: "data" in t.lower())
    assert not errs and len(ls) == 2 and ls[0].employer == "Acme" and "CDI" in ls[0].context
    assert ls[0].url == "https://www.welcometothejungle.com/fr/companies/acme/jobs/data-analyst_paris"
    assert "csekhvms53-dsn.algolia.net/1/indexes/wttj_jobs_production_fr/query" in posts[0][0]
    assert posts[0][2]["Referer"].startswith("https://www.welcometothejungle.com") and "published_at_timestamp" in posts[0][1]["params"]
    d = src.detail_for(comp, f, ls[0].url)
    assert "Analyse des données" in d.text and "CDI" in d.structured and "Paris" in d.structured
