import { useEffect, useState } from "react";

import { adminApi, delegationApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Loading, useAction } from "../../components/ui";

/** Délégation des droits d'administration : par rôle, puis exceptions individuelles. Les privilèges du Pilote n'y figurent pas. */
export function DelegationTab() {
  const matrix = useApi(delegationApi.matrix);
  const users = useApi(adminApi.users);
  const { run, busy } = useAction();
  const [draft, setDraft] = useState<Record<string, string[]>>({});
  const [userId, setUserId] = useState("");
  const userCaps = useApi(() => (userId ? delegationApi.ofUser(Number(userId)) : Promise.resolve(null)), [userId]);
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (matrix.data)
      setDraft(Object.fromEntries(matrix.data.roles.filter((r) => !r.locked).map((r) => [r.code, r.capabilities])));
  }, [matrix.data]);
  useEffect(() => {
    setOverrides(Object.fromEntries((userCaps.data?.overrides ?? []).map((o) => [o.code, o.granted])));
  }, [userCaps.data]);

  if (matrix.error) return <ErrorNotice error={matrix.error} onRetry={matrix.reload} />;
  if (!matrix.data) return <Loading />;
  const { catalog, roles } = matrix.data;
  const toggle = (role: string, code: string) =>
    setDraft((d) => ({
      ...d,
      [role]: d[role].includes(code) ? d[role].filter((c) => c !== code) : [...d[role], code],
    }));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Card
        title="Droits d'administration par rôle"
        sub="Délégation à l'intérieur de votre entreprise. L'administrateur garde tous les droits ; « Rôles et permissions » ne se délègue pas."
        extra={
          <button
            className="btn primary sm"
            disabled={busy}
            onClick={() =>
              run(() => delegationApi.setMatrix(draft), "Délégations enregistrées").then(matrix.reload, () => undefined)
            }
          >
            Enregistrer
          </button>
        }
      >
        <div className="tbl-wrap">
          <table className="tbl tight matrix">
            <thead>
              <tr>
                <th>Droit</th>
                {roles.map((r) => (
                  <th key={r.code} style={{ textAlign: "center" }}>
                    {r.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {catalog.map((c) => (
                <tr key={c.code}>
                  <td>
                    <b>{c.domain}</b> · {c.action}
                  </td>
                  {roles.map((r) => (
                    <td key={r.code} style={{ textAlign: "center" }}>
                      <input
                        type="checkbox"
                        aria-label={`${r.label} : ${c.domain} · ${c.action}`}
                        disabled={r.locked || !c.delegable}
                        checked={r.locked ? true : (draft[r.code] ?? []).includes(c.code)}
                        onChange={() => toggle(r.code, c.code)}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card
        title="Exceptions individuelles"
        sub="Accorder ou retirer un droit à une personne précise, en plus de son rôle."
      >
        <Field id="dl-u" label="Utilisateur">
          <select id="dl-u" className="inp" value={userId} onChange={(e) => setUserId(e.target.value)}>
            <option value="">Choisir…</option>
            {(users.data ?? [])
              .filter((u) => u.isActive)
              .map((u) => (
                <option key={u.id} value={u.id}>
                  {u.username} · {u.role}
                </option>
              ))}
          </select>
        </Field>
        {userId && userCaps.data && (
          <>
            <table className="tbl tight" style={{ marginTop: 12 }}>
              <tbody>
                {catalog
                  .filter((c) => c.delegable)
                  .map((c) => {
                    const value = c.code in overrides ? (overrides[c.code] ? "grant" : "deny") : "inherit";
                    return (
                      <tr key={c.code}>
                        <td>
                          <b>{c.domain}</b> · {c.action}
                        </td>
                        <td className="muted">
                          {userCaps.data!.effective.includes(c.code) ? "accordé actuellement" : "non accordé"}
                        </td>
                        <td>
                          <select
                            className="inp"
                            aria-label={`Exception ${c.domain} · ${c.action}`}
                            value={value}
                            onChange={(e) => {
                              const next = { ...overrides };
                              if (e.target.value === "inherit") delete next[c.code];
                              else next[c.code] = e.target.value === "grant";
                              setOverrides(next);
                            }}
                          >
                            <option value="inherit">Selon le rôle</option>
                            <option value="grant">Accorder</option>
                            <option value="deny">Retirer</option>
                          </select>
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
            <button
              className="btn primary"
              style={{ marginTop: 12 }}
              disabled={busy}
              onClick={() =>
                run(
                  () =>
                    delegationApi.setUser(
                      Number(userId),
                      Object.entries(overrides).map(([code, granted]) => ({ code, granted })),
                    ),
                  "Exceptions enregistrées",
                ).then(
                  (r) => r && userCaps.setData(r),
                  () => undefined,
                )
              }
            >
              Enregistrer les exceptions
            </button>
          </>
        )}
      </Card>
    </div>
  );
}
