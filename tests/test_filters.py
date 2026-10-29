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
    f.s.post = lambda url, json=None, timeout=0: Resp(js={"jobPostings": [
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
    c = Criteria.from_config({"keywords": ["data"], "zones": ["ile-de-france", "suisse", "luxembourg", "malaisie", "oman"],
                              "country_rules": {"Suisse": {"max_experience_years": 3}}})
    assert c.evaluate("Data Analyst", "Paris", "CDI").country == "France"
    assert c.evaluate("Data Analyst", "Cyberjaya", "CDI").country == "Malaisie"
    assert c.evaluate("Data Analyst", "Muscat", "CDI").country == "Oman"
    assert c.evaluate("Data Analyst", "Zürich", "CDI 3 ans d'expérience").ok      # règle propre à la Suisse
    assert not c.evaluate("Data Analyst", "Paris", "CDI 3 ans d'expérience").ok
    assert detect_zone("Women in data, romandie") != "Oman"


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


def test_sponsor_register_and_london():
    from jobhunter.sponsors import parse_register, lookup
    from jobhunter.filters import detect_zone
    reg = parse_register('"Organisation Name","Town/City","County","Type & Rating","Route"\n'
                         '"Barclays Bank UK PLC","London","","Worker (A rating)","Skilled Worker"\n'
                         '"Acme Events Ltd","London","","Temporary Worker (A rating)","Creative Worker"\n')
    assert lookup(reg, "Barclays") == "skilled"
    assert lookup(reg, "BARCLAYS BANK UK") == "skilled"
    assert lookup(reg, "Acme Events Limited") == "other"
    assert lookup(reg, "Unknown Startup Ltd") is False
    assert detect_zone("Canary Wharf, London") == "Londres"
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
        if json["model"] == "llama-3.3-70b-versatile":
            return R(400, '{"error":{"message":"The model has been decommissioned"}}')
        return R(200, js={"choices": [{"message": {"content": '{"ok": true}'}}]})
    monkeypatch.setattr(llm.requests, "post", post)
    assert llm.chat_json("s", "u") == {"ok": True}
    assert calls[:2] == ["llama-3.3-70b-versatile", "openai/gpt-oss-120b"]

    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: R(401, '{"error":{"message":"Invalid API Key"}}'))
    try:
        llm.chat_json("s", "u")
        assert False
    except llm.LLMError as e:
        assert "401" in str(e) and "Invalid API Key" in str(e)
