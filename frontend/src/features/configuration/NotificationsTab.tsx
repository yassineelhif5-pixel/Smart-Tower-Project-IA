import { useState } from "react";

import { ApiError } from "../../api/client";
import { adminApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Loading, Pill, Switch, useAction } from "../../components/ui";
import type { Channel, NotificationSettings } from "../../types/api";

export function NotificationsTab({ adminEmail }: { adminEmail: string }) {
  const state = useApi(adminApi.notifications);
  const { run, busy } = useAction();

  if (state.error) return <ErrorNotice error={state.error} onRetry={state.reload} />;
  if (!state.data) return <Loading />;
  const data = state.data;

  async function setRule(event: string, kind: string, value: boolean) {
    const next = await run(() => adminApi.setRules({ [event]: { [kind]: value } })).catch(() => undefined);
    if (next) state.setData(next);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div className="grid g2">
        {data.channels.map((c) => (
          <ChannelCard key={c.kind} channel={c} adminEmail={adminEmail} onSaved={(next) => state.setData(next)} />
        ))}
      </div>
      <Card
        title="Règles d'envoi"
        sub="Pour chaque événement, les canaux qui le diffusent. Un canal désactivé n'envoie rien, même si la case est cochée."
      >
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Événement</th>
                {data.channels.map((c) => (
                  <th key={c.kind} style={{ textAlign: "center" }}>
                    {c.label} {!c.enabled && <span className="muted">(inactif)</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.events.map((e) => (
                <tr key={e.code}>
                  <td>
                    <b>{e.label}</b>
                  </td>
                  {data.channels.map((c) => (
                    <td key={c.kind} style={{ textAlign: "center" }}>
                      <span className="perm">
                        <input
                          type="checkbox"
                          aria-label={`${e.label} par ${c.label}`}
                          checked={data.rules[e.code]?.[c.kind] ?? false}
                          disabled={busy}
                          onChange={(ev) => setRule(e.code, c.kind, ev.target.checked)}
                        />
                      </span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function ChannelCard({
  channel,
  adminEmail,
  onSaved,
}: {
  channel: Channel;
  adminEmail: string;
  onSaved: (s: NotificationSettings) => void;
}) {
  const [settings, setSettings] = useState<Record<string, string | number>>({
    port: 587,
    security: "starttls",
    ...channel.settings,
  });
  const [to, setTo] = useState(adminEmail);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const { run, busy } = useAction();
  const set = (k: string, v: string | number) => setSettings((s) => ({ ...s, [k]: v }));

  async function save(enabled: boolean) {
    setErrors({});
    try {
      const next = await run(
        () => adminApi.setChannel(channel.kind, enabled, channel.kind === "email" ? settings : {}),
        "Canal enregistré",
      );
      if (next) onSaved(next);
    } catch (e) {
      if (e instanceof ApiError) setErrors({ ...e.fieldErrors(), form: e.message });
    }
  }

  async function test() {
    await run(
      () => adminApi.testChannel(channel.kind, channel.kind === "email" ? to : undefined),
      "Message de test envoyé",
    ).catch(() => undefined);
  }

  const secretLine = channel.secret && (
    <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>
      {channel.kind === "email" ? "Mot de passe SMTP" : "URL du webhook"} :{" "}
      {channel.secret.isSet ? <Pill tone="ok">défini</Pill> : <Pill tone="">non défini</Pill>} — à saisir dans API →
      Clés de services externes.
    </p>
  );

  return (
    <Card
      title={channel.label}
      extra={
        <Switch
          label={`Activer ${channel.label}`}
          checked={channel.enabled}
          disabled={busy}
          onChange={(v) => save(v)}
        />
      }
      sub={channel.enabled ? "Actif" : "Inactif"}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {channel.kind === "inapp" && (
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>
            Notifications affichées dans la cloche de l'application.
          </p>
        )}
        {channel.kind === "email" && (
          <>
            <div className="frow">
              <Field id="smtp_host" label="Serveur SMTP" error={errors["settings.host"]}>
                <input
                  id="smtp_host"
                  className="inp"
                  value={settings.host ?? ""}
                  onChange={(e) => set("host", e.target.value)}
                  placeholder="smtp.office365.com"
                />
              </Field>
              <Field id="smtp_port" label="Port" error={errors["settings.port"]}>
                <input
                  id="smtp_port"
                  className="inp mono"
                  type="number"
                  value={settings.port ?? 587}
                  onChange={(e) => set("port", Number(e.target.value))}
                />
              </Field>
            </div>
            <div className="frow">
              <Field id="smtp_user" label="Utilisateur SMTP">
                <input
                  id="smtp_user"
                  className="inp"
                  value={settings.username ?? ""}
                  onChange={(e) => set("username", e.target.value)}
                />
              </Field>
              <Field id="smtp_sec" label="Sécurité" error={errors["settings.security"]}>
                <select
                  id="smtp_sec"
                  className="inp"
                  value={settings.security}
                  onChange={(e) => set("security", e.target.value)}
                >
                  <option value="starttls">STARTTLS (587)</option>
                  <option value="ssl">SSL/TLS (465)</option>
                  <option value="none">Aucune (déconseillé)</option>
                </select>
              </Field>
            </div>
            <Field id="smtp_from" label="Adresse d'expéditeur" error={errors["settings.from_address"]}>
              <input
                id="smtp_from"
                className="inp"
                type="email"
                value={settings.from_address ?? ""}
                onChange={(e) => set("from_address", e.target.value)}
                placeholder="pilotage@demo-esn.fr"
              />
            </Field>
            {secretLine}
            <div className="btns">
              <button className="btn primary" onClick={() => save(channel.enabled)} disabled={busy}>
                Enregistrer
              </button>
              <input
                className="inp"
                type="email"
                aria-label="Destinataire du test"
                value={to}
                onChange={(e) => setTo(e.target.value)}
                placeholder="destinataire@…"
                style={{ width: 210 }}
              />
              <button className="btn" onClick={test} disabled={busy || !channel.settings.host}>
                Envoyer un test
              </button>
            </div>
          </>
        )}
        {(channel.kind === "teams" || channel.kind === "slack") && (
          <>
            {secretLine}
            <div className="btns">
              <button className="btn" onClick={test} disabled={busy || !channel.secret?.isSet}>
                Envoyer un test
              </button>
            </div>
          </>
        )}
        {errors.form && !Object.keys(errors).some((k) => k.startsWith("settings.")) && (
          <div className="callout warn" role="alert">
            <b>{errors.form}</b>
          </div>
        )}
      </div>
    </Card>
  );
}
