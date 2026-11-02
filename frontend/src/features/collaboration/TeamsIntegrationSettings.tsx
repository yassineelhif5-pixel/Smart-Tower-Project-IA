import { useEffect, useState } from "react";

import { calendarApi, teamsApi } from "../../api/collab";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, fmtDate, Loading, Pill, Switch, useAction } from "../../components/ui";
import type { CalendarColors, EventStatus, Priority, TeamsConnectorSettings } from "../../types/collab";
import { DEFAULT_COLORS, PRIORITY_LABEL, STATUS_LABEL } from "../calendar/calendarUtils";

const STATUS_TONE: Record<TeamsConnectorSettings["status"], ["ok" | "warn" | "crit" | "", string]> = {
  not_configured: ["", "Non configuré"],
  configured: ["warn", "Configuré, non vérifié"],
  ok: ["ok", "Vérifié"],
  error: ["crit", "En erreur"],
};

/** Onglet « Connecteurs » de la Configuration : application Microsoft de l'entreprise et couleurs du calendrier. */
export function TeamsIntegrationSettings() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <TeamsConnectorCard />
      <CalendarColorsCard />
    </div>
  );
}

function TeamsConnectorCard() {
  const c = useApi(teamsApi.admin);
  const { run, busy } = useAction();
  const [form, setForm] = useState<Partial<TeamsConnectorSettings>>({});
  const [secret, setSecret] = useState("");
  const [check, setCheck] = useState<{ ok: boolean; message: string } | null>(null);
  useEffect(() => {
    if (c.data) setForm(c.data);
  }, [c.data]);
  if (c.error) return <ErrorNotice error={c.error} onRetry={c.reload} />;
  if (!c.data) return <Loading />;
  const d = c.data;
  const set = (patch: Partial<TeamsConnectorSettings>) => setForm((f) => ({ ...f, ...patch }));
  const expiresSoon = d.secretExpiresOn && new Date(d.secretExpiresOn).getTime() - Date.now() < 30 * 864e5;

  const save = () =>
    void run(
      () =>
        teamsApi.saveAdmin({
          directoryId: form.directoryId,
          clientId: form.clientId,
          enabled: form.enabled,
          allowChannels: form.allowChannels,
          allowChannelCreation: form.allowChannelCreation,
          allowEditInTeams: form.allowEditInTeams,
          secretExpiresOn: form.secretExpiresOn || null,
          ...(secret ? { clientSecret: secret } : {}),
        }),
      "Connecteur enregistré",
    ).then(
      (r) => {
        if (r) {
          c.setData(r);
          setSecret("");
        }
      },
      () => undefined,
    );

  return (
    <Card
      title="Microsoft Teams"
      sub="Application Microsoft Entra de votre entreprise. Les messages sont publiés au nom de chaque utilisateur (permissions déléguées)."
      extra={<Pill tone={STATUS_TONE[d.status][0]}>{STATUS_TONE[d.status][1]}</Pill>}
    >
      <div className="ev-form">
        <div className="grid g2">
          <Field id="t-dir" label="Identifiant de l'annuaire (tenant Microsoft)">
            <input
              id="t-dir"
              className="inp mono"
              value={form.directoryId ?? ""}
              onChange={(e) => set({ directoryId: e.target.value.trim() })}
            />
          </Field>
          <Field id="t-client" label="Identifiant de l'application (client)">
            <input
              id="t-client"
              className="inp mono"
              value={form.clientId ?? ""}
              onChange={(e) => set({ clientId: e.target.value.trim() })}
            />
          </Field>
          <Field
            id="t-secret"
            label="Secret client"
            hint={d.secretSet ? `Défini (…${d.secretHint}). Laissez vide pour le conserver.` : "Non défini."}
          >
            <input
              id="t-secret"
              className="inp mono"
              type="password"
              autoComplete="new-password"
              value={secret}
              placeholder={d.secretSet ? "••••••••" : ""}
              onChange={(e) => setSecret(e.target.value)}
            />
          </Field>
          <Field
            id="t-exp"
            label="Expiration du secret (rappel)"
            error={expiresSoon ? "Le secret expire dans moins de 30 jours : renouvelez-le." : undefined}
          >
            <input
              id="t-exp"
              className="inp"
              type="date"
              value={form.secretExpiresOn ?? ""}
              onChange={(e) => set({ secretExpiresOn: e.target.value })}
            />
          </Field>
        </div>
        <div className="switch-list">
          {(
            [
              [
                "enabled",
                "Activer le connecteur",
                "Les utilisateurs peuvent relier leur compte et publier dans Teams.",
              ],
              [
                "allowChannels",
                "Canaux d'équipe",
                "Publier dans des canaux existants (consentement administrateur Microsoft requis).",
              ],
              [
                "allowChannelCreation",
                "Création de canaux",
                "Permission supplémentaire Channel.Create ; réservée au droit « Collaboration · Valider ».",
              ],
              [
                "allowEditInTeams",
                "Répercuter modifications et suppressions",
                "Permission supplémentaire ChatMessage.ReadWrite.",
              ],
            ] as [keyof TeamsConnectorSettings, string, string][]
          ).map(([k, l, h]) => (
            <label key={k} className="switch-row">
              <Switch
                label={l}
                checked={!!form[k]}
                disabled={(k === "allowChannelCreation" && !form.allowChannels) || false}
                onChange={(v) => set({ [k]: v } as Partial<TeamsConnectorSettings>)}
              />
              <span>
                <b>{l}</b>
                <small className="muted">{h}</small>
              </span>
            </label>
          ))}
        </div>
        <div className="callout info">
          <div>
            <b>À déclarer dans l'application Microsoft Entra</b>
            <div>
              URI de redirection : <code>{d.redirectUri}</code>
            </div>
            <div>
              Permissions déléguées demandées : <code>{d.scopes.join(" ")}</code>
            </div>
            {d.webhookUrl ? (
              <div>
                Notifications : <code>{d.webhookUrl}</code>
              </div>
            ) : (
              <div className="muted">PUBLIC_BASE_URL non défini : les réponses Teams sont relues périodiquement.</div>
            )}
            <div className="muted">
              {d.linkedUsers} utilisateur(s) relié(s)
              {d.lastCheckAt ? ` · dernière vérification ${fmtDate(d.lastCheckAt)}` : ""}
            </div>
          </div>
        </div>
        {d.lastError && <div className="callout warn">{d.lastError}</div>}
        {check && <div className={`callout ${check.ok ? "ok" : "warn"}`}>{check.message}</div>}
        <div className="btns">
          <button
            className="btn"
            disabled={busy || !d.directoryId || !d.clientId}
            onClick={() =>
              void run(teamsApi.check).then(
                (r) => {
                  if (r) {
                    setCheck({ ok: r.ok, message: r.message });
                    c.setData(r);
                  }
                },
                () => undefined,
              )
            }
          >
            Vérifier la connexion
          </button>
          <button className="btn primary" disabled={busy} onClick={save}>
            Enregistrer
          </button>
        </div>
      </div>
    </Card>
  );
}

