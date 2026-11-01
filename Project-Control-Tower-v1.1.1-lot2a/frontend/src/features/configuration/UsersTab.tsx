import { useMemo, useState } from "react";

import { ApiError } from "../../api/client";
import { adminApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import {
  Card,
  ErrorNotice,
  Field,
  fmtDate,
  Loading,
  Modal,
  OneTimeSecret,
  Pill,
  Switch,
  useAction,
} from "../../components/ui";
import type { Access, AdminProject, AdminUser, Me, Role, UserInput } from "../../types/api";

type Editing = { mode: "create" } | { mode: "edit"; user: AdminUser } | { mode: "access"; user: AdminUser } | null;

export function UsersTab({ me }: { me: Me }) {
  const users = useApi(adminApi.users);
  const roles = useApi(adminApi.roles);
  const [editing, setEditing] = useState<Editing>(null);
  const [secret, setSecret] = useState<{ user: string; value: string } | null>(null);
  const [filter, setFilter] = useState("");
  const { run } = useAction();

  const roleLabel = useMemo(
    () => Object.fromEntries((roles.data?.roles ?? []).map((r) => [r.code, r.label])),
    [roles.data],
  );
  const list = (users.data ?? []).filter((u) =>
    `${u.username} ${u.firstName} ${u.lastName} ${u.email} ${roleLabel[u.role] ?? ""}`
      .toLowerCase()
      .includes(filter.toLowerCase()),
  );

  if (users.error) return <ErrorNotice error={users.error} onRetry={users.reload} />;
  if (users.loading && !users.data) return <Loading />;

  async function reset(user: AdminUser) {
    const r = await run(() => adminApi.resetPassword(user.id), "Mot de passe réinitialisé").catch(() => undefined);
    if (r) {
      setSecret({ user: user.username, value: r.temporaryPassword });
      users.reload();
    }
  }

  async function toggleActive(user: AdminUser) {
    await run(
      () => adminApi.updateUser(user.id, { isActive: !user.isActive }),
      user.isActive ? "Compte désactivé" : "Compte réactivé",
    ).catch(() => undefined);
    users.reload();
  }

  return (
    <>
      <Card
        title="Comptes utilisateurs"
        sub={`${users.data?.filter((u) => u.isActive).length ?? 0} comptes actifs · un nouveau compte reçoit un mot de passe provisoire à changer à la première connexion`}
        extra={
          <div className="btns">
            <input
              className="inp"
              placeholder="Rechercher…"
              aria-label="Rechercher un utilisateur"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              style={{ width: 200 }}
            />
            <button className="btn primary" onClick={() => setEditing({ mode: "create" })}>
              Créer un compte
            </button>
          </div>
        }
      >
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Utilisateur</th>
                <th>Rôle</th>
                <th className="r">Projets</th>
                <th>Dernière connexion</th>
                <th>Statut</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.map((u) => (
                <tr key={u.id}>
                  <td className="cell-main">
                    <b>{[u.firstName, u.lastName].filter(Boolean).join(" ") || u.username}</b>
                    <small className="muted mono">
                      {u.username}
                      {u.email && ` · ${u.email}`}
                    </small>
                  </td>
                  <td>
                    {u.role === "admin" ? <Pill tone="acc">{roleLabel[u.role]}</Pill> : (roleLabel[u.role] ?? u.role)}
                  </td>
                  <td className="r mono">{["admin", "direction"].includes(u.role) ? "tous" : u.projectCount}</td>
                  <td className="muted">{fmtDate(u.lastLogin)}</td>
                  <td>
                    {!u.isActive ? (
                      <Pill tone="">Désactivé</Pill>
                    ) : u.mustChangePassword ? (
                      <Pill tone="warn">Mot de passe provisoire</Pill>
                    ) : (
                      <Pill tone="ok">Actif</Pill>
                    )}
                  </td>
                  <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                    <button className="btn sm" onClick={() => setEditing({ mode: "edit", user: u })}>
                      Modifier
                    </button>{" "}
                    <button className="btn sm" onClick={() => setEditing({ mode: "access", user: u })}>
                      Accès
                    </button>{" "}
                    <button className="btn sm ghost" onClick={() => reset(u)}>
                      Réinitialiser
                    </button>{" "}
                    {u.id !== me.id && (
                      <button className={`btn sm ${u.isActive ? "danger" : ""}`} onClick={() => toggleActive(u)}>
                        {u.isActive ? "Désactiver" : "Réactiver"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {editing?.mode !== "access" && editing && roles.data && (
        <UserForm
          user={editing.mode === "edit" ? editing.user : null}
          roles={roles.data.roles}
          isSelf={editing.mode === "edit" && editing.user.id === me.id}
          onClose={() => setEditing(null)}
          onSaved={(temporary, username) => {
            setEditing(null);
            users.reload();
            if (temporary) setSecret({ user: username, value: temporary });
          }}
        />
      )}
      {editing?.mode === "access" && (
        <AccessEditor
          user={editing.user}
          fullScope={["admin", "direction"].includes(editing.user.role)}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            users.reload();
          }}
        />
      )}
      {secret && (
        <Modal
          title={`Mot de passe provisoire · ${secret.user}`}
          onClose={() => setSecret(null)}
          footer={
            <button className="btn primary" onClick={() => setSecret(null)}>
              J'ai noté le mot de passe
            </button>
          }
        >
          <OneTimeSecret label="Mot de passe provisoire." value={secret.value} />
          <p className="muted" style={{ margin: "10px 0 0", fontSize: 13 }}>
            Transmettez-le par un canal sûr. L'utilisateur devra en choisir un nouveau à sa première connexion.
          </p>
        </Modal>
      )}
    </>
  );
}

function UserForm({
  user,
  roles,
  isSelf,
  onClose,
  onSaved,
}: {
  user: AdminUser | null;
  roles: Role[];
  isSelf: boolean;
  onClose: () => void;
  onSaved: (temporary: string | null, username: string) => void;
}) {
  const clients = useApi(adminApi.projects);
  const [form, setForm] = useState<UserInput>(
    user ?? {
      username: "",
      firstName: "",
      lastName: "",
      email: "",
      role: "consultant",
      title: "",
      team: "",
      client: null,
      password: "",
    },
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const { run, busy } = useAction();
  const role = roles.find((r) => r.code === form.role);
  const clientOptions = useMemo(() => {
    const seen = new Map<string, string>();
    (clients.data ?? []).forEach((p: AdminProject) => seen.set(p.client.code, p.client.name));
    return [...seen];
  }, [clients.data]);
  const set = <K extends keyof UserInput>(key: K, value: UserInput[K]) => setForm((f) => ({ ...f, [key]: value }));

  async function save() {
    setErrors({});
    const payload: UserInput = { ...form, client: role?.internal ? null : form.client };
    if (!payload.password) delete payload.password;
    try {
      if (user) {
        delete payload.password;
        const saved = await run(() => adminApi.updateUser(user.id, payload), "Compte enregistré");
        if (saved) onSaved(null, saved.username);
      } else {
        const created = await run(() => adminApi.createUser(payload), "Compte créé");
        if (created) onSaved(created.temporaryPassword, created.username);
      }
    } catch (e) {
      if (e instanceof ApiError) setErrors(e.fieldErrors());
    }
  }

  return (
    <Modal
      title={user ? `Modifier · ${user.username}` : "Créer un compte"}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            Annuler
          </button>
          <button className="btn primary" onClick={save} disabled={busy}>
            {user ? "Enregistrer" : "Créer le compte"}
          </button>
        </>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="frow">
          <Field id="u_first" label="Prénom" error={errors.firstName}>
            <input
              id="u_first"
              className="inp"
              value={form.firstName ?? ""}
              onChange={(e) => set("firstName", e.target.value)}
            />
          </Field>
          <Field id="u_last" label="Nom" error={errors.lastName}>
            <input
              id="u_last"
              className="inp"
              value={form.lastName ?? ""}
              onChange={(e) => set("lastName", e.target.value)}
            />
          </Field>
        </div>
        <div className="frow">
          <Field id="u_username" label="Identifiant de connexion" error={errors.username}>
            <input
              id="u_username"
              className="inp mono"
              value={form.username ?? ""}
              onChange={(e) => set("username", e.target.value)}
              disabled={!!user}
            />
          </Field>
          <Field id="u_email" label="E-mail" error={errors.email}>
            <input
              id="u_email"
              className="inp"
              type="email"
              value={form.email ?? ""}
              onChange={(e) => set("email", e.target.value)}
            />
          </Field>
        </div>
        <div className="frow">
          <Field
            id="u_role"
            label="Rôle"
            error={errors.role}
            hint={
              isSelf
                ? "Vous ne pouvez pas retirer votre propre rôle d'administrateur."
                : role?.code === "admin"
                  ? "Accès au module Configuration et à tous les projets."
                  : undefined
            }
          >
            <select
              id="u_role"
              className="inp"
              value={form.role}
              onChange={(e) => set("role", e.target.value)}
              disabled={isSelf}
            >
              {roles.map((r) => (
                <option key={r.code} value={r.code}>
                  {r.label}
                </option>
              ))}
            </select>
          </Field>
          {role && !role.internal && (
            <Field id="u_client" label="Client rattaché" error={errors.client}>
              <select
                id="u_client"
                className="inp"
                value={form.client ?? ""}
                onChange={(e) => set("client", e.target.value || null)}
              >
                <option value="">Choisir…</option>
                {clientOptions.map(([code, name]) => (
                  <option key={code} value={code}>
                    {name}
                  </option>
                ))}
              </select>
            </Field>
          )}
        </div>
        <div className="frow">
          <Field id="u_title" label="Fonction" error={errors.title}>
            <input
              id="u_title"
              className="inp"
              value={form.title ?? ""}
              onChange={(e) => set("title", e.target.value)}
            />
          </Field>
          <Field id="u_team" label="Équipe" error={errors.team}>
            <input id="u_team" className="inp" value={form.team ?? ""} onChange={(e) => set("team", e.target.value)} />
          </Field>
        </div>
        {!user && (
          <Field
            id="u_password"
            label="Mot de passe provisoire (facultatif)"
            error={errors.password}
            hint="Laissez vide pour en générer un. L'utilisateur devra le changer à sa première connexion."
          >
            <input
              id="u_password"
              className="inp"
              type="password"
              autoComplete="new-password"
              value={form.password ?? ""}
              onChange={(e) => set("password", e.target.value)}
            />
          </Field>
        )}
        {Object.keys(errors).some(
          (k) =>
            !["firstName", "lastName", "username", "email", "role", "client", "title", "team", "password"].includes(k),
        ) && (
          <div className="callout warn" role="alert">
            <b>{Object.values(errors).join(" ")}</b>
          </div>
        )}
      </div>
    </Modal>
  );
}

function AccessEditor({
  user,
  fullScope,
  onClose,
  onSaved,
}: {
  user: AdminUser;
  fullScope: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const projects = useApi(adminApi.projects);
  const current = useApi(() => adminApi.access(user.id), [user.id]);
  const [draft, setDraft] = useState<Access | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const { run, busy } = useAction();
  const access = draft ?? current.data;

  if (projects.error || current.error)
    return (
      <Modal title="Accès" onClose={onClose}>
        <ErrorNotice error={(projects.error ?? current.error)!} />
      </Modal>
    );

  const pMap = new Map(access?.projects.map((p) => [p.project, p.canEdit]));
  const aMap = new Map(access?.actions.map((a) => [a.action, a.canEdit]));
  const update = (next: Access) => setDraft(next);
  const toggleProject = (id: string, on: boolean) =>
    access &&
    update({
      ...access,
      projects: on
        ? [...access.projects, { project: id, canEdit: true }]
        : access.projects.filter((p) => p.project !== id),
    });
  const editProject = (id: string, canEdit: boolean) =>
    access && update({ ...access, projects: access.projects.map((p) => (p.project === id ? { ...p, canEdit } : p)) });
  const toggleAction = (id: string, on: boolean) =>
    access &&
    update({
      ...access,
      actions: on ? [...access.actions, { action: id, canEdit: false }] : access.actions.filter((a) => a.action !== id),
    });
  const editAction = (id: string, canEdit: boolean) =>
    access && update({ ...access, actions: access.actions.map((a) => (a.action === id ? { ...a, canEdit } : a)) });

  async function save() {
    if (!access) return;
    const saved = await run(
      () => adminApi.setAccess(user.id, access),
      "Accès enregistrés · l'utilisateur est notifié",
    ).catch(() => undefined);
    if (saved) onSaved();
  }

  return (
    <Modal
      wide
      title={`Accès aux projets et aux tâches · ${user.username}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            Annuler
          </button>
          <button className="btn primary" onClick={save} disabled={busy || !draft}>
            Enregistrer les accès
          </button>
        </>
      }
    >
      {!access || !projects.data ? (
        <Loading />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div className="notice">
            {fullScope
              ? "Ce rôle voit déjà tous les projets. Les affectations ci-dessous servent seulement si le rôle change."
              : "Les droits du rôle (matrice) s'appliquent en plus : « Écriture » n'autorise que ce que le rôle permet déjà. Une tâche ouverte seule rend visible cette tâche sans donner accès au reste du projet."}
          </div>
          <div className="tbl-wrap">
            <table className="tbl tight">
              <thead>
                <tr>
                  <th>Projet</th>
                  <th>Client</th>
                  <th style={{ textAlign: "center" }}>Accès</th>
                  <th style={{ textAlign: "center" }}>Écriture</th>
                  <th className="r">Tâches ouvertes seules</th>
                </tr>
              </thead>
              <tbody>
                {projects.data.map((p) => {
                  const has = pMap.has(p.id);
                  const singles = p.actions.filter((a) => aMap.has(a.id)).length;
                  return [
                    <tr key={p.id}>
                      <td className="cell-main">
                        <b>{p.name}</b>
                        <small className="mono muted">{p.code}</small>
                      </td>
                      <td>{p.client.name}</td>
                      <td style={{ textAlign: "center" }}>
                        <Switch label={`Accès à ${p.code}`} checked={has} onChange={(v) => toggleProject(p.id, v)} />
                      </td>
                      <td style={{ textAlign: "center" }}>
                        <Switch
                          label={`Écriture sur ${p.code}`}
                          checked={!!pMap.get(p.id)}
                          disabled={!has}
                          onChange={(v) => editProject(p.id, v)}
                        />
                      </td>
                      <td className="r">
                        <button
                          className="btn sm ghost"
                          onClick={() => setOpen(open === p.id ? null : p.id)}
                          aria-expanded={open === p.id}
                        >
                          {singles ? `${singles} tâche${singles > 1 ? "s" : ""}` : "Choisir"}{" "}
                          {open === p.id ? "▴" : "▾"}
                        </button>
                      </td>
                    </tr>,
                    open === p.id && (
                      <tr key={`${p.id}-a`}>
                        <td colSpan={5} style={{ background: "var(--surface-2)" }}>
                          <div className="list">
                            {p.actions.map((a) => (
                              <div className="li" key={a.id}>
                                <span className="tag mono">{a.id}</span>
                                <div className="grow">
                                  <b>{a.title}</b>
                                </div>
                                <label className="chk" style={{ padding: 0 }}>
                                  <input
                                    type="checkbox"
                                    checked={aMap.has(a.id)}
                                    onChange={(e) => toggleAction(a.id, e.target.checked)}
                                  />
                                  <span>Ouvrir</span>
                                </label>
                                <label className="chk" style={{ padding: 0 }}>
                                  <input
                                    type="checkbox"
                                    checked={!!aMap.get(a.id)}
                                    disabled={!aMap.has(a.id)}
                                    onChange={(e) => editAction(a.id, e.target.checked)}
                                  />
                                  <span>Écriture</span>
                                </label>
                              </div>
                            ))}
                          </div>
                        </td>
                      </tr>
                    ),
                  ];
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Modal>
  );
}
