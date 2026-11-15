// Pilote › fiche entreprise › Notifications e-mail : configuration SMTP de l'entreprise, règles, test et journal ;
// plus l'état du serveur SMTP de la plateforme (demandes de licence, relances de contrat).
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { useAction } from "../../components/ui";
import { DeliveryLog, type DeliveryData } from "./DeliveryLog";
import { SmtpTestPanel } from "./SmtpTestPanel";

type Email = { enabled: boolean; host: string; port: number; security: string; username: string; from_address: string; passwordSet: boolean; passwordHint: string };
type Data = DeliveryData & { tenant: { id: number; name: string }; email: Email; smtpTests: { at: string; ok: boolean; recipient: string; subject: string; error: string }[]; events: { code: string; label: string }[]; rules: Record<string, Record<string, boolean>> };
type Platform = DeliveryData & { smtp: { host: string; port: number; security: string; username: string; from_address: string; passwordSet: boolean; configured: boolean } };

export function PilotTenantNotifications({ tenantId }: { tenantId: number }) {
  const r = useApi(() => api.get<Data>(`/platform/tenants/${tenantId}/notifications`), [tenantId]);
  const plat = useApi(() => api.get<Platform>("/platform/notifications"));
  const { run, busy } = useAction();
  const [f, setF] = useState<(Email & { password: string }) | null>(null);
  useEffect(() => { if (r.data) setF({ ...r.data.email, password: "" }); }, [r.data]);
  if (!r.data || !f) return <p className="muted">Chargement…</p>;
  const save = () => void run(() => api.put(`/platform/tenants/${tenantId}/notifications/email`, {
    enabled: f.enabled, password: f.password || undefined,
    settings: { host: f.host, port: f.port, security: f.security, username: f.username, from_address: f.from_address } }), "Configuration e-mail enregistrée").then(() => r.reload(), () => undefined);
  const set = (k: keyof typeof f, v: string | number | boolean) => setF({ ...f, [k]: v });
  const p = plat.data?.smtp;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <section>
        <b>Envoi e-mail de {r.data.tenant.name}</b>
        <p className="muted" style={{ fontSize: 12, margin: "4px 0 8px" }}>Même configuration que celle de l'administrateur (Configuration › Notifications) : toute modification est visible des deux côtés et tracée dans l'audit.</p>
        <div className="grid g2" style={{ gap: 8 }}>
          <label><span className="muted" style={{ fontSize: 12 }}>Serveur SMTP</span><input className="inp" value={f.host} onChange={(e) => set("host", e.target.value)} placeholder="smtp.exemple.fr" /></label>
          <label><span className="muted" style={{ fontSize: 12 }}>Port</span><input className="inp" type="number" value={f.port} onChange={(e) => set("port", Number(e.target.value))} /></label>
          <label><span className="muted" style={{ fontSize: 12 }}>Sécurité</span>
            <select className="inp" value={f.security} onChange={(e) => set("security", e.target.value)}><option value="starttls">STARTTLS</option><option value="ssl">SSL/TLS</option><option value="none">Aucune</option></select></label>
          <label><span className="muted" style={{ fontSize: 12 }}>Identifiant</span><input className="inp" value={f.username} onChange={(e) => set("username", e.target.value)} autoComplete="off" /></label>
          <label><span className="muted" style={{ fontSize: 12 }}>Adresse d'expédition</span><input className="inp" value={f.from_address} onChange={(e) => set("from_address", e.target.value)} placeholder="notifications@entreprise.fr" /></label>
          <label><span className="muted" style={{ fontSize: 12 }}>Clé SMTP {f.passwordSet ? `(définie ····${f.passwordHint})` : "(non définie)"}</span>
            <input className="inp" type="password" autoComplete="new-password" placeholder={f.passwordSet ? "laisser vide pour conserver" : "mot de passe / clé API"} value={f.password} onChange={(e) => set("password", e.target.value)} /></label>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginTop: 8 }}>
          <label className="vb-check"><input type="checkbox" checked={f.enabled} onChange={(e) => set("enabled", e.target.checked)} /> Envoi e-mail actif</label>
          <button type="button" className="btn primary sm" disabled={busy} onClick={save}>Enregistrer</button>
        </div>
        <SmtpTestPanel key={r.data.smtpTests.length} postUrl={`/platform/tenants/${tenantId}/notifications/test`} initial={r.data.smtpTests} />
      </section>
      <section>
        <b>Événements envoyés par e-mail</b>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
          {r.data.events.map((e) => (
            <span key={e.code} style={{ fontSize: 12, padding: "2px 8px", borderRadius: 999, background: r.data!.rules[e.code]?.email ? "#dcfce7" : "#f1f5f9", color: r.data!.rules[e.code]?.email ? "#166534" : "#64748b" }}>
              {r.data!.rules[e.code]?.email ? "✉️ " : ""}{e.label}
            </span>
          ))}
        </div>
        <p className="muted" style={{ fontSize: 11 }}>Les règles par événement sont réglées par l'administrateur de l'entreprise.</p>
      </section>
      <DeliveryLog data={r.data} title="Journal des envois de l'entreprise" />
      {p && (
        <section style={{ borderTop: "1px solid var(--line, #e2e8f0)", paddingTop: 12 }}>
          <b>Serveur SMTP de la plateforme</b> <span className="muted" style={{ fontSize: 12 }}>(demandes de licence vers le Pilote, relances de contrat)</span>
          <p style={{ margin: "6px 0", fontSize: 13 }}>{p.configured ? <>✅ {p.host}:{p.port} ({p.security}) · expéditeur {p.from_address || "—"} · mot de passe {p.passwordSet ? "défini" : "non défini"}</>
            : <>⚠️ Non configuré : renseignez PLATFORM_EMAIL_HOST, PLATFORM_EMAIL_USER, PLATFORM_EMAIL_PASSWORD et PLATFORM_EMAIL_FROM dans le fichier .env du backend. En attendant, le Pilote est notifié dans l'application.</>}</p>
          {p.configured && <SmtpTestPanel postUrl="/platform/notifications/test" />}
          {plat.data && plat.data.rows.length > 0 && <div style={{ marginTop: 8 }}><DeliveryLog data={plat.data} title="Journal des envois de la plateforme" /></div>}
        </section>
      )}
    </div>
  );
}
