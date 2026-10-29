// Protection du site par mot de passe (Vercel Routing Middleware, gratuit).
// Le mot de passe se règle dans Vercel : Settings → Environment Variables → SITE_PASSWORD
// (et SITE_USER si tu veux un autre identifiant que "heykel"), puis "Redeploy".
// Fichiers d'installation de l'appli (sans donnée perso) : servis sans mot de passe,
// car le téléphone les télécharge sans transmettre l'identifiant.
const PUBLIC = new Set(["/manifest.webmanifest", "/sw.js", "/icon-192.png", "/icon-512.png",
                        "/icon-maskable-512.png", "/apple-touch-icon.png", "/favicon.ico", "/kanit.css"]);

export default function middleware(request) {
  const path = new URL(request.url).pathname;
  if (PUBLIC.has(path) || path.startsWith("/fonts/") || path.startsWith("/flags/")) return;
  const pass = process.env.SITE_PASSWORD;
  const user = process.env.SITE_USER || "heykel";
  if (!pass) {
    return new Response("Site verrouillé : ajoute la variable SITE_PASSWORD dans Vercel puis redéploie.",
      { status: 503, headers: { "content-type": "text/plain; charset=utf-8" } });
  }
  const auth = request.headers.get("authorization") || "";
  if (auth.startsWith("Basic ")) {
    try {
      const decoded = new TextDecoder().decode(Uint8Array.from(atob(auth.slice(6)), (c) => c.charCodeAt(0)));
      const i = decoded.indexOf(":");
      if (decoded.slice(0, i) === user && decoded.slice(i + 1) === pass) return; // accès accordé
    } catch (e) { /* en-tête invalide : on redemande */ }
  }
  return new Response("Accès réservé.", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="JobHunter", charset="UTF-8"',
               "content-type": "text/plain; charset=utf-8" },
  });
}
