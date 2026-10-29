/* CV en PDF (pdfmake), même structure que la version Word.
   Police Roboto (intégrée à pdfmake) : Calibri ne peut pas être embarquée librement. */
(function (root) {
  "use strict";
  const NAVY = "#1F3864", ACCENT = "#2E75B6", GREY = "#555555";

  function clean(s) {
    return String(s == null ? "" : s)
      .replace(/ — /g, " : ").replace(/ – /g, " : ")
      .replace(/[—–‒]/g, "-").replace(/ {2,}/g, " ").trim();
  }
  function href(s) {
    s = clean(s);
    if (!s) return undefined;
    if (s.includes("@") && !s.startsWith("http")) return "mailto:" + s;
    return /^https?:\/\//.test(s) ? s : "https://" + s;
  }

  function buildDefinition(cv) {
    // Roboto est ~8 % plus large que Calibri : on compense pour garder la même mise en page
    const pt = (Number(cv.taille) || 10) * 0.92;
    const g = Number(cv.espacement) || 1;
    const W = 595.28 - 2 * 40;                     // largeur utile A4 (marges 40 pt)
    const content = [];

    const section = (title) => {
      content.push({ text: clean(title).toUpperCase(), bold: true, color: NAVY, fontSize: pt + 1, margin: [0, 9 * g, 0, 1] });
      content.push({ canvas: [{ type: "line", x1: 0, y1: 0, x2: W, y2: 0, lineWidth: 0.7, lineColor: NAVY }], margin: [0, 0, 0, 3 * g] });
    };
    const line = (leftParts, right, rightLink) => ({
      columns: [
        { width: "*", text: leftParts },
        right ? { width: "auto", text: clean(right), alignment: "right", color: rightLink ? ACCENT : GREY,
                  fontSize: pt - 0.5, link: rightLink ? href(right) : undefined } : { width: 0, text: "" },
      ],
      columnGap: 8, margin: [0, 3 * g, 0, 0],
    });
    const bullets = (arr) => {
      const items = (arr || []).map(clean).filter(Boolean);
      if (items.length) content.push({ ul: items, margin: [6, 1, 0, 1 * g] });
    };

    // En-tête
    content.push({ text: clean(cv.nom), bold: true, fontSize: pt + 9, color: NAVY, alignment: "center" });
    if (cv.titre) content.push({ text: clean(cv.titre), bold: true, fontSize: pt + 3, color: ACCENT, alignment: "center", margin: [0, 1, 0, 2] });
    const c = cv.contact || {};
    const parts = [];
    const sep = () => { if (parts.length) parts.push({ text: "   |   ", color: "#888888" }); };
    if (c.ville) { sep(); parts.push({ text: clean(c.ville) }); }
    if (c.telephone) { sep(); parts.push({ text: clean(c.telephone) }); }
    for (const k of ["email", "portfolio", "github", "linkedin"]) {
      if (c[k]) { sep(); parts.push({ text: clean(c[k]), color: ACCENT, link: href(c[k]) }); }
    }
    content.push({ text: parts, alignment: "center", fontSize: pt - 0.5, margin: [0, 0, 0, 3 * g] });

    if (cv.profil) { section("Profil"); content.push({ text: clean(cv.profil), alignment: "justify" }); }

    const comps = (cv.competences || []).filter((x) => x.items && x.items.length);
    if (comps.length) {
      section("Compétences");
      for (const x of comps) {
        content.push({ text: [{ text: clean(x.groupe) + " : ", bold: true }, x.items.map(clean).join(", ")], margin: [0, 0, 0, 1.5 * g] });
      }
    }

    const projets = (cv.projets || []).filter((p) => p.inclus !== false);
    if (projets.length) {
      section("Projets data (portfolio)");
      for (const p of projets) {
        content.push(line([{ text: clean(p.titre), bold: true }], p.dates));
        if (p.lien) content.push({ text: clean(p.lien), link: href(p.lien), color: ACCENT, fontSize: pt - 0.5 });
        if (p.stack) content.push({ text: clean(p.stack), italics: true, color: GREY, fontSize: pt - 0.5 });
        bullets(p.puces);
      }
    }

    const exps = (cv.experiences || []).filter((x) => x.inclus !== false);
    if (exps.length) {
      section("Expérience professionnelle");
      for (const e of exps) {
        content.push(line([{ text: clean(e.titre), bold: true }, e.entreprise ? ", " + clean(e.entreprise) : ""], e.dates));
        bullets(e.puces);
      }
    }

    const forms = (cv.formations || []).filter((x) => x.inclus !== false);
    if (forms.length) {
      section("Formation");
      for (const f of forms) {
        content.push(line([{ text: clean(f.titre), bold: true }, f.ecole ? ", " + clean(f.ecole) : ""], f.dates));
      }
    }

    const extra = [cv.langues, cv.atouts].map(clean).filter(Boolean);
    if (extra.length) {
      section("Langues et atouts");
      for (const x of extra) content.push({ text: x, margin: [0, 0, 0, 1.5 * g] });
    }

    return {
      pageSize: "A4",
      pageMargins: [40, 34, 40, 34],
      info: { title: "CV " + clean(cv.nom) + (cv.entreprise ? " - " + clean(cv.entreprise) : ""), author: clean(cv.nom) },
      defaultStyle: { font: "Roboto", fontSize: pt, lineHeight: 1.06, color: "#111111" },
      content,
    };
  }

  const api = { buildDefinition, clean };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CvPdf = api;
})(typeof window !== "undefined" ? window : globalThis);
