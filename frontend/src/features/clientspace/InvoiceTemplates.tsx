// Modèles de facture .docx déposés par l'administrateur : par personne, groupe de personnes, société (intervenants externes)
// ou par défaut. La facture générée avec le CRA utilise le modèle le plus précis ; sans modèle, le modèle intégré.
import { useState } from "react";

import { API_BASE, api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { DocInfoPanel } from "../../components/DocInfoPanel";
import { useAction } from "../../components/ui";

type Tpl = { id: number; name: string; scope: string; scopeLabel: string; company: string; persons: { id: number; name: string }[];
  filename: string; size: number; uploadedBy: string; updatedAt: string; tags: string[] };
type Person = { id: number; name: string; company: string; external: boolean; dailyRate: string | null; template: string; rule: string };
type Data = { templates: Tpl[]; placeholders: { key: string; label: string }[]; people: Person[]; companies: string[]; scopes: { code: string; label: string }[] };
type Form = { id?: number; name: string; scope: string; persons: number[]; company: string; filename: string; content: string };

const base = `${API_BASE}/client-space/invoice-templates`;
const empty: Form = { name: "", scope: "default", persons: [], company: "", filename: "", content: "" };
const RULE: Record<string, string> = { personne: "modèle personnel", groupe: "modèle de groupe", "société": "modèle de la société", "défaut": "modèle par défaut", "intégré": "modèle intégré" };

export function InvoiceTemplates() {
  const r = useApi(() => api.get<Data>("/client-space/invoice-templates"));
  const { run, busy } = useAction();
  const [form, setForm] = useState<Form | null>(null);
  const [showTags, setShowTags] = useState(false);
  const [info, setInfo] = useState<string | null>(null);
  if (!r.data) return null;
  const d = r.data;
  const pick = (file: File | undefined) => {
    if (!file || !form) return;
    const fr = new FileReader();
    fr.onload = () => setForm({ ...form, filename: file.name, content: String(fr.result), name: form.name || file.name.replace(/\.docx$/i, "") });
    fr.readAsDataURL(file);
  };
  const save = () => {
    if (!form) return;
    const body = { name: form.name, scope: form.scope, persons: form.persons, company: form.company, ...(form.content ? { filename: form.filename, content: form.content } : {}) };
    void run(() => (form.id ? api.put(`/client-space/invoice-templates/${form.id}`, body) : api.post("/client-space/invoice-templates", body)),
      form.id ? "Modèle modifié" : "Modèle ajouté").then(() => { setForm(null); r.reload(); }, () => undefined);
  };
  const remove = (t: Tpl) => {
    if (!window.confirm(`Supprimer le modèle « ${t.name} » ? Les prochaines factures utiliseront le modèle suivant dans l'ordre de priorité.`)) return;
    void run(() => api.delete(`/client-space/invoice-templates/${t.id}`), "Modèle supprimé").then(() => r.reload(), () => undefined);
  };
  const target = (t: Tpl) => (t.scope === "company" ? t.company : t.scope === "default" ? "Tous les autres" : t.persons.map((p) => p.name).join(", "));
  const togglePerson = (id: number, on: boolean) => form && setForm({ ...form, persons: form.scope === "person" ? (on ? [id] : []) : on ? [...form.persons, id] : form.persons.filter((x) => x !== id) });
  return (
    <section className="cs-card cs-billing">
      <b>Modèles de facture</b>
      <p className="muted">
        Chaque CRA généré produit automatiquement une facture valorisée au TJM de la personne (TJM du projet s'il est renseigné, sinon TJM du profil).
        Le modèle utilisé est, dans l'ordre : celui de la <b>personne</b>, d'un <b>groupe</b> dont elle fait partie, de sa <b>société</b> de rattachement
        (intervenants externes), le modèle <b>par défaut</b>, puis le modèle intégré.
      </p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button type="button" className="btn primary" onClick={() => setForm({ ...empty })}>+ Ajouter un modèle</button>
        <a className="btn" href={`${base}/sample`}>Télécharger le modèle d'exemple (.docx)</a>
        <button type="button" className="btn" onClick={() => setShowTags((x) => !x)}>{showTags ? "Masquer" : "Voir"} les balises</button>
      </div>
      {showTags && (
        <div className="cs-tags">
          <p className="muted">Écrivez ces balises dans votre document Word ; {"{{lignes}}"} et {"{{totaux}}"} doivent être seules dans leur paragraphe.</p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: "4px 16px" }}>
            {d.placeholders.map((p) => <span key={p.key}><code>{`{{${p.key}}}`}</code> <span className="muted">{p.label}</span></span>)}
          </div>
        </div>
      )}
      {form && (
        <div className="cs-card" style={{ background: "var(--surface-2, #f8fafc)" }}>
          <div className="cs-grid">
            <label><span>Nom</span><input className="inp" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <label><span>Appliquer à</span>
              <select className="inp" value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value, persons: e.target.value === "person" ? form.persons.slice(0, 1) : form.persons })}>
                {d.scopes.map((s) => <option key={s.code} value={s.code}>{s.label}</option>)}
              </select>
            </label>
            {form.scope === "company" && (
              <label><span>Société</span>
                <input className="inp" list="it-companies" value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} placeholder="Nom de la société" />
                <datalist id="it-companies">{d.companies.map((c) => <option key={c} value={c} />)}</datalist>
              </label>
            )}
            <label><span>Fichier Word (.docx){form.id ? " — facultatif" : ""}</span>
              <input className="inp" type="file" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(e) => pick(e.target.files?.[0])} />
            </label>
          </div>
          {(form.scope === "person" || form.scope === "group") && (
            <div>
              <span className="muted">{form.scope === "person" ? "Personne" : "Personnes du groupe"}</span>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 14px", maxHeight: 160, overflow: "auto" }}>
                {d.people.map((p) => (
                  <label key={p.id} className="cs-check">
                    <input type={form.scope === "person" ? "radio" : "checkbox"} name="it-person" checked={form.persons.includes(p.id)} onChange={(e) => togglePerson(p.id, e.target.checked)} />
                    {p.name}{p.company ? <span className="muted"> · {p.company}</span> : null}
                  </label>
                ))}
              </div>
            </div>
          )}
          {form.scope === "company" && form.company && (
            <p className="muted">Membres concernés : {d.people.filter((p) => p.company.toLowerCase() === form.company.trim().toLowerCase()).map((p) => p.name).join(", ") || "aucun pour l'instant (renseignez la société dans le profil des utilisateurs)"}</p>
          )}
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" className="btn primary" disabled={busy} onClick={save}>Enregistrer</button>
            <button type="button" className="btn" onClick={() => setForm(null)}>Annuler</button>
          </div>
        </div>
      )}
      {d.templates.length === 0 ? <p className="muted">Aucun modèle déposé : les factures utilisent le modèle intégré.</p> : (
        <table className="cs-table">
          <thead><tr><th>Modèle</th><th>Portée</th><th>Cible</th><th>Fichier</th><th>Balises</th><th /></tr></thead>
          <tbody>
            {d.templates.map((t) => (
              <tr key={t.id}>
                <td><b>{t.name}</b><div className="muted" style={{ fontSize: 12 }}>{t.uploadedBy} · {new Date(t.updatedAt).toLocaleDateString("fr-FR")}</div></td>
                <td>{t.scopeLabel}</td>
                <td>{target(t)}</td>
                <td><a href={`${base}/${t.id}`}>{t.filename}</a></td>
                <td style={{ fontSize: 12 }}>{t.tags.length ? `${t.tags.length} balise(s)` : <span style={{ color: "#b45309" }}>aucune balise</span>}</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <a className="btn sm" href={`${base}/${t.id}?preview=${t.persons[0]?.id ?? d.people.find((p) => t.scope === "company" && p.company.toLowerCase() === t.company.toLowerCase())?.id ?? d.people[0]?.id ?? ""}`}>Aperçu</a>{" "}
                  <button type="button" className="btn sm" onClick={() => setForm({ id: t.id, name: t.name, scope: t.scope, persons: t.persons.map((p) => p.id), company: t.company, filename: "", content: "" })}>Modifier</button>{" "}
                  <button type="button" className="btn sm danger" disabled={busy} onClick={() => remove(t)}>Supprimer</button>{" "}
                  <button type="button" className="btn sm" title={`Historique · TPL-${String(t.id).padStart(6, "0")}`} onClick={() => setInfo(`template:${t.id}`)}>ℹ️</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {info && <DocInfoPanel docRef={info} onClose={() => setInfo(null)} />}
      <details>
        <summary>Modèle appliqué à chaque personne ({d.people.length})</summary>
        <table className="cs-table">
          <thead><tr><th>Personne</th><th>Société</th><th>TJM profil</th><th>Modèle de facture</th></tr></thead>
          <tbody>
            {d.people.map((p) => (
              <tr key={p.id}>
                <td>{p.name}{p.external ? <span className="muted"> · externe</span> : null}</td>
                <td>{p.company || "—"}</td>
                <td>{p.dailyRate ? `${Number(p.dailyRate).toLocaleString("fr-FR")} €` : "—"}</td>
                <td>{p.template} <span className="muted">({RULE[p.rule] ?? p.rule})</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}
