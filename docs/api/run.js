// Fonction Vercel : lance le robot JobHunter (GitHub Actions) et renvoie son avancement.
// Protégée par le mot de passe du site (middleware.js).
// Variables à définir dans Vercel (Settings → Environment Variables) :
//   GH_TOKEN    jeton GitHub « fine-grained » limité au dépôt jobhunter, permission Actions : Read and write
//   NTFY_TOPIC  le même nom de topic ntfy que dans les secrets GitHub (pour lire l'avancement)
//   GH_REPO     facultatif, "heykelh/jobhunter" par défaut
const REPO = process.env.GH_REPO || "heykelh/jobhunter";
// ?w=boards → robot des sites d'emploi (APEC, HelloWork) ; sinon robot des sites carrière
const WORKFLOWS = { main: "jobhunter.yml", boards: "boards.yml" };

async function gh(path, init = {}) {
  const r = await fetch(`https://api.github.com/repos/${REPO}${path}`, {
    ...init,
    headers: { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               Authorization: `Bearer ${process.env.GH_TOKEN}`, "User-Agent": "jobhunter-site", ...(init.headers || {}) },
  });
  return r;
}

async function latestRun(WORKFLOW) {
  const r = await gh(`/actions/workflows/${WORKFLOW}/runs?per_page=5`);
  if (!r.ok) throw new Error(`GitHub a répondu ${r.status} : vérifie le jeton GH_TOKEN`);
  const runs = (await r.json()).workflow_runs || [];
  return runs[0] || null;
}

async function progressFor(runId) {
  const topic = (process.env.NTFY_TOPIC || "").trim();
  if (!topic || !runId) return [];
  const server = (process.env.NTFY_SERVER || "https://ntfy.sh").replace(/\/$/, "");
  try {
    const r = await fetch(`${server}/${encodeURIComponent(topic)}-live/json?poll=1&since=3h`);
    if (!r.ok) return [];
    const lines = (await r.text()).split("\n").filter(Boolean);
    const out = [];
    for (const l of lines) {
      try {
        const m = JSON.parse(l);
        if (m.event !== "message") continue;
        const ev = JSON.parse(m.message);
        if (String(ev.run) === String(runId)) out.push({ ...ev, at: m.time });
      } catch { /* message étranger : ignoré */ }
    }
    return out;
  } catch { return []; }
}

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  const w = new URL(req.url, "http://x").searchParams.get("w");
  const WORKFLOW = WORKFLOWS[w] || WORKFLOWS.main;
  if (!process.env.GH_TOKEN) {
    return res.status(503).json({ error: "Bouton pas encore configuré : ajoute la variable GH_TOKEN dans Vercel, puis redéploie." });
  }
  try {
    if (req.method === "POST") {
      const cur = await latestRun(WORKFLOW);
      if (cur && cur.status !== "completed") {
        return res.status(200).json({ started: false, reason: "Un passage est déjà en cours.", run: slim(cur) });
      }
      const r = await gh(`/actions/workflows/${WORKFLOW}/dispatches`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ref: "main", inputs: { mode: "run", only: "", progress: "1" } }),
      });
      if (r.status !== 204) {
        const t = await r.text();
        return res.status(502).json({ error: `GitHub a refusé le lancement (${r.status}) : ${t.slice(0, 160)}` });
      }
      return res.status(202).json({ started: true, requested_at: new Date().toISOString() });
    }
    const run = await latestRun(WORKFLOW);
    const events = run ? await progressFor(run.id) : [];
    return res.status(200).json({ run: run ? slim(run) : null, events });
  } catch (e) {
    return res.status(502).json({ error: String(e.message || e).slice(0, 200) });
  }
}

function slim(r) {
  return { id: r.id, status: r.status, conclusion: r.conclusion, event: r.event, created_at: r.created_at,
           updated_at: r.updated_at, run_started_at: r.run_started_at, url: r.html_url };
}
