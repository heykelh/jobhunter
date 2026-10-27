// Protection du site par mot de passe (Vercel Routing Middleware, gratuit).
// Le mot de passe se règle dans Vercel : Settings → Environment Variables → SITE_PASSWORD
// (et SITE_USER si tu veux un autre identifiant que "heykel"), puis "Redeploy".
export default function middleware(request) {
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
