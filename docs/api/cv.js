// Fonction Vercel : CV adapté à UNE offre, à la demande (bouton « Générer mon CV » de cv.html).
// Protégée par le mot de passe du site (middleware.js). Mêmes variables que run.js (GH_TOKEN, GH_REPO).
//   POST /api/cv?id=<offre>&list=main|boards → lance le workflow cv.yml (1 appel IA)
//   GET  /api/cv?id=<offre>                  → le CV s'il est prêt (lu directement sur GitHub,
//                                              sans attendre le redéploiement du site), sinon l'état du workflow
const REPO = process.env.GH_REPO || "heykelh/jobhunter";
const WORKFLOW = "cv.yml";

async function gh(path, init = {}) {
  return fetch(`https://api.github.com/repos/${REPO}${path}`, {
    ...init,
    headers: { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               Authorization: `Bearer ${process.env.GH_TOKEN}`, "User-Agent": "jobhunter-site", ...(init.headers || {}) },
  });
}

async function runFor(id) {
  const r = await gh(`/actions/workflows/${WORKFLOW}/runs?per_page=20`);
  if (r.status === 404) throw new Error("Workflow cv.yml absent du dépôt : ajoute .github/workflows/cv.yml");
  if (!r.ok) throw new Error(`GitHub a répondu ${r.status} : vérifie le jeton GH_TOKEN`);
  const runs = (await r.json()).workflow_runs || [];
  const run = runs.find(x => (x.display_title || x.name || "") === `CV ${id}`);
  return run ? { id: run.id, status: run.status, conclusion: run.conclusion, created_at: run.created_at, url: run.html_url } : null;
}

async function readCV(id) {
  const r = await gh(`/contents/docs/data/cv/${id}.json?ref=main`, { headers: { Accept: "application/vnd.github.raw+json" } });
  if (!r.ok) return null;
  try { return JSON.parse(await r.text()); } catch { return null; }
}

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  const q = new URL(req.url, "http://x").searchParams;
  const id = (q.get("id") || "").trim();
  const list = q.get("list") === "boards" ? "boards" : "main";
  if (!/^[0-9a-f]{6,40}$/.test(id)) return res.status(400).json({ error: "Identifiant d'offre invalide" });
  if (!process.env.GH_TOKEN) {
    return res.status(503).json({ error: "Bouton pas encore configuré : ajoute la variable GH_TOKEN dans Vercel, puis redéploie." });
  }
  try {
    if (req.method === "POST") {
      const cur = await runFor(id);
      if (cur && cur.status !== "completed") return res.status(200).json({ started: false, run: cur });
      const r = await gh(`/actions/workflows/${WORKFLOW}/dispatches`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ref: "main", inputs: { id, list } }),
      });
      if (r.status !== 204) {
        const t = await r.text();
        return res.status(502).json({ error: `GitHub a refusé le lancement (${r.status}) : ${t.slice(0, 160)}` });
      }
      return res.status(202).json({ started: true });
    }
    const cv = await readCV(id);
    if (cv) return res.status(200).json({ cv });
    return res.status(200).json({ cv: null, run: await runFor(id) });
  } catch (e) {
    return res.status(502).json({ error: String(e.message || e).slice(0, 200) });
  }
}