function CalendarColorsCard() {
  const s = useApi(calendarApi.settings);
  const { run, busy } = useAction();
  const [v, setV] = useState<CalendarColors>(DEFAULT_COLORS);
  useEffect(() => {
    if (s.data) setV(s.data);
  }, [s.data]);
  if (s.error) return <ErrorNotice error={s.error} onRetry={s.reload} />;
  if (!s.data) return <Loading />;
  return (
    <Card title="Couleurs du calendrier" sub="Propres à votre entreprise, appliquées à toutes les vues.">
      <div className="ev-form">
        <fieldset className="radios">
          <legend>Colorer les éléments selon</legend>
          {(["status", "priority"] as const).map((k) => (
            <label key={k}>
              <input
                type="radio"
                name="colorBy"
                checked={v.colorBy === k}
                onChange={() => setV({ ...v, colorBy: k })}
              />{" "}
              {k === "status" ? "le statut" : "la priorité"}
            </label>
          ))}
        </fieldset>
        <div className="color-grid">
          {(Object.keys(STATUS_LABEL) as EventStatus[]).map((k) => (
            <label key={k}>
              <input
                type="color"
                value={v.status[k]}
                onChange={(e) => setV({ ...v, status: { ...v.status, [k]: e.target.value } })}
              />
              {STATUS_LABEL[k]}
            </label>
          ))}
        </div>
        <div className="color-grid">
          {(Object.keys(PRIORITY_LABEL) as Priority[]).map((k) => (
            <label key={k}>
              <input
                type="color"
                value={v.priority[k]}
                onChange={(e) => setV({ ...v, priority: { ...v.priority, [k]: e.target.value } })}
              />
              Priorité {PRIORITY_LABEL[k].toLowerCase()}
            </label>
          ))}
        </div>
        <div className="btns">
          <button className="btn ghost" onClick={() => setV({ ...DEFAULT_COLORS, canEdit: v.canEdit })}>
            Couleurs par défaut
          </button>
          <button
            className="btn primary"
            disabled={busy || !v.canEdit}
            onClick={() =>
              void run(
                () => calendarApi.saveSettings({ status: v.status, priority: v.priority, colorBy: v.colorBy }),
                "Couleurs enregistrées",
              ).then(
                (r) => r && s.setData(r),
                () => undefined,
              )
            }
          >
            Enregistrer
          </button>
        </div>
      </div>
    </Card>
  );
}
