import { useState } from "react";

import { ApiError } from "../../api/client";
import { adminApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import {
  Card,
  ErrorNotice,
  Field,
  fmtDate,
  Icon,
  Loading,
  Modal,
  OneTimeSecret,
  Pill,
  Tabs,
  useAction,
} from "../../components/ui";
import type { Secret } from "../../types/api";

type Section = "tokens" | "secrets" | "status";

export function ApiTab() {
  const [section, setSection] = useState<Section>("tokens");
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <Tabs<Section>
        tabs={[
          ["tokens", "Jetons d'accès"],
          ["secrets", "Clés de services externes"],
          ["status", "État des API"],
        ]}
        value={section}
        onChange={setSection}
      />
      {section === "tokens" && <TokensSection />}
      {section === "secrets" && <SecretsSection />}
      {section === "status" && <StatusSection />}
    </div>
  );
}

function TokensSection() {
  const tokens = useApi(adminApi.tokens);
  const users = useApi(adminApi.users);
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", user: 0, readOnly: true, expiresInDays: 90 as number | null });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const { run, busy } = useAction();

  if (tokens.error) return <ErrorNotice error={tokens.error} onRetry={tokens.reload} />;
  if (!tokens.data) return <Loading />;

  async function create() {
    setErrors({});
    try {
      const r = await run(() => adminApi.createToken(form), "Jeton créé");
      if (r) {
        setCreating(false);
        setCreated(r.token);
        tokens.reload();
      }
    } catch (e) {
      if (e instanceof ApiError) setErrors(e.fieldErrors());
    }
  }

  async function revoke(id: number) {
    await run(() => adminApi.revokeToken(id), "Jeton révoqué").catch(() => undefined);
    tokens.reload();
  }

  return (
    <Card
      title="Jetons d'accès API"
      sub="Pour les applications tierces. Un jeton agit avec les droits et le périmètre de l'utilisateur choisi, et n'ouvre jamais le module Configuration."
      extra={
        <button className="btn primary" onClick={() => setCreating(true)}>
          Créer un jeton
        </button>
      }
    >
      {tokens.data.length === 0 ? (
        <p className="muted">Aucun jeton pour l'instant.</p>
      ) : (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Nom</th>
                <th>Agit en tant que</th>
                <th>Droits</th>
                <th>Expiration</th>
                <th>Dernière utilisation</th>
                <th>Statut</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {tokens.data.map((t) => (
                <tr key={t.id}>
                  <td className="cell-main">
                    <b>{t.name}</b>
                    <small className="mono muted">{t.prefix}…</small>
                  </td>
                  <td className="mono">{t.user.username}</td>
                  <td>{t.readOnly ? "Lecture seule" : "Lecture et écriture"}</td>
                  <td className="muted">{t.expiresAt ? fmtDate(t.expiresAt) : "Jamais"}</td>
                  <td className="muted">{fmtDate(t.lastUsedAt)}</td>
                  <td>
                    {t.revokedAt ? (
                      <Pill tone="">Révoqué</Pill>
                    ) : t.active ? (
                      <Pill tone="ok">Actif</Pill>
                    ) : (
                      <Pill tone="warn">Expiré</Pill>
                    )}
                  </td>
                  <td className="r">
                    {!t.revokedAt && (
                      <button className="btn sm danger" onClick={() => revoke(t.id)}>
                        Révoquer
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted mono" style={{ fontSize: 12, margin: "12px 0 0" }}>
        Utilisation : en-tête Authorization: Bearer pct_…
      </p>

      {creating && (
        <Modal
          title="Créer un jeton d'accès"
          onClose={() => setCreating(false)}
          footer={
            <>
              <button className="btn" onClick={() => setCreating(false)}>
                Annuler
              </button>
              <button className="btn primary" onClick={create} disabled={busy}>
                Créer
              </button>
            </>
          }
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <Field id="t_name" label="Nom (application ou usage)" error={errors.name}>
              <input
                id="t_name"
                className="inp"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </Field>
            <Field
              id="t_user"
              label="Agit en tant que"
              error={errors.user}
              hint="Le jeton hérite du rôle et des projets de cet utilisateur."
            >
              <select
                id="t_user"
                className="inp"
                value={form.user}
                onChange={(e) => setForm({ ...form, user: Number(e.target.value) })}
              >
                <option value={0}>Choisir un utilisateur…</option>
                {(users.data ?? [])
                  .filter((u) => u.isActive)
                  .map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.username} · {u.role}
                    </option>
                  ))}
              </select>
            </Field>
            <div className="frow">
              <Field id="t_ro" label="Droits du jeton">
                <select
                  id="t_ro"
                  className="inp"
                  value={form.readOnly ? "ro" : "rw"}
                  onChange={(e) => setForm({ ...form, readOnly: e.target.value === "ro" })}
                >
                  <option value="ro">Lecture seule</option>
                  <option value="rw">Lecture et écriture</option>
                </select>
              </Field>
              <Field id="t_exp" label="Expiration" error={errors.expiresInDays}>
                <select
                  id="t_exp"
                  className="inp"
                  value={form.expiresInDays ?? 0}
                  onChange={(e) => setForm({ ...form, expiresInDays: Number(e.target.value) || null })}
                >
                  <option value={30}>30 jours</option>
                  <option value={90}>90 jours</option>
                  <option value={365}>1 an</option>
                  <option value={0}>Jamais (déconseillé)</option>
                </select>
              </Field>
            </div>
          </div>
        </Modal>
      )}
      {created && (
        <Modal
          title="Jeton créé"
          onClose={() => setCreated(null)}
          footer={
            <button className="btn primary" onClick={() => setCreated(null)}>
              J'ai copié le jeton
            </button>
          }
        >
          <OneTimeSecret label="Jeton d'accès API." value={created} />
        </Modal>
      )}
    </Card>
  );
}

function SecretsSection() {
  const secrets = useApi(adminApi.secrets);
  const [editing, setEditing] = useState<Secret | null>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { run, busy } = useAction();

  if (secrets.error) return <ErrorNotice error={secrets.error} onRetry={secrets.reload} />;
  if (!secrets.data) return <Loading />;

  async function save() {
    if (!editing) return;
    setError(null);
    try {
      await run(() => adminApi.setSecret(editing.key, value), "Secret enregistré et chiffré");
      setEditing(null);
      setValue("");
      secrets.reload();
    } catch (e) {
      if (e instanceof ApiError) setError(e.message);
    }
  }

  async function remove(key: string) {
    await run(() => adminApi.deleteSecret(key), "Secret supprimé").catch(() => undefined);
    secrets.reload();
  }

  return (
    <Card
      title="Clés de services externes"
      sub="Chiffrées sur le serveur. Une clé saisie n'est jamais réaffichée : seuls ses 4 derniers caractères le sont."
    >
      <div className="list">
        {secrets.data.map((s) => (
          <div className="li" key={s.key}>
            <Icon name="key" />
            <div className="grow">
              <b>{s.label}</b>
              <small>
                {s.used_by}
                {s.updatedAt && ` · modifié le ${fmtDate(s.updatedAt)}`}
              </small>
            </div>
            {s.isSet ? <span className="mono muted">{s.hint}</span> : <Pill tone="">Non défini</Pill>}
            <button
              className="btn sm"
              onClick={() => {
                setEditing(s);
                setValue("");
                setError(null);
              }}
            >
              {s.isSet ? "Remplacer" : "Définir"}
            </button>
            {s.isSet && (
              <button className="btn sm ghost" onClick={() => remove(s.key)}>
                Supprimer
              </button>
            )}
          </div>
        ))}
      </div>
      <p className="muted" style={{ fontSize: 12.5, margin: "12px 0 0" }}>
        Les clés d'autres services (stockage, OCR, IA) apparaîtront ici quand leurs connecteurs seront ajoutés.
      </p>
      {editing && (
        <Modal
          title={editing.label}
          onClose={() => setEditing(null)}
          footer={
            <>
              <button className="btn" onClick={() => setEditing(null)}>
                Annuler
              </button>
              <button className="btn primary" onClick={save} disabled={busy || !value}>
                Enregistrer
              </button>
            </>
          }
        >
          <Field
            id="s_value"
            label="Valeur"
            error={error ?? undefined}
            hint={editing.key.endsWith("webhook_url") ? "URL https fournie par Teams ou Slack." : undefined}
          >
            <input
              id="s_value"
              className="inp mono"
              type="password"
              autoComplete="off"
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          </Field>
        </Modal>
      )}
    </Card>
  );
}

function StatusSection() {
  const [hours, setHours] = useState(24);
  const [errorsOnly, setErrorsOnly] = useState(false);
  const stats = useApi(() => adminApi.stats(hours), [hours]);
  const endpoints = useApi(adminApi.endpoints);
  const logs = useApi(() => adminApi.logs(errorsOnly), [errorsOnly]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <label htmlFor="api_period" className="muted" style={{ fontSize: 13 }}>
          Période
        </label>
        <select
          id="api_period"
          className="inp"
          value={hours}
          onChange={(e) => setHours(Number(e.target.value))}
          style={{ width: "auto" }}
        >
          <option value={1}>Dernière heure</option>
          <option value={24}>24 dernières heures</option>
          <option value={168}>7 derniers jours</option>
        </select>
      </div>
      {stats.error && <ErrorNotice error={stats.error} onRetry={stats.reload} />}
      {stats.data && (
        <div className="kpis">
          {[
            ["Appels", stats.data.requests],
            ["Temps moyen", `${stats.data.avgMs} ms`],
            ["Erreurs client (4xx)", stats.data.clientErrors],
            ["Erreurs serveur (5xx)", stats.data.serverErrors],
          ].map(([label, value]) => (
            <div
              className={`kpi ${label === "Erreurs serveur (5xx)" && Number(value) > 0 ? "warn" : ""}`}
              key={String(label)}
            >
              <label>{label}</label>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Card title="Points d'accès" sub="Liste générée à partir des routes réelles du serveur">
          {endpoints.error ? (
            <ErrorNotice error={endpoints.error} />
          ) : !endpoints.data ? (
            <Loading />
          ) : (
            <div className="tbl-wrap">
              <table className="tbl tight">
                <thead>
                  <tr>
                    <th>Chemin</th>
                    <th>Méthodes</th>
                    <th>Accès</th>
                  </tr>
                </thead>
                <tbody>
                  {endpoints.data.map((e) => (
                    <tr key={e.path}>
                      <td className="mono">{e.path}</td>
                      <td className="mono muted">{e.methods.join(" ")}</td>
                      <td>
                        <Pill tone={e.access === "admin" ? "acc" : e.access === "public" ? "warn" : "info"}>
                          {e.access}
                        </Pill>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <Card
          title="Derniers appels"
          sub="Sans contenu, sans paramètres, sans adresse IP"
          extra={
            <label className="chk" style={{ padding: 0 }}>
              <input type="checkbox" checked={errorsOnly} onChange={(e) => setErrorsOnly(e.target.checked)} />
              <span>Erreurs seulement</span>
            </label>
          }
        >
          {logs.error ? (
            <ErrorNotice error={logs.error} />
          ) : !logs.data ? (
            <Loading />
          ) : (
            <div className="tbl-wrap" style={{ maxHeight: 420, overflow: "auto" }}>
              <table className="tbl tight">
                <thead>
                  <tr>
                    <th>Heure</th>
                    <th>Appel</th>
                    <th className="r">Statut</th>
                    <th className="r">Durée</th>
                    <th>Par</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.data.map((l, i) => (
                    <tr key={i}>
                      <td className="muted">{fmtDate(l.at)}</td>
                      <td className="mono">
                        {l.method} {l.path}
                      </td>
                      <td className="r">
                        <Pill tone={l.status >= 500 ? "crit" : l.status >= 400 ? "warn" : "ok"}>{l.status}</Pill>
                      </td>
                      <td className="r mono">{l.durationMs} ms</td>
                      <td className="mono muted">{l.token ? `jeton ${l.token}` : (l.user ?? "—")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
