// Projet › Informations : récapitulatif hebdomadaire par e-mail, paramétré par le chef de projet.
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { Card, Modal, useAction } from "../../components/ui";

type Conf = { enabled: boolean; weekday: number; hour: number; audience: Record<string, boolean>; emails: string[]; sections: Record<string, boolean>;
  canEdit: boolean; days: string[]; recipients: string[]; emailActive: boolean; lastSent?: string };
const AUD: [string, string][] = [["pm", "Chef de projet"], ["team", "Équipe projet"], ["client", "Client (comptes du client)"]];
const SEC: [string, string][] = [["done", "Actions terminées"], ["late", "Actions en retard"], ["upcoming", "Échéances à 7 jours"], ["hours", "Temps saisi"],
  ["validations", "Saisies en attente de validation"], ["budget", "Budget consommé"]];

export function WeeklyRecapCard({ projectId }: { projectId: string }) {
  const r = useApi(() => api.get<Conf>(`/projects/${encodeURIComponent(projectId)}/weekly-recap`), [projectId]);
  const { run, busy } = useAction();
  const [c, setC] = useState<Conf | null>(null);
  const [emails, setEmails] = useState("");
  const [preview, setPreview] = useState<{ title: string; html: string; recipients: string[] } | null>(null);
  useEffect(() => { if (r.data) { setC(r.data); setEmails(r.data.emails.join(", ")); } }, [r.data]);
  if (!c) return null;
  const ro = !c.canEdit;
  const save = () => void run(() => api.put(`/projects/${encodeURIComponent(projectId)}/weekly-recap`, { ...c, emails }), "Récap hebdomadaire enregistré").then(() => r.reload(), () => undefined);
  const sendNow = () => window.confirm("Envoyer le récap de la semaine maintenant aux destinataires ?")
    && void run(() => api.post(`/projects/${encodeURIComponent(projectId)}/weekly-recap/send`, {}), "Récap envoyé").then(() => r.reload(), () => undefined);
  const showPreview = () => void run(() => api.post<{ title: string; html: string; recipients: string[] }>(`/projects/${encodeURIComponent(projectId)}/weekly-recap/send`, { preview: true }))
    .then((p) => p && setPreview(p), () => undefined);
  return (
    <Card title="📧 Récap hebdomadaire par e-mail" sub="Synthèse de la semaine envoyée automatiquement au créneau choisi. Paramétrée par le chef de projet.">
      {!c.emailActive && <p className="notice">L'envoi e-mail de l'entreprise est désactivé : le récap arrive seulement dans la cloche de l'application.</p>}
      <fieldset disabled={ro || busy} style={{ border: 0, padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 10 }}>
        <label className="vb-check"><input type="checkbox" checked={c.enabled} onChange={(e) => setC({ ...c, enabled: e.target.checked })} /> <b>Envoyer le récap chaque semaine</b></label>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span>Le</span>
          <select className="inp" style={{ width: "auto" }} value={c.weekday} onChange={(e) => setC({ ...c, weekday: Number(e.target.value) })}>{c.days.map((d, i) => <option key={d} value={i}>{d}</option>)}</select>
          <span>à</span>
          <select className="inp" style={{ width: "auto" }} value={c.hour} onChange={(e) => setC({ ...c, hour: Number(e.target.value) })}>{Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{h} h</option>)}</select>
        </div>
        <div><span className="muted" style={{ fontSize: 12 }}>Destinataires</span>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>{AUD.map(([k, l]) => <label key={k} className="vb-check"><input type="checkbox" checked={!!c.audience[k]} onChange={(e) => setC({ ...c, audience: { ...c.audience, [k]: e.target.checked } })} /> {l}</label>)}</div>
          <input className="inp" style={{ marginTop: 6 }} placeholder="Autres adresses e-mail (séparées par des virgules)" value={emails} onChange={(e) => setEmails(e.target.value)} />
        </div>
        <div><span className="muted" style={{ fontSize: 12 }}>Contenu</span>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>{SEC.map(([k, l]) => <label key={k} className="vb-check"><input type="checkbox" checked={!!c.sections[k]} onChange={(e) => setC({ ...c, sections: { ...c.sections, [k]: e.target.checked } })} /> {l}</label>)}</div>
        </div>
      </fieldset>
      <p className="muted" style={{ fontSize: 12 }}>Destinataires actuels : {c.recipients.join(", ") || "aucun"}{c.lastSent ? ` · dernier envoi automatique : ${c.lastSent}` : ""}</p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {!ro && <button type="button" className="btn primary sm" disabled={busy} onClick={save}>Enregistrer</button>}
        {!ro && <button type="button" className="btn sm" disabled={busy} onClick={showPreview}>👁️ Aperçu</button>}
        {!ro && <button type="button" className="btn sm" disabled={busy} onClick={sendNow}>Envoyer maintenant</button>}
        {ro && <span className="muted" style={{ fontSize: 12 }}>Lecture seule : seul le chef de projet (ou l'administrateur) modifie ce réglage.</span>}
      </div>
      {preview && (
        <Modal wide title={preview.title} onClose={() => setPreview(null)} footer={<button type="button" className="btn primary" onClick={() => setPreview(null)}>Fermer</button>}>
          <p className="muted" style={{ fontSize: 12 }}>Destinataires : {preview.recipients.join(", ") || "aucun"}</p>
          <iframe title="Aperçu du récap" sandbox="" srcDoc={preview.html} style={{ width: "100%", height: "65vh", border: "1px solid var(--line, #e2e8f0)", borderRadius: 8 }} />
        </Modal>
      )}
    </Card>
  );
}
