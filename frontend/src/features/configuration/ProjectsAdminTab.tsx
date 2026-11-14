import { useState } from "react";

import { api } from "../../api/client";
import { adminApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Loading, useAction } from "../../components/ui";
import type { AdminProject, Me } from "../../types/api";

const EMPTY = { code: "", name: "", client: "", method: "", description: "", startDate: "", endDate: "", pm: "", tl: "", projectType: "new", baseProject: "", baseVersion: "" };
const METHODS = ["Scrum", "Cycle en V", "Kanban", "Hybride", "Régie"];
const NEW_CLIENT = "__new__";

/** Code projet proposé à partir du nom : « Refonte site client » → « REFONTESITE ». */
function suggestCode(name: string) {
  return name
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^A-Za-z0-9 ]/g, "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 3)
    .join("")
    .toUpperCase()
    .slice(0, 12);
}

export function ProjectsAdminTab({ me }: { me: Me }) {
  const projects = useApi(adminApi.projects);
  const clients = useApi(adminApi.projectClients);
  const users = useApi(adminApi.users);
  const roles = useApi(adminApi.roles);
  const { run, busy } = useAction();
  const [form, setForm] = useState(EMPTY);
  const [codeTouched, setCodeTouched] = useState(false);
  const [newClient, setNewClient] = useState("");
  const [notice, setNotice] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<AdminProject | null>(null);

  if (projects.error) return <ErrorNotice error={projects.error} onRetry={projects.reload} />;
  if (!projects.data || !clients.data || !users.data)
    return (
      <>
        {clients.error && <ErrorNotice error={clients.error} onRetry={clients.reload} />}
        {users.error && <ErrorNotice error={users.error} onRetry={users.reload} />}
        <Loading />
      </>
    );

  const set = (key: keyof typeof EMPTY) => (event: { target: { value: string } }) =>
    setForm((old) => ({ ...old, [key]: event.target.value }));
  const setName = (value: string) =>
    setForm((old) => ({ ...old, name: value, code: codeTouched ? old.code : suggestCode(value) }));
  const addingClient = form.client === NEW_CLIENT;
  const company = me.tenant?.name ?? "Mon entreprise";
  // Le client de l'entreprise elle-même n'apparaît qu'une fois : comme choix par défaut.
  const otherClients = clients.data.filter((c) => c.name.toLowerCase() !== company.toLowerCase());
  const activeUsers = users.data.filter((u) => u.isActive);
  // Seuls les profils Chef de projet / Tech Lead (rôle standard ou profil personnalisé du même nom) sont proposés.
  const roleLabel = (code: string) => roles.data?.roles.find((r) => r.code === code)?.label ?? code;
  const hasRole = (code: string, codes: string[], labels: string[]) =>
    codes.includes(code) || labels.some((l) => roleLabel(code).toLowerCase().includes(l));
  const pmChoices = activeUsers.filter((u) => hasRole(u.role, ["cdp"], ["chef de projet"]));
  const tlChoices = activeUsers.filter((u) => hasRole(u.role, ["techlead"], ["tech lead", "techlead"]));
  const label = (u: (typeof activeUsers)[number]) => [u.firstName, u.lastName].filter(Boolean).join(" ") || u.username;

  const createClient = () =>
    run(() => adminApi.createClient({ name: newClient.trim() }), "Client ajouté").then(
      (created) => {
        if (!created) return;
        setNewClient("");
        clients.reload();
        setForm((old) => ({ ...old, client: created.code }));
      },
      () => undefined,
    );

  const createProject = () =>
    run(
      () => adminApi.createProject({ ...form, pm: form.pm ? Number(form.pm) : null, tl: form.tl ? Number(form.tl) : null, baseProject: form.baseProject || null }),
      "Projet créé",
    ).then(
      (created) => {
        if (!created) return;
        setNotice(`Projet ${created.code} créé : vous, le chef de projet et le Tech Lead y avez accès.`);
        close();
        projects.reload();
      },
      () => undefined,
    );

  const canCreate = !busy && form.code.trim() && form.name.trim() && form.client !== NEW_CLIENT;

  const close = () => {
    setOpen(false);
    setEditing(null);
    setForm(EMPTY);
    setCodeTouched(false);
  };
  const startEdit = (p: AdminProject) => {
    setForm({
      code: p.code,
      name: p.name,
      client: p.client.name.toLowerCase() === company.toLowerCase() ? "" : p.client.code,
      method: p.method ?? "",
      description: p.description ?? "",
      startDate: p.startDate ?? "",
      endDate: p.endDate ?? "",
      pm: p.pm ? String(p.pm.id) : "",
      tl: p.tl ? String(p.tl.id) : "",
      projectType: p.projectType ?? "new",
      baseProject: p.baseProject ?? "",
      baseVersion: p.baseVersion ?? "",
    });
    setCodeTouched(true);
    setEditing(p);
    setOpen(true);
    setNotice("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const updateProject = () =>
    editing &&
    run(
      () =>
        adminApi.updateProject(editing.id, {
          name: form.name,
          client: form.client,
          method: form.method,
          description: form.description,
          startDate: form.startDate,
          endDate: form.endDate,
          pm: form.pm ? Number(form.pm) : null,
          tl: form.tl ? Number(form.tl) : null,
          projectType: form.projectType,
          baseProject: form.baseProject || null,
          baseVersion: form.baseVersion,
        }),
      "Projet modifié",
    ).then(
      (saved) => {
        if (!saved) return;
        setNotice(`Projet ${saved.code} mis à jour.`);
        close();
        projects.reload();
      },
      () => undefined,
    );
  // Un responsable déjà affecté reste visible même si son profil a changé depuis.
  const withCurrent = (list: typeof activeUsers, current?: { id: number; name: string } | null) =>
    current && !list.some((u) => u.id === current.id)
      ? [...list, { id: current.id, firstName: current.name, lastName: "", username: current.name } as (typeof activeUsers)[number]]
      : list;
  const pmList = withCurrent(pmChoices, editing?.pm);
  const tlList = withCurrent(tlChoices, editing?.tl);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {notice && (
        <div className="callout ok" role="status">
          {notice}
        </div>
      )}
      <Card
        title="Projets de l’entreprise"
        sub={`${projects.data.length} projet${projects.data.length > 1 ? "s" : ""} · l’accès de chaque utilisateur se règle dans « Utilisateurs et accès ».`}
        extra={
          !open && (
            <button className="btn primary" type="button" onClick={() => setOpen(true)}>
              + Nouveau projet
            </button>
          )
        }
      >
        {open && (
          <div className="proj-form">
            <h3>{editing ? `Modifier le projet ${editing.code}` : "Nouveau projet"}</h3>
            <div className="frow">
              <Field id="new-project-name" label="Nom du projet *">
                <input id="new-project-name" className="inp" maxLength={200} value={form.name} autoFocus
                  placeholder="Ex. Refonte du portail client" onChange={(e) => setName(e.target.value)} />
              </Field>
              <Field id="new-project-code" label="Code *">
                <input id="new-project-code" className="inp mono" maxLength={20} value={form.code} disabled={!!editing}
                  onChange={(e) => { setCodeTouched(true); set("code")(e); }} />
              </Field>
            </div>
            <div className="frow">
              <Field id="new-project-type" label="Type de projet *">
                <select id="new-project-type" className="inp" value={form.projectType} onChange={set("projectType")}>
                  <option value="new">Nouveau projet (from scratch)</option>
                  <option value="evolution">Évolution d’un projet existant</option>
                  <option value="improvement">Amélioration d’un projet existant</option>
                </select>
              </Field>
              {form.projectType !== "new" && (
                <>
                  <Field id="new-project-base" label="Projet existant concerné">
                    <select id="new-project-base" className="inp" value={form.baseProject} onChange={set("baseProject")}>
                      <option value="">Non précisé</option>
                      {projects.data.filter((x) => x.id !== editing?.id).map((x) => (
                        <option key={x.id} value={x.id}>
                          {x.code} — {x.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field id="new-project-version" label="Version concernée">
                    <input id="new-project-version" className="inp" maxLength={40} placeholder="Ex. v2.3" value={form.baseVersion} onChange={set("baseVersion")} />
                  </Field>
                </>
              )}
            </div>
            <div className="frow">
              <Field id="new-project-client" label="Client">
                <select id="new-project-client" className="inp" value={form.client} onChange={set("client")}>
                  <option value="">{company} (votre entreprise)</option>
                  {otherClients.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.name}
                    </option>
                  ))}
                  <option value={NEW_CLIENT}>+ Autre client…</option>
                </select>
              </Field>
              <Field id="new-project-method" label="Méthode">
                <select id="new-project-method" className="inp" value={form.method} onChange={set("method")}>
                  <option value="">Non précisée</option>
                  {METHODS.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            {addingClient && (
              <div className="proj-newclient">
                <Field id="new-client-name" label="Nom du nouveau client">
                  <input id="new-client-name" className="inp" maxLength={120} value={newClient} placeholder="Ex. Banque Atlas"
                    onChange={(e) => setNewClient(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && newClient.trim()) createClient(); }} />
                </Field>
                <button className="btn" type="button" disabled={busy || !newClient.trim()} onClick={createClient}>
                  Ajouter le client
                </button>
              </div>
            )}
            <div className="frow">
              <Field id="new-project-pm" label="Chef de projet">
                <select id="new-project-pm" className="inp" value={form.pm} onChange={set("pm")}>
                  <option value="">{pmList.length ? "Non affecté" : "Aucun profil Chef de projet"}</option>
                  {pmList.map((u) => (
                    <option key={u.id} value={u.id}>
                      {label(u)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field id="new-project-tl" label="Tech Lead">
                <select id="new-project-tl" className="inp" value={form.tl} onChange={set("tl")}>
                  <option value="">{tlList.length ? "Non affecté" : "Aucun profil Tech Lead"}</option>
                  {tlList.map((u) => (
                    <option key={u.id} value={u.id}>
                      {label(u)}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            {(pmChoices.length === 0 || tlChoices.length === 0) && (
              <p className="muted" style={{ fontSize: 12.5, margin: "-4px 0 0" }}>
                Seuls les comptes ayant le profil Chef de projet ou Tech Lead sont proposés. Attribuez ces profils dans « Utilisateurs et accès ».
              </p>
            )}
            <div className="frow">
              <Field id="new-project-start" label="Début">
                <input id="new-project-start" className="inp" type="date" value={form.startDate} onChange={set("startDate")} />
              </Field>
              <Field id="new-project-end" label="Fin">
                <input id="new-project-end" className="inp" type="date" value={form.endDate} onChange={set("endDate")} />
              </Field>
            </div>
            <Field id="new-project-description" label="Description">
              <textarea id="new-project-description" className="inp" rows={2} value={form.description} onChange={set("description")} />
            </Field>
            <div className="btns" style={{ justifyContent: "flex-end" }}>
              <button className="btn ghost" type="button" onClick={close}>
                Annuler
              </button>
              <button className="btn primary" type="button" disabled={!canCreate} onClick={editing ? updateProject : createProject}>
                {busy ? "Enregistrement…" : editing ? "Enregistrer les modifications" : "Créer le projet"}
              </button>
            </div>
          </div>
        )}
        {projects.data.length === 0 ? (
          !open && (
            <div className="empty">
              Aucun projet pour l’instant. Cliquez sur <b>+ Nouveau projet</b> pour créer le premier.
            </div>
          )
        ) : (
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Projet</th>
                  <th>Client</th>
                  <th>Type</th>
                  <th>Chef de projet</th>
                  <th>Tech Lead</th>
                  <th className="r">Tâches</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {projects.data.map((p) => (
                  <tr key={p.id}>
                    <td className="mono">{p.code}</td>
                    <td>{p.name}</td>
                    <td>{p.client.name}</td>
                    <td className="muted">{p.projectTypeLabel ?? "—"}{p.baseVersion ? ` (${p.baseVersion})` : ""}</td>
                    <td>{p.pm?.name ?? <span className="faint">Non affecté</span>}</td>
                    <td>{p.tl?.name ?? <span className="faint">Non affecté</span>}</td>
                    <td className="r">{p.actions.length}</td>
                    <td className="r">
                      <button className="btn sm" type="button" disabled={busy} onClick={() => startEdit(p)}>
                        Modifier
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <DocKeywordsCard />
    </div>
  );
}

/** Mots-clés par type de document : servent à classer automatiquement les documents déposés dans les projets. */
function DocKeywordsCard() {
  const data = useApi(() => api.get<{ types: { code: string; label: string; keywords: string[] }[] }>("/admin/doc-keywords"));
  const { run, busy } = useAction();
  const [edit, setEdit] = useState<Record<string, string>>({});
  if (data.error) return <ErrorNotice error={data.error} onRetry={data.reload} />;
  if (!data.data) return null;
  const value = (code: string, kws: string[]) => edit[code] ?? kws.join(", ");
  const save = () =>
    run(
      () =>
        api.put<{ types: { code: string; label: string; keywords: string[] }[] }>("/admin/doc-keywords", {
          keywords: Object.fromEntries(data.data!.types.map((t) => [t.code, value(t.code, t.keywords).split(",").map((w) => w.trim()).filter(Boolean)])),
        }),
      "Mots-clés enregistrés",
    ).then((v) => { if (v) { data.setData(v); setEdit({}); } }, () => undefined);
  return (
    <Card title="Classification des documents" sub="Mots-clés recherchés dans le nom et le contenu des documents déposés (séparés par des virgules). Le type ayant le plus de correspondances est proposé.">
      <div className="kw-grid">
        {data.data.types.map((t) => (
          <Field key={t.code} id={`kw-${t.code}`} label={t.label}>
            <textarea id={`kw-${t.code}`} className="inp" rows={2} value={value(t.code, t.keywords)} onChange={(e) => setEdit({ ...edit, [t.code]: e.target.value })} />
          </Field>
        ))}
      </div>
      {Object.keys(edit).length > 0 && (
        <div className="btns" style={{ justifyContent: "flex-end", marginTop: 12 }}>
          <button className="btn primary" type="button" disabled={busy} onClick={save}>
            Enregistrer les mots-clés
          </button>
        </div>
      )}
    </Card>
  );
}
