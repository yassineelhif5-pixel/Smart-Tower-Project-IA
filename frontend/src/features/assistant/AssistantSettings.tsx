import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Loading, useAction } from "../../components/ui";

type Mode = { code: string; label: string };
type AdminConf = {
  license: { enabled: boolean; maxMode: string }; modes: Mode[]; llm: boolean; llmConfigured: boolean;
  profiles: { code: string; label: string; internal: boolean; mode: string; assistant: string }[];
};
const RANK: Record<string, number> = { off: 0, semi: 1, auto: 2 };
const SHORT: Record<string, string> = { off: "Désactivé", semi: "Semi-automatique", auto: "Automatique" };
const HELP: Record<string, string> = {
  off: "Pas d’assistant pour ce profil.",
  semi: "L’assistant propose (relances, actions, replanification) ; un humain valide avant exécution.",
  auto: "L’assistant agit seul et remplace le chef de projet humain (relances automatiques, créations, replanification).",
};

/** Paramétrage (administrateur) : mode de l'assistant IA pour chaque profil, dans la limite de la licence du Pilote. */
export function AssistantAdminTab() {
  const data = useApi(() => api.get<AdminConf>("/admin/assistant"));
  const { run, busy } = useAction();
  const [draft, setDraft] = useState<Record<string, string>>({});
  useEffect(() => setDraft({}), [data.data]);
  if (data.error) return <ErrorNotice error={data.error} onRetry={data.reload} />;
  if (!data.data) return <Loading />;
  const d = data.data;
  const max = d.license.enabled ? RANK[d.license.maxMode] : -1;
  const save = () =>
    run(() => api.put<AdminConf>("/admin/assistant", { profiles: draft }), "Assistants IA enregistrés").then((v) => v && data.setData(v), () => undefined);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className={`callout ${d.license.enabled ? "ok" : "warn"}`}>
        {d.license.enabled ? (
          <>
            Licence <b>Assistants IA</b> active, accordée par le Pilote — mode maximal : <b>{SHORT[d.license.maxMode]}</b>.
          </>
        ) : (
          <>Votre entreprise ne dispose pas de la licence Assistants IA : demandez-la au Pilote de la plateforme.</>
        )}
        {" "}
        {d.llmConfigured ? "Moteur : IA Claude + données du projet." : "Moteur : analyse des données du projet (IA Claude activable par une clé serveur)."}
      </div>
      <Card title="Assistants IA par profil" sub="Chaque profil dispose de son assistant (chef de projet IA, Tech Lead IA, assistant d’équipe, client, commercial, direction). Choisissez son mode d’exécution.">
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Profil</th>
                <th>Assistant</th>
                {d.modes.map((m) => (
                  <th key={m.code} className="r">
                    {SHORT[m.code]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.profiles.map((p) => {
                const cur = draft[p.code] ?? p.mode;
                return (
                  <tr key={p.code}>
                    <td>
                      <b>{p.label}</b>
                      {!p.internal && <span className="pill info nodot" style={{ marginLeft: 6 }}>externe</span>}
                    </td>
                    <td className="muted">{p.assistant}</td>
                    {d.modes.map((m) => (
                      <td key={m.code} className="r">
                        <input type="radio" name={`mode-${p.code}`} aria-label={`${p.label} : ${SHORT[m.code]}`} checked={cur === m.code}
                          disabled={!d.license.enabled || RANK[m.code] > max} onChange={() => setDraft({ ...draft, [p.code]: m.code })} />
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <ul className="muted" style={{ fontSize: 12.5, margin: "12px 0 0", paddingLeft: 18 }}>
          {Object.entries(HELP).map(([k, v]) => (
            <li key={k}>
              <b>{SHORT[k]}</b> : {v}
            </li>
          ))}
        </ul>
        {Object.keys(draft).length > 0 && (
          <div className="btns" style={{ justifyContent: "flex-end", marginTop: 12 }}>
            <button className="btn primary" type="button" disabled={busy} onClick={save}>
              Enregistrer
            </button>
          </div>
        )}
      </Card>
    </div>
  );
}

type Tenant = { id: number; name: string; status: string };
type License = { tenant: string; enabled: boolean; maxMode: string };

/** Console Pilote : licence Assistants IA par entreprise (activation et mode maximal autorisé). */
export function AssistantPilotTab() {
  const tenants = useApi(() => api.get<Tenant[] | { results: Tenant[] }>("/platform/tenants"));
  const [lic, setLic] = useState<Record<number, License>>({});
  const { run, busy } = useAction();
  const list: Tenant[] = Array.isArray(tenants.data) ? tenants.data : (tenants.data?.results ?? []);
  useEffect(() => {
    list.forEach((t) => {
      if (!lic[t.id]) void api.get<License>(`/platform/tenants/${t.id}/assistant`).then((l) => setLic((o) => ({ ...o, [t.id]: l })), () => undefined);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenants.data]);
  if (tenants.error) return <ErrorNotice error={tenants.error} onRetry={tenants.reload} />;
  if (!tenants.data) return <Loading />;
  const save = (id: number, v: { enabled: boolean; maxMode: string }) =>
    run(() => api.put<License>(`/platform/tenants/${id}/assistant`, v), "Licence mise à jour").then((l) => l && setLic((o) => ({ ...o, [id]: l })), () => undefined);
  return (
    <Card title="Licences Assistants IA" sub="Activez les assistants IA par entreprise et fixez le mode maximal : l’administrateur de l’entreprise règle ensuite chaque profil dans cette limite.">
      <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>Entreprise</th>
              <th>Licence</th>
              <th>Mode maximal autorisé</th>
            </tr>
          </thead>
          <tbody>
            {list.map((t) => {
              const l = lic[t.id];
              return (
                <tr key={t.id}>
                  <td>
                    <b>{t.name}</b>
                  </td>
                  <td>
                    {l ? (
                      <label style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                        <input type="checkbox" checked={l.enabled} disabled={busy} onChange={(e) => save(t.id, { enabled: e.target.checked, maxMode: l.maxMode })} />
                        {l.enabled ? "Activée" : "Non accordée"}
                      </label>
                    ) : (
                      "…"
                    )}
                  </td>
                  <td>
                    {l && (
                      <select className="inp" style={{ maxWidth: 260 }} value={l.maxMode} disabled={busy || !l.enabled} onChange={(e) => save(t.id, { enabled: l.enabled, maxMode: e.target.value })}>
                        <option value="semi">Semi-automatique (validation humaine)</option>
                        <option value="auto">Automatique (remplace le chef de projet)</option>
                      </select>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
