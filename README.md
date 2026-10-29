# JobHunter

Veille automatique des offres d'emploi **directement sur les sites carrière** d'une trentaine d'entreprises (France, Suisse, Luxembourg, Malaisie, Oman).
Les offres qui correspondent aux critères arrivent sur un site privé et en notification **ntfy** sur le téléphone, avec un **CV adapté à chaque offre** (modifiable, téléchargeable en Word et en PDF).

- Robot : **GitHub Actions**, plusieurs passages par jour de 6 h à minuit (heure de Paris)
- Site : **Vercel**, protégé par mot de passe
- Notifications : **ntfy**
- CV : adaptation par règles et reformulation par IA (**Groq**, gratuit)
- Coût : 0 €

---

## Sommaire

1. [Comment ça marche](#1-comment-ça-marche)
2. [Le tri des offres](#2-le-tri-des-offres)
3. [Utiliser le site](#3-utiliser-le-site)
4. [Modifier les critères](#4-modifier-les-critères)
5. [Ajouter une entreprise](#5-ajouter-une-entreprise)
6. [Vérifier que tout tourne](#6-vérifier-que-tout-tourne)
7. [Installation (depuis zéro)](#7-installation-depuis-zéro)
8. [Organisation du code](#8-organisation-du-code)
9. [Confidentialité](#9-confidentialité)
10. [Dépannage](#10-dépannage)

---

## 1. Comment ça marche

```
GitHub Actions (toutes les 30 min, en pratique 5 à 7 passages par jour)
   │
   ├─ 1. lit la liste des offres de chaque entreprise (RSS, API, page web, navigateur Chromium)
   ├─ 2. garde les titres avec un mot-clé (data, analyst…) et sans mot exclu (senior, stage…)
   ├─ 3. ouvre chaque nouvelle fiche : lieu → pays, contrat, expérience demandée
   ├─ 4. fait relire l'expérience par l'IA, qui doit citer la phrase exacte de la fiche
   ├─ 5. génère un CV adapté à l'offre
   ├─ 6. envoie une notif ntfy (drapeau du pays + lien)
   └─ 7. enregistre tout dans docs/data/ (commit "Offres …")
                    │
                    ▼
      Vercel publie docs/ → site JobHunter (mot de passe)
```

Au **premier passage** pour une entreprise, les offres déjà en ligne sont ajoutées au site **sans notification**, pour éviter une rafale. Ensuite, chaque nouvelle offre retenue déclenche une notif.

Un passage s'arrête de lui-même après 38 minutes (`time_budget_minutes`). Le passage suivant reprend là où il s'était arrêté, pour que les dernières entreprises de la liste ne soient jamais oubliées.

---

## 2. Le tri des offres

Une offre est retenue seulement si elle passe **toutes** les étapes. Sinon, elle est rangée dans l'onglet **Écartées** du site, avec la raison.

| Étape | Règle | Exemple de rejet |
|---|---|---|
| Titre | contient un mot-clé (`keywords`) | « Mécanicien avion » |
| Titre | ne contient aucun mot exclu (`exclude_title`) | « Senior Data Analyst », « Stage… », « Team Leader… », « …Datacenter » |
| Lieu | Île-de-France, Suisse, Luxembourg, Londres, Malaisie ou Oman | « Data Analyst, Lyon » |
| Salaire (Londres) | salaire maximum affiché ≥ 41 700 £, le minimum du visa Skilled Worker | « Data Analyst, £30 000 - £35 000 » |
| Contrat | CDI ou CDD | « Alternance », « VIE » |
| Expérience | 2 ans maximum (`max_experience_years`) | « Niveau d'expérience : 3 - 5 ans » |
| IA | relit l'expérience sur la fiche | « vous justifiez d'une expérience réussie de plusieurs années… » |

### La lecture de l'expérience est volontairement stricte

1. Un **champ étiqueté** de la fiche passe avant tout : « Niveau minimum d'expérience : 3 - 5 ans », « Experience level: Mid-Senior », « Niveau : Confirmé ».
2. Si la fiche cite **plusieurs durées**, c'est la **plus exigeante** qui compte. Une offre qui dit « première expérience » puis « 5 ans en gestion de projet » est écartée.
3. Les formules sans chiffre (« solide expérience », « plusieurs années », « several years », « mehrjährige Erfahrung ») valent **3 ans**.
4. Les nombres écrits en lettres sont compris (« trois ans », « three years », « drei Jahre »).
5. L'ancienneté de l'entreprise (« fort de 40 ans d'expérience ») est ignorée.
6. Exception : un titre qui contient « Junior » ou « Jeune diplômé » passe quand même.

Ensuite, **l'IA relit chaque fiche retenue** (40 au maximum par passage). Elle doit recopier la phrase exacte de l'offre qui justifie sa réponse. Si cette phrase n'existe pas dans la fiche, son avis est ignoré. Le rejet affiche la citation, par exemple :
`expérience demandée ≥ 3 ans (lu par l'IA) « 3 à 5 ans d'expérience sur un poste similaire »`.

Quand les règles changent (constante `RULES_VERSION` dans `jobhunter/__main__.py`), les offres **déjà affichées sont revérifiées** : le robot rouvre leur fiche, 12 par entreprise et par passage, et retire celles qui ne passent plus.

### Catégories par pays

Chaque offre est rangée dans un pays : 🇫🇷 France, 🇨🇭 Suisse, 🇱🇺 Luxembourg, 🇬🇧 Royaume-Uni (Londres), 🇲🇾 Malaisie, 🇴🇲 Oman. Le pays apparaît en boutons sur le site et en drapeau dans les notifs.

### Londres et le visa

Pour chaque offre à Londres, le robot cherche l'employeur dans le [registre officiel des sponsors de visa](https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers), téléchargé à chaque passage. La carte et la notif affichent :
- ✅ sponsor visa : l'employeur peut sponsoriser un visa Skilled Worker ;
- ⚠ sponsor (autre visa) : il a une licence, mais pas pour le Skilled Worker ;
- ⛔ pas sponsor de visa : il est absent du registre.

Avec `require_sponsor: true` dans `country_rules`, les employeurs non sponsors sont écartés.
Pour assouplir les règles dans un seul pays, utilise `country_rules` dans `config.yaml` :

```yaml
country_rules:
  Suisse:
    max_experience_years: 3
```

---

## 3. Utiliser le site

Adresse : https://jobhunter-docs.vercel.app/. Le navigateur demande l'identifiant et le mot de passe (voir [§ 9](#9-confidentialité)).

- **En haut** : ce qui est arrivé **depuis ta dernière visite** (une visite = une session ; après 30 min d'absence, la suivante commence), puis 4 compteurs : offres en ligne, nouvelles depuis ta visite, candidatures en cours, candidatures à relancer.
- **Offres** : boutons par pays, recherche, filtre par entreprise, tri « Plus récentes » ou « Meilleure correspondance », « Nouvelles », « Masquer suivies ».
- Chaque carte affiche :
  - le **score de correspondance** 🎯 : la part des compétences demandées dans la fiche que l'on retrouve dans ton CV de base (vert ≥ 70 %, orange 40-69 %, rouge < 40 %). En dépliant « Compétences demandées », tu vois celles que tu as (✓) et celles qui manquent (✗) ;
  - la date de publication sur le site d'origine et la date de récupération ;
  - le lieu, le contrat et l'expérience ;
  - les boutons **Voir et postuler**, **Mon CV pour cette offre**, le menu **Suivi** et **Masquer**.
- **Mes candidatures** : les étapes À postuler → Postulé → Entretien → Refus / Offre, avec la date d'envoi (J+n), une note libre et le bouton **J'ai relancé**. Une candidature passe **⏰ À relancer** 7 jours après l'envoi ou après la dernière relance. Ce suivi est enregistré **sur l'appareil** (il n'est pas partagé entre ton PC et ton téléphone).
- **Écartées** : les offres rejetées et la raison. Utile pour vérifier que le tri ne jette rien de bon.
- **Sources** : l'état de chaque entreprise (ok / vide / erreur), le nombre de liens trouvés et le dernier succès.

### Installer le site comme une appli

- **Android (Chrome)** : bouton **📲 Installer l'appli** en haut de la page, ou menu ⋮ → *Installer l'application*.
- **iPhone (Safari)** : bouton *Partager* → *Sur l'écran d'accueil* (un bandeau le rappelle).

L'icône JobHunter apparaît sur l'écran d'accueil et le site s'ouvre en plein écran.

### Le CV par offre

`cv.html?id=…` ouvre un éditeur avec un aperçu A4. Tout est modifiable et les changements restent enregistrés sur ton appareil. Deux boutons : **Télécharger en Word** et **Télécharger en PDF**.
Le CV de base est dans `cv/base_cv.json`. Le téléphone et l'email ne sont **pas** dans le dépôt : saisis-les une fois dans l'éditeur, ils sont gardés sur ton appareil.

---

## 4. Modifier les critères

Tout se règle dans **`config.yaml`**. Tu peux le modifier directement sur GitHub (icône crayon, puis *Commit*). Le passage suivant en tient compte.

| Réglage | Rôle |
|---|---|
| `keywords` | mots dont le titre doit contenir au moins un (ex. `data`, `analyst`, `daten`) |
| `exclude_title` | mots qui écartent un titre d'office |
| `contracts` | `[CDI, CDD]` |
| `max_experience_years` | expérience maximum demandée (2) |
| `zones` | `ile-de-france`, `luxembourg`, `suisse`, `malaisie`, `oman` |
| `country_rules` | réglages propres à un pays |
| `unknown_contract` / `unknown_experience` / `unknown_location` | `keep` ou `drop` quand l'info manque |
| `experience_ai`, `experience_ai_per_run` | contrôle IA de l'expérience |
| `notify.max_per_run` | au-delà, une seule notif récapitulative |
| `cv_enabled`, `cv_per_run` | génération des CV |
| `time_budget_minutes` | durée maximum d'un passage |
| `match_backfill_per_company` | offres déjà affichées dont le score est calculé par passage (8) |

---

## 5. Ajouter une entreprise

1. Copie un bloc dans `companies:` de `config.yaml`, en choisissant le type de site le plus proche :

| `source` | Pour quel site | Exemple déjà en place |
|---|---|---|
| `rss` | flux RSS (le plus fiable) | Air France, Bouygues Telecom |
| `reed` | API officielle de Reed.co.uk (clé `REED_API_KEY`) | Reed (Londres) |
| `workday` | sites `*.myworkdayjobs.com` | Eiffage, Julius Baer |
| `json` | API JSON publique | AXA |
| `sequence` | fiches à numéro croissant | EDF / Enedis |
| `html` | page de résultats ; `render: true` si le site est en JavaScript | SNCF, VINCI, L'Oréal… |

Options utiles pour `html` :
- `{q}` dans l'URL est remplacé par chaque mot-clé, `{page}` par `pages`, `{offset}` par `offsets` ;
- `link_pattern` est le morceau d'URL propre aux fiches (ex. `/job/`) ;
- `default_location` sert de lieu si la fiche n'en donne pas ;
- `enabled: false` désactive une entreprise sans supprimer son bloc ;
- `aggregator: true` pour un site d'annonces (jobs.ch, jobup.ch, Reed) : la carte affiche le vrai employeur (« via jobs.ch »), et une annonce déjà vue ailleurs n'est pas ajoutée deux fois.

2. Lance le workflow en mode **diagnose** (voir § 6), avec le nom de l'entreprise dans *only*. Le log montre les liens et les titres trouvés.
3. Si rien ne remonte, envoie le log à Claude pour ajuster l'URL ou le `link_pattern`.

---

## 6. Vérifier que tout tourne

- **GitHub → Actions → JobHunter** : un passage vert toutes les 30 min environ. En pratique, GitHub en saute beaucoup et il en reste 5 à 7 par jour.
- **Lancer à la main** : *Run workflow*, puis `mode` :
  - `run` = veille normale ;
  - `diagnose` = test des sources sans notif ni enregistrement d'offres (résultat dans `docs/data/diagnose.json`).
- **Commits « Offres … »** du bot dans l'historique : chaque passage qui trouve du nouveau en crée un.
- **Onglet Sources** du site : une entreprise en *erreur* ou *vide* plusieurs fois de suite a sans doute changé son site. Une notif « ⚠ Source en panne » part après 6 échecs.

### Mettre à jour le code depuis ton PC (PowerShell)

```powershell
git add -A
git commit -m "message"
git pull --rebase
git push
```

Le bot commite souvent : il faut donc **commiter avant** le `pull --rebase`. En cas de conflit dans `docs/data` ou `state`, garde la version du bot :

```powershell
git checkout --ours docs/data state
git add docs/data state
git rebase --continue
git push
```

---

## 7. Installation (depuis zéro)

1. **ntfy** : installe l'app et abonne-toi à un topic difficile à deviner.
2. **GitHub** : dépôt `jobhunter` contenant ce dossier.
   Dans *Settings → Secrets and variables → Actions*, ajoute :
   - `NTFY_TOPIC` : le nom du topic (obligatoire) ;
   - `GROQ_API_KEY` : clé gratuite sur console.groq.com, pour les CV reformulés et le contrôle IA de l'expérience (recommandé) ;
   - `REED_API_KEY` : clé gratuite du portail développeur de Reed.co.uk, pour les offres à Londres (facultatif) ;
   - `NTFY_TOKEN` : facultatif, seulement pour un serveur ntfy protégé.
3. **Actions** : onglet Actions, activer les workflows, puis *Run workflow* une première fois.
4. **Vercel** : *Add New Project* et importer le dépôt, avec :
   - Root Directory : `docs` ;
   - Framework : **Other** ;
   - Build et Install Command : vides.
5. **Mot de passe du site** : dans Vercel, *Settings → Environment Variables* :
   - `SITE_PASSWORD` : ton mot de passe ;
   - `SITE_USER` : facultatif, `heykel` par défaut.

   Puis *Deployments → … → Redeploy*.
6. **Test local** (facultatif) :
   ```powershell
   pip install requests beautifulsoup4 lxml PyYAML pytest
   python -m pytest -q
   ```

---

## 8. Organisation du code

```
jobhunter/                     ← racine du dépôt
├─ config.yaml                 critères + liste des entreprises
├─ requirements.txt
├─ .github/workflows/jobhunter.yml   planification et commit des résultats
├─ jobhunter/                  le robot (Python)
│  ├─ __main__.py              déroulé d'un passage (tri, revérification, CV, notifs)
│  ├─ sources.py               lecture des sites : RSS, HTML, JSON, Workday, navigateur, fiches
│  ├─ filters.py               mots-clés, contrat, expérience, lieu → pays
│  ├─ ai_check.py              contrôle IA de l'expérience (avec citation vérifiée)
│  ├─ match.py                 score de correspondance offre / CV
│  ├─ sponsors.py              registre britannique des sponsors de visa
│  ├─ llm.py                   appel à l'IA Groq (erreur exacte affichée, modèle de secours)
│  ├─ cv.py                    CV adapté à chaque offre
│  ├─ notify.py                notifications ntfy
│  └─ store.py                 fichiers JSON (offres, écartées, état des sources)
├─ cv/base_cv.json             CV de référence (sans téléphone ni email)
├─ docs/                       le site publié par Vercel
│  ├─ index.html               liste des offres
│  ├─ cv.html, cv-docx.js, cv-pdf.js   éditeur et export du CV
│  ├─ middleware.js, package.json      mot de passe du site
│  ├─ manifest.webmanifest, sw.js, icon-*.png, apple-touch-icon.png   appli installable
│  ├─ kanit.css                police Kanit intégrée (licence SIL OFL) ; les drapeaux sont intégrés à index.html
│  └─ data/                    écrit par le robot : jobs.json, rejected.json, health.json, cv/…
├─ state/state.json            mémoire du robot (entreprises déjà initialisées, curseurs)
└─ tests/test_filters.py       tests des filtres (python -m pytest -q)
```

---

## 9. Confidentialité

- **Le site** est protégé par mot de passe (`docs/middleware.js`, variable `SITE_PASSWORD` dans Vercel). Sans la variable, le site affiche « Site verrouillé » au lieu de s'ouvrir.
- **Le dépôt GitHub** : s'il est public, les fichiers `docs/data/` (offres et CV générés) restent lisibles sur GitHub, même avec le site protégé. Pour tout cacher, passe le dépôt en **privé** (*Settings → General → Danger Zone → Change visibility*). Vercel continue de fonctionner avec un dépôt privé.
  - Attention : en privé, GitHub Actions est limité à **2 000 minutes par mois** gratuites. Vérifie la durée moyenne d'un passage dans l'onglet Actions. Il faut que *durée × passages par jour × 30* reste sous 2 000. Sinon, espace les passages dans le `cron` du workflow (ex. `"7 6-20/2 * * *"` = toutes les 2 h).
- Le topic ntfy est dans les **secrets** GitHub, jamais dans le code.
- Le téléphone et l'email du CV ne sont jamais envoyés sur GitHub.

---

## 10. Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| `git push` refusé (*fetch first*) | le bot a commité entre-temps | `git pull --rebase` puis `git push` |
| *cannot pull with rebase: You have unstaged changes* | modifs pas encore commitées | commiter d'abord (voir § 6) |
| Une entreprise reste à 0 offre | site modifié ou bloqué | mode `diagnose`, puis ajuster l'URL ou le `link_pattern` |
| Offre retenue alors qu'elle demande trop d'expérience | formulation non reconnue | envoyer l'URL de l'offre à Claude pour ajouter la formule |
| Bonne offre dans « Écartées » | règle trop stricte | lire la raison et la citation, puis ajuster `exclude_title`, `max_experience_years` ou `country_rules` |
| Page « Site verrouillé » | `SITE_PASSWORD` absent | l'ajouter dans Vercel puis *Redeploy* |
| Peu de passages par jour | limitation de GitHub sur les tâches planifiées | normal ; *Run workflow* à la main si besoin |
| Passage coupé (*timeout*) | trop d'entreprises lentes | le robot reprend au même endroit ; baisser `max_details_per_company` si ça se répète |
