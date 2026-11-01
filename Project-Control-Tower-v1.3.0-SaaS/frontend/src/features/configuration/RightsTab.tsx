import { useState } from "react";

import { adminApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Icon, Loading, useAction } from "../../components/ui";
import type { Flags } from "../../types/api";

/** Matrice des droits par rôle, comme l'onglet « Matrice des droits » de index.html, mais appliquée par l'API. */
export function RightsTab() {
  const roles = useApi(adminApi.roles);
  const [code, setCode] = useState("techlead");
  const [draft, setDraft] = useState<Record<string, Flags> | null>(null);
  const { run, busy } = useAction();

  if (roles.error) return <ErrorNotice error={roles.error} onRetry={roles.reload} />;
  if (!roles.data) return <Loading />;
  const role = roles.data.roles.find((r) => r.code === code) ?? roles.data.roles[0];
  const perms = draft ?? role.permissions;

  function toggle(module: string, i: number, value: boolean) {
    const next = { ...perms, [module]: perms[module].map((f, j) => (j === i ? value : f)) as Flags };
    setDraft(next);
  }

  async function save() {
    if (!draft) return;
    await run(() => adminApi.setPermissions(role.code, draft), `Droits du rôle ${role.label} enregistrés`).catch(
      () => undefined,
    );
    setDraft(null);
    roles.reload();
  }

  return (
    <Card
      title="Matrice des droits"
      sub="Droits de chaque rôle, vérifiés par l'API à chaque requête. Le périmètre (projets et tâches) se règle par utilisateur."
      extra={
        <div className="btns">
          <label
            className="mono muted"
            htmlFor="mRole"
            style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".06em" }}
          >
            Rôle
          </label>
          <select
            id="mRole"
            className="inp"
            style={{ width: "auto" }}
            value={role.code}
            onChange={(e) => {
              setCode(e.target.value);
              setDraft(null);
            }}
          >
            {roles.data.roles.map((r) => (
              <option key={r.code} value={r.code}>
                {r.label} ({r.userCount})
              </option>
            ))}
          </select>
          <button className="btn primary" onClick={save} disabled={!draft || busy}>
            Enregistrer
          </button>
        </div>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Module</th>
                {roles.data.verbs.map((v) => (
                  <th key={v.code} style={{ textAlign: "center" }}>
                    {v.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {roles.data.modules.map((m) => (
                <tr key={m.code}>
                  <td>
                    <b>{m.label}</b>
                  </td>
                  {roles.data!.verbs.map((v, i) => (
                    <td key={v.code} style={{ textAlign: "center" }}>
                      <span className="perm">
                        <input
                          type="checkbox"
                          aria-label={`${m.label} ${v.label}`}
                          checked={perms[m.code]?.[i] ?? false}
                          onChange={(e) => toggle(m.code, i, e.target.checked)}
                        />
                      </span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="notice">
          <Icon name="shield" size={15} /> Le rôle Administrateur ouvre le module Configuration quelle que soit cette
          matrice. Les accès au budget et aux marges dépendent aussi du profil du rôle (
          {role.money ? "budget visible" : "budget masqué"}, {role.margin ? "marges visibles" : "marges masquées"}).
        </div>
      </div>
    </Card>
  );
}
