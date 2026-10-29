/* Construction du CV Word (.docx) à partir des données de l'éditeur.
   Fonctionne dans le navigateur (window.docx chargé depuis le CDN) et sous Node (require("docx")).
   Règles : Calibri, une colonne compatible ATS, dates alignées à droite par tabulation, aucun tiret long. */
(function (root) {
  "use strict";

  // Texte sans tiret long ni demi-cadratin (règle du CV), espaces conservés aux extrémités
  function inline(s) {
    return String(s == null ? "" : s)
      .replace(/ — /g, " : ").replace(/ – /g, " : ")
      .replace(/[—–‒]/g, "-")
      .replace(/ {2,}/g, " ");
  }
  function clean(s) { return inline(s).trim(); }

  function href(s) {
    s = clean(s);
    if (!s) return "";
    if (s.includes("@") && !s.startsWith("http")) return "mailto:" + s;
    return /^https?:\/\//.test(s) ? s : "https://" + s;
  }

  function buildDocument(cv, D) {
    const {
      Document, Paragraph, TextRun, ExternalHyperlink, TabStopType, AlignmentType,
      BorderStyle, LevelFormat,
    } = D;
    const pt = Number(cv.taille) || 10;            // taille du texte courant
    const SZ = Math.round(pt * 2);                 // demi-points
    const NAVY = "1F3864";
    const ACCENT = "2E75B6";
    const GAP = Math.round(Number(cv.espacement || 1) * 40);
    const PAGE_W = 11906, MARGIN_X = 794, MARGIN_Y = 680;
    const RIGHT = PAGE_W - 2 * MARGIN_X;

    const run = (text, o = {}) => new TextRun({ text: inline(text), font: "Calibri", size: o.size || SZ, ...o });
    const tab = () => new TextRun({ text: "\t", font: "Calibri", size: SZ });
    const link = (text, url, o = {}) => new ExternalHyperlink({
      link: href(url), children: [run(text, { color: ACCENT, ...o })],
    });

    const section = (title) => new Paragraph({
      spacing: { before: GAP * 3, after: GAP },
      border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: NAVY, space: 1 } },
      children: [run(title.toUpperCase(), { bold: true, color: NAVY, size: SZ + 2 })],
    });
    const header = (leftRuns, right) => new Paragraph({
      tabStops: [{ type: TabStopType.RIGHT, position: RIGHT }],
      spacing: { before: GAP, after: 0 },
      children: [...leftRuns, ...(right ? [tab(), run(clean(right), { color: "555555", size: SZ - 1 })] : [])],
    });
    const bullet = (text) => new Paragraph({
      numbering: { reference: "puces", level: 0 },
      spacing: { before: 0, after: Math.round(GAP / 2) },
      children: [run(text)],
    });

    const body = [];
    // En-tête
    body.push(new Paragraph({
      alignment: AlignmentType.CENTER, spacing: { after: 0 },
      children: [run(cv.nom || "", { bold: true, size: SZ + 18, color: NAVY })],
    }));
    if (cv.titre) {
      body.push(new Paragraph({
        alignment: AlignmentType.CENTER, spacing: { before: 20, after: 40 },
        children: [run(cv.titre, { bold: true, size: SZ + 6, color: ACCENT })],
      }));
    }
    const c = cv.contact || {};
    const contactParts = [];
    const pushSep = () => { if (contactParts.length) contactParts.push(new TextRun({ text: "   |   ", font: "Calibri", color: "888888", size: SZ - 1 })); };
    if (c.ville) { pushSep(); contactParts.push(run(c.ville, { size: SZ - 1 })); }
    if (c.telephone) { pushSep(); contactParts.push(run(c.telephone, { size: SZ - 1 })); }
    for (const k of ["email", "portfolio", "github", "linkedin"]) {
      if (c[k]) { pushSep(); contactParts.push(link(c[k], c[k], { size: SZ - 1 })); }
    }
    body.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: GAP }, children: contactParts }));

    // Profil
    if (cv.profil) {
      body.push(section("Profil"));
      body.push(new Paragraph({ alignment: AlignmentType.JUSTIFIED, spacing: { after: 0 }, children: [run(cv.profil)] }));
    }
    // Compétences
    const comps = (cv.competences || []).filter((g) => g.items && g.items.length);
    if (comps.length) {
      body.push(section("Compétences"));
      for (const g of comps) {
        body.push(new Paragraph({
          spacing: { after: Math.round(GAP / 2) },
          children: [run(clean(g.groupe) + " : ", { bold: true }), run(g.items.map(clean).join(", "))],
        }));
      }
    }
    // Projets
    const projets = (cv.projets || []).filter((p) => p.inclus !== false);
    if (projets.length) {
      body.push(section("Projets data (portfolio)"));
      for (const p of projets) {
        body.push(header([run(p.titre, { bold: true })], p.dates));
        if (p.lien) body.push(new Paragraph({ spacing: { after: 0 }, children: [link(clean(p.lien), p.lien, { size: SZ - 1 })] }));
        if (p.stack) body.push(new Paragraph({ spacing: { after: 20 }, children: [run(p.stack, { italics: true, color: "555555", size: SZ - 1 })] }));
        for (const b of p.puces || []) if (clean(b)) body.push(bullet(b));
      }
    }
    // Expérience
    const exps = (cv.experiences || []).filter((x) => x.inclus !== false);
    if (exps.length) {
      body.push(section("Expérience professionnelle"));
      for (const e of exps) {
        body.push(header([run(clean(e.titre), { bold: true }), run(e.entreprise ? ", " + clean(e.entreprise) : "")], e.dates));
        for (const b of e.puces || []) if (clean(b)) body.push(bullet(b));
      }
    }
    // Formation
    const forms = (cv.formations || []).filter((x) => x.inclus !== false);
    if (forms.length) {
      body.push(section("Formation"));
      for (const f of forms) {
        body.push(header([run(clean(f.titre), { bold: true }), run(f.ecole ? ", " + clean(f.ecole) : "")], f.dates));
      }
    }
    // Langues et atouts
    const extra = [cv.langues, cv.atouts].filter((x) => clean(x));
    if (extra.length) {
      body.push(section("Langues et atouts"));
      for (const x of extra) body.push(new Paragraph({ spacing: { after: Math.round(GAP / 2) }, children: [run(x)] }));
    }

    return new Document({
      creator: cv.nom || "",
      title: "CV " + (cv.nom || "") + (cv.entreprise ? " - " + cv.entreprise : ""),
      styles: { default: { document: { run: { font: "Calibri", size: SZ } } } },
      numbering: {
        config: [{
          reference: "puces",
          levels: [{
            level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 284, hanging: 200 } } },
          }],
        }],
      },
      sections: [{
        properties: { page: { size: { width: PAGE_W, height: 16838 }, margin: { top: MARGIN_Y, bottom: MARGIN_Y, left: MARGIN_X, right: MARGIN_X } } },
        children: body,
      }],
    });
  }

  function fileName(cv) {
    const slug = (s) => clean(s).normalize("NFD").replace(/[̀-ͯ]/g, "")
      .replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);
    return ["CV", slug(cv.nom || "CV"), slug(cv.entreprise || ""), slug(cv.titre || "")].filter(Boolean).join("_") + ".docx";
  }

  const api = { buildDocument, fileName, clean };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CvDocx = api;
})(typeof window !== "undefined" ? window : globalThis);
