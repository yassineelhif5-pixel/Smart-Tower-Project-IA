import { useState } from "react";

import { adminApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Icon, Loading, Modal, useAction } from "../../components/ui";
import type { Flags } from "../../types/api";

/** Matrice des droits par rôle, comme l'onglet « Matrice des droits » de index.html, mais appliquée par l'API. */
export function RightsTab() {
  const roles = useApi(adminApi.roles);
  const [code, setCode] = useState("techlead");
  const [draft, setDraft] = useState<Record<string, Flags> | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [profile, setProfile] = useState({ label: "", question: "", internal: true, money: false, margin: false });
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

  async function createProfile() {
    if (!profile.label.trim()) return;
    const created = await run(() => adminApi.createRole({ ...profile, label: profile.label.trim() }), "Profil créé").catch(
      () => undefined,
    );
    if (!created) return;
    setCode(created.code);
    setDraft(null);
    setProfile({ label: "", question: "", internal: true, money: false, margin: false });
    setCreateOpen(false);
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
          <button className="btn" onClick={() => setCreateOpen(true)}>Créer un profil</button>
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
      {createOpen && (
        <Modal
          title="Créer un profil"
          onClose={() => setCreateOpen(false)}
          footer={
            <>
              <button className="btn" onClick={() => setCreateOpen(false)}>Annuler</button>
              <button className="btn primary" onClick={createProfile} disabled={busy || !profile.label.trim()}>
                Créer le profil
              </button>
            </>
          }
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <Field id="profile-label" label="Nom du profil">
              <input className="inp" id="profile-label" maxLength={60} value={profile.label}
                onChange={(e) => setProfile({ ...profile, label: e.target.value })} />
            </Field>
            <Field id="profile-question" label="Description ou consigne (facultatif)">
              <input className="inp" id="profile-question" maxLength={200} value={profile.question}
                onChange={(e) => setProfile({ ...profile, question: e.target.value })} />
            </Field>
            <label style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 13 }}><input type="checkbox" checked={profile.internal}
              onChange={(e) => setProfile({ ...profile, internal: e.target.checked })} /> Profil interne (sinon, accès portail client)</label>
            <label style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 13 }}><input type="checkbox" checked={profile.money}
              onChange={(e) => setProfile({ ...profile, money: e.target.checked })} /> Autoriser la visibilité du budget</label>
            <label style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 13 }}><input type="checkbox" checked={profile.margin}
              onChange={(e) => setProfile({ ...profile, margin: e.target.checked })} /> Autoriser la visibilité des marges et du chiffre d’affaires</label>
            <div className="notice">Les droits des modules sont fermés au départ. Après création, sélectionnez les autorisations dans la matrice puis enregistrez-les. Vous pourrez ensuite affecter ce profil aux utilisateurs.</div>
          </div>
        </Modal>
      )}
    </Card>
  );
}
