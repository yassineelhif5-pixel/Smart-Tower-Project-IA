// Pilote : reporting des contrats des entreprises clientes (échéances) et relance par e-mail.
import { useState } from "react";

import { api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Loading, Modal, Pill, useAction } from "../../components/ui";

type Row = {
  tenant: number; name: string; slug: string; tenantStatus: string; contact: string; contactEmail: string; recipients: string[];
  contract: string | null; contractStatus: string | null; offer: string | null; subscriptionStatus: string;
  start: string | null; end: string | null; trialEnd: string | null; daysLeft: number | null;
  state: "expired" | "soon" | "watch" | "ok" | "open"; stateLabel: string;
  lastReminder: { at: string; detail: string } | null; subject: string; message: string;
};
type Data = { rows: Row[]; counts: Record<string, number>; smtp: boolean };

const TONE: Record<Row["state"], "crit" | "warn" | "info" | "ok" | ""> = { expired: "crit", soon: "warn", watch: "info", ok: "ok", open: "" };
const fr = (d: string | null) => (d ? new Date(`${d.slice(0, 10)}T00:00:00`).toLocaleDateString("fr-FR") : "—");

export function ContractsTab() {
  const r = useApi(() => api.get<Data>("/platform/contracts"));
  const [filter, setFilter] = useState<"" | Row["state"]>("");
  const [q, setQ] = useState("");
  const [mail, setMail] = useState<{ row: Row; to: string; subject: string; message: string } | null>(null);
  const [result, setResult] = useState("");
  const { run, busy } = useAction();
  if (r.error) return <ErrorNotice error={r.error} onRetry={r.reload} />;
  if (!r.data) return <Loading />;
  const d = r.data;
  const rows = d.rows.filter((x) => (!filter || x.state === filter) && (!q.trim() || `${x.name} ${x.contract ?? ""} ${x.offer ?? ""}`.toLowerCase().includes(q.trim().toLowerCase())));
  const open = (row: Row) => { setResult(""); setMail({ row, to: row.recipients.join(", "), subject: row.subject, message: row.message }); };
  const send = () => mail && void run(() => api.post<{ sent: boolean; via: string; to: string[] }>(`/platform/contracts/${mail.row.tenant}/remind`, {
    to: mail.to.split(/[,;\s]+/).filter(Boolean), subject: mail.subject, message: mail.message,
  }), "Relance enregistrée").then((res) => {
    if (!res) return;
    setResult(res.sent ? `E-mail envoyé à ${res.to.join(", ")}.` : `Relance notifiée aux administrateurs de l’entreprise dans l’application (${res.via}). Pour l’e-mail, utilisez « Ouvrir dans ma messagerie ».`);
    r.reload();
  }, () => undefined);
  const mailto = mail ? `mailto:${encodeURIComponent(mail.to.replace(/\s/g, ""))}?subject=${encodeURIComponent(mail.subject)}&body=${encodeURIComponent(mail.message)}` : "";
  const csv = () => {
    const lines = [["Entreprise", "Contrat", "Offre", "Abonnement", "Début", "Échéance", "Jours restants", "État", "Contact", "E-mail", "Dernière relance"],
      ...rows.map((x) => [x.name, x.contract ?? "", x.offer ?? "", x.subscriptionStatus, fr(x.start), fr(x.end), x.daysLeft ?? "", x.stateLabel, x.contact, x.recipients.join(" "), x.lastReminder ? fr(x.lastReminder.at) : ""])];
    const blob = new Blob(["﻿" + lines.map((l) => l.join(";")).join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "contrats_entreprises.csv"; a.click();
  };
  const KPI: [Row["state"], string][] = [["expired", "Expirés"], ["soon", "< 30 jours"], ["watch", "< 90 jours"], ["ok", "En cours"], ["open", "Sans échéance"]];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="kpis">
        {KPI.map(([k, l]) => (
          <button key={k} type="button" className="kpi" style={{ cursor: "pointer", textAlign: "left", outline: filter === k ? "2px solid var(--accent)" : undefined }} onClick={() => setFilter(filter === k ? "" : k)}>
            <label>{l}</label><strong>{d.counts[k] ?? 0}</strong>
          </button>
        ))}
      </div>
      <Card title="Contrats des entreprises clientes" sub={`Échéance = fin de l’abonnement en cours (sinon fin du contrat ou de l’essai). Les plus urgents en premier. ${d.smtp ? "Les relances partent par e-mail depuis le serveur de la plateforme." : "Serveur e-mail de la plateforme non configuré : la relance est notifiée dans l’application et vous l’envoyez depuis votre messagerie."}`}
        extra={<button type="button" className="btn sm" onClick={csv}>⬇ Export CSV</button>}>
        <div className="toolbar" style={{ display: "flex", gap: 8, marginBottom: 10 }}>
          <input className="inp" style={{ maxWidth: 320 }} placeholder="Rechercher une entreprise, un contrat…" aria-label="Rechercher" value={q} onChange={(e) => setQ(e.target.value)} />
          {filter && <button type="button" className="btn sm ghost" onClick={() => setFilter("")}>Tous les états</button>}
        </div>
        <div className="tbl-wrap">
          <table className="tbl tight">
            <thead><tr><th>Entreprise</th><th>Contrat / offre</th><th>Début</th><th>Échéance</th><th className="r">Jours restants</th><th>État</th><th>Contact</th><th>Dernière relance</th><th /></tr></thead>
            <tbody>
              {rows.map((x) => (
                <tr key={x.tenant}>
                  <td><b>{x.name}</b><small className="muted" style={{ display: "block" }}>{x.subscriptionStatus}</small></td>
                  <td>{x.contract ?? <span className="muted">Sans contrat</span>}<small className="muted" style={{ display: "block" }}>{x.offer ?? "—"}</small></td>
                  <td>{fr(x.start)}</td>
                  <td><b>{fr(x.end)}</b>{x.trialEnd && <small className="muted" style={{ display: "block" }}>essai → {fr(x.trialEnd)}</small>}</td>
                  <td className="r"><b style={{ color: x.state === "expired" ? "var(--crit)" : x.state === "soon" ? "var(--warn)" : undefined }}>{x.daysLeft ?? "—"}</b></td>
                  <td><Pill tone={TONE[x.state]}>{x.stateLabel}</Pill></td>
                  <td>{x.contact || "—"}<small className="muted" style={{ display: "block" }}>{x.recipients.join(", ") || "aucune adresse"}</small></td>
                  <td>{x.lastReminder ? <>{fr(x.lastReminder.at)}<small className="muted" style={{ display: "block" }}>{x.lastReminder.detail.split(" · ").pop()}</small></> : <span className="muted">Jamais</span>}</td>
                  <td><button type="button" className={`btn sm ${x.state === "expired" || x.state === "soon" ? "primary" : ""}`} onClick={() => open(x)}>✉ Relancer</button></td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={9} className="muted">Aucune entreprise.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>
      {mail && (
        <Modal title={`Relancer ${mail.row.name}`} onClose={() => setMail(null)} wide
          footer={<>
            <a className="btn" href={mailto} onClick={() => setTimeout(() => void 0, 0)}>Ouvrir dans ma messagerie</a>
            <button type="button" className="btn" onClick={() => setMail(null)}>Fermer</button>
            <button type="button" className="btn primary" disabled={busy || !mail.to.trim()} onClick={send}>{d.smtp ? "Envoyer l’e-mail" : "Enregistrer la relance et notifier"}</button>
          </>}>
          <Field id="ct-to" label="Destinataires (contact et administrateurs de l’entreprise)"><input id="ct-to" className="inp" value={mail.to} onChange={(e) => setMail({ ...mail, to: e.target.value })} /></Field>
          <Field id="ct-subject" label="Objet"><input id="ct-subject" className="inp" value={mail.subject} onChange={(e) => setMail({ ...mail, subject: e.target.value })} /></Field>
          <Field id="ct-body" label="Message"><textarea id="ct-body" className="inp" rows={9} value={mail.message} onChange={(e) => setMail({ ...mail, message: e.target.value })} /></Field>
          {result && <div className="notice" style={{ marginTop: 8 }}>{result}</div>}
        </Modal>
      )}
    </div>
  );
}
