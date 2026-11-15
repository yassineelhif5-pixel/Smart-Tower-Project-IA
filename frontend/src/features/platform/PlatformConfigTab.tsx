// Pilote › Configuration : URL publique de l'application (liens des e-mails) et serveur SMTP de la plateforme.
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { Card, useAction } from "../../components/ui";
import { DeliveryLog, type DeliveryData } from "../notifications/DeliveryLog";
import { SmtpTestPanel } from "../notifications/SmtpTestPanel";
import { GoogleConfigCard } from "./GoogleConfigCard";
import { StripeConfigCard } from "./StripeConfigCard";

type Smtp = { host: string; port: number; security: string; username: string; from_address: string; passwordSet: boolean; configured: boolean; source: "pilote" | "env"; passwordHint: string };
type Conf = { appUrl: string; effectiveUrl: string; source: "pilote" | "env" | "localhost"; envUrl: string; localUrl: string; updatedBy: string; updatedAt: string | null; smtp: Smtp; smtpTests: { at: string; ok: boolean; recipient: string; subject: string; error: string }[] };
const SRC: Record<string, string> = { pilote: "réglage du Pilote", env: "fichier .env (APP_PUBLIC_URL)", localhost: "valeur par défaut (localhost)" };

export function PlatformConfigTab() {
  const r = useApi(() => api.get<Conf>("/platform/config"));
  const log = useApi(() => api.get<DeliveryData>("/platform/notifications"));
  const { run, busy } = useAction();
  const [url, setUrl] = useState("");
  const [f, setF] = useState<{ host: string; port: number; security: string; username: string; from_address: string; password: string } | null>(null);
  useEffect(() => {
    if (!r.data) return;
    setUrl(r.data.appUrl);
    const m = r.data.smtp;
    setF({ host: m.host, port: m.port, security: m.security, username: m.username, from_address: m.from_address, password: "" });
  }, [r.data]);
  if (!r.data) return <p className="muted">Chargement…</p>;
  const c = r.data;
  const save = (v: string) => void run(() => api.put("/platform/config", { appUrl: v }), v ? "URL publique enregistrée" : "URL publique effacée : localhost utilisé")
    .then(() => r.reload(), () => undefined);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <Card title="🌐 URL publique de l'application" sub="Utilisée pour les liens « Ouvrir » des e-mails de notification (demandes de licence, actions, échéances, récaps…).">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input className="inp" style={{ flex: 1, minWidth: 280 }} placeholder="https://app.mondomaine.fr" aria-label="URL publique" value={url} onChange={(e) => setUrl(e.target.value)} />
          <button type="button" className="btn primary sm" disabled={busy} onClick={() => save(url.trim())}>Enregistrer</button>
          {c.appUrl && <button type="button" className="btn sm" disabled={busy} onClick={() => { setUrl(""); save(""); }}>Effacer</button>}
        </div>
        <p style={{ margin: "10px 0 4px" }}>URL utilisée actuellement : <a href={c.effectiveUrl} target="_blank" rel="noopener noreferrer"><b>{c.effectiveUrl}</b></a> <span className="muted">({SRC[c.source]})</span></p>
        <p className="muted" style={{ fontSize: 12, margin: 0 }}>
          Ordre de priorité : ce réglage s'il est renseigné et valide (http:// ou https://) → APP_PUBLIC_URL du fichier .env{c.envUrl ? ` (${c.envUrl})` : " (vide)"} → {c.localUrl}.
          {c.updatedBy && ` Dernière modification par ${c.updatedBy}${c.updatedAt ? ` le ${new Date(c.updatedAt).toLocaleString("fr-FR")}` : ""}.`}
        </p>
      </Card>
      <GoogleConfigCard />
      <StripeConfigCard />
      <Card title="✉️ Serveur SMTP de la plateforme" sub="Envoi des e-mails du Pilote (demandes de licence, relances de contrat). Les entreprises utilisent leur propre SMTP (fiche entreprise › Notifications e-mail).">
        {f && (
          <>
            <div className="grid g2" style={{ gap: 8 }}>
              <label><span className="muted" style={{ fontSize: 12 }}>Serveur SMTP</span><input className="inp" value={f.host} onChange={(e) => setF({ ...f, host: e.target.value })} placeholder="smtp-relay.brevo.com" /></label>
              <label><span className="muted" style={{ fontSize: 12 }}>Port</span><input className="inp" type="number" value={f.port} onChange={(e) => setF({ ...f, port: Number(e.target.value) })} /></label>
              <label><span className="muted" style={{ fontSize: 12 }}>Sécurité</span>
                <select className="inp" value={f.security} onChange={(e) => setF({ ...f, security: e.target.value })}><option value="starttls">STARTTLS (587)</option><option value="ssl">SSL/TLS (465)</option><option value="none">Aucune</option></select></label>
              <label><span className="muted" style={{ fontSize: 12 }}>Identifiant de connexion</span><input className="inp" value={f.username} autoComplete="off" onChange={(e) => setF({ ...f, username: e.target.value })} /></label>
              <label><span className="muted" style={{ fontSize: 12 }}>Adresse d'expédition</span><input className="inp" value={f.from_address} onChange={(e) => setF({ ...f, from_address: e.target.value })} /></label>
              <label><span className="muted" style={{ fontSize: 12 }}>Clé SMTP {c.smtp.passwordSet ? `(définie ····${c.smtp.passwordHint})` : "(non définie)"}</span>
                <input className="inp" type="password" autoComplete="new-password" placeholder={c.smtp.passwordSet ? "laisser vide pour conserver" : "clé SMTP / mot de passe"} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></label>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 8 }}>
              <button type="button" className="btn primary sm" disabled={busy} onClick={() => void run(() => api.put("/platform/config/smtp", { ...f, password: f.password || undefined }), "SMTP plateforme enregistré").then(() => r.reload(), () => undefined)}>Enregistrer</button>
              {c.smtp.source === "pilote" && <button type="button" className="btn sm" disabled={busy} onClick={() => void run(() => api.put("/platform/config/smtp", { reset: true }), "Retour à la configuration du fichier .env").then(() => r.reload(), () => undefined)}>Revenir au fichier .env</button>}
              <span className="muted" style={{ fontSize: 12 }}>Source actuelle : {c.smtp.source === "pilote" ? "réglage du Pilote (prioritaire)" : "fichier .env (PLATFORM_EMAIL_*)"} · la clé est stockée chiffrée et jamais réaffichée.</span>
            </div>
          </>
        )}
        <SmtpTestPanel postUrl="/platform/notifications/test" initial={c.smtpTests} />
        {log.data && <DeliveryLog data={log.data} title="Journal des envois de la plateforme" />}
      </Card>
    </div>
  );
}
