// Espace client : CRA et factures mensuels (un par consultant, par client et par mois), validation des temps par le client,
// contrats de support N1/N2/N3 et paramètres de facturation. Les droits sont revérifiés par le serveur.
import { useEffect, useMemo, useState } from "react";

import { API_BASE, api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { ErrorNotice, Loading, PageHead, useAction } from "../../components/ui";
import type { Me } from "../../types/api";
import "./clientspace.css";
import { AiUsageReport } from "../aiusage/AiUsageReport";
import { PortalBilling, PortalOrders, PortalRecap, PortalTimesheets } from "./ClientPortal";

type Num = string | number | null;
type Doc = { id: string; kind: "cra" | "invoice"; kindLabel: string; client: string; clientName: string; period: string; periodLabel: string;
  person: string; personId: number | null; name: string; number: string; version: number; days: Num; amountHt: Num; vatRate: Num; amountTtc: Num;
  createdAt: string; projects: string[]; approvers: string[]; due?: string };
type Contract = { enabled: boolean; levels: string[]; startsOn: string | null; endsOn: string | null; members: { id: number; name: string; role: string }[]; rates?: Record<string, Num> };
type Space = { clients: { code: string; name: string; support: Contract }[]; documents: Doc[]; isClient: boolean; isAdmin: boolean;
  supportLicense: { enabled: boolean; levels: string[]; maxClients: number | null }; levels: { code: string; label: string }[];
  clientValidationPending: number; canGenerate: boolean; people: { id: number; name: string }[]; billing: Record<string, unknown> | null };
type Group = { client: string; clientName: string; person: number; personName: string; period: string; periodLabel: string; days: Num; hours: Num;
  projects: string[]; entries: { id?: number; date: string; project: string; task: string; hours: Num; approvedBy: string }[] };

const n = (v: Num) => Number(v ?? 0);
const eur = (v: Num) => (v === null || v === undefined ? "—" : n(v).toLocaleString("fr-FR", { style: "currency", currency: "EUR" }));
const dl = (id: string) => `${API_BASE}/client-space/documents/${encodeURIComponent(id)}`;

export function ClientSpacePage({ me }: { me: Me }) {
  const [client, setClient] = useState("");
  const [period, setPeriod] = useState("");
  const q = new URLSearchParams({ ...(client ? { client } : {}), ...(period ? { period } : {}) }).toString();
  const space = useApi(() => api.get<Space>(`/client-space?${q}`), [q]);
  const [tab, setTab] = useState<"docs" | "times" | "bills" | "validate" | "orders" | "recap" | "support" | "ai" | "billing">("docs");
  useEffect(() => { if (space.data?.isClient && space.data.clientValidationPending) setTab((t) => (t === "docs" ? "validate" : t)); }, [space.data?.isClient, space.data?.clientValidationPending]);
  if (space.error) return <div className="page"><ErrorNotice error={space.error} onRetry={space.reload} /></div>;
  if (!space.data) return <Loading />;
  const s = space.data;
  const tabs: [typeof tab, string][] = [["docs", "CRA et factures"], ["times", "Saisies & reporting"], ["bills", "Facturation par utilisateur"]];
  if (s.isClient || s.isAdmin) tabs.push(["validate", `Temps à valider${s.clientValidationPending ? ` (${s.clientValidationPending})` : ""}`]);
  tabs.push(["orders", "Commandes"], ["recap", "Récap e-mail"]);
  tabs.push(["support", "Support N1 / N2 / N3"]);
  tabs.push(["ai", "Consommation IA"]);
  if (s.isAdmin) tabs.push(["billing", "Facturation"]);
  return (
    <div className="page cs">
      <PageHead eyebrow={me.tenant?.name ?? ""} title="Espace client"
        sub="Un compte rendu d'activité et une facture par consultant, par client et par mois, tous projets confondus — générés automatiquement dès que le mois est entièrement validé. Lecture réservée au consultant, au chef de projet, au commercial et au client." />
      <div className="cs-tabs" role="tablist">
        {tabs.map(([k, l]) => <button key={k} type="button" role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      {tab === "docs" && <Documents s={s} client={client} setClient={setClient} period={period} setPeriod={setPeriod} reload={space.reload} />}
      {tab === "validate" && <Validation onDone={space.reload} />}
      {tab === "support" && <Support s={s} reload={space.reload} />}
      {tab === "ai" && <AiUsageReport />}
      {tab === "times" && <PortalTimesheets />}
      {tab === "bills" && <PortalBilling />}
      {tab === "orders" && <PortalOrders />}
      {tab === "recap" && <PortalRecap />}
      {tab === "billing" && s.billing && <><Billing conf={s.billing} reload={space.reload} /><ModuleProfiles /></>}
    </div>
  );
}

function Documents({ s, client, setClient, period, setPeriod, reload }: { s: Space; client: string; setClient: (v: string) => void; period: string; setPeriod: (v: string) => void; reload: () => void }) {
  const { run, busy } = useAction();
  const [gen, setGen] = useState<{ client: string; person: string; period: string; force: boolean } | null>(null);
  const rows = useMemo(() => {
    const m = new Map<string, { cra?: Doc; inv?: Doc }>();
    s.documents.forEach((d) => {
      const k = `${d.client}|${d.personId}|${d.period}`;
      const cur = m.get(k) ?? {};
      if (d.kind === "cra" && (!cur.cra || d.version > cur.cra.version)) cur.cra = d;
      if (d.kind === "invoice" && (!cur.inv || d.version > cur.inv.version)) cur.inv = d;
      m.set(k, cur);
    });
    return [...m.values()].filter((x) => x.cra || x.inv).sort((a, b) => ((b.cra ?? b.inv)!.period).localeCompare((a.cra ?? a.inv)!.period));
  }, [s.documents]);
  const totals = rows.reduce((t, r) => ({ ht: t.ht + n(r.inv?.amountHt ?? r.cra?.amountHt ?? 0), ttc: t.ttc + n(r.inv?.amountTtc ?? 0), days: t.days + n(r.cra?.days ?? 0) }), { ht: 0, ttc: 0, days: 0 });
  const generate = () => gen && void run(() => api.post<{ created: boolean }>("/client-space/generate", { ...gen, person: Number(gen.person) }), "CRA et facture générés")
    .then(() => { setGen(null); reload(); }, () => undefined);
  return (
    <section className="cs-card">
      <div className="cs-filters">
        <select className="inp" aria-label="Client" value={client} onChange={(e) => setClient(e.target.value)}>
          <option value="">Tous les clients</option>
          {s.clients.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
        </select>
        <input className="inp" type="month" aria-label="Mois" value={period} onChange={(e) => setPeriod(e.target.value)} />
        {period && <button type="button" className="btn sm" onClick={() => setPeriod("")}>Tous les mois</button>}
        <span className="cs-sum">{rows.length} CRA · {totals.days.toLocaleString("fr-FR")} j · {eur(totals.ht)} HT · {eur(totals.ttc)} TTC</span>
        {s.canGenerate && !gen && <button type="button" className="btn sm" onClick={() => setGen({ client: client || s.clients[0]?.code || "", person: "", period: period || new Date(new Date().getFullYear(), new Date().getMonth() - 1, 15).toISOString().slice(0, 7), force: false })}>⚙ Générer un CRA</button>}
      </div>
      {gen && (
        <form className="cs-gen" onSubmit={(e) => { e.preventDefault(); generate(); }}>
          <select className="inp" value={gen.client} onChange={(e) => setGen({ ...gen, client: e.target.value })} aria-label="Client">{s.clients.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}</select>
          <select className="inp" value={gen.person} onChange={(e) => setGen({ ...gen, person: e.target.value })} aria-label="Consultant">
            <option value="">Consultant…</option>{s.people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <input className="inp" type="month" value={gen.period} onChange={(e) => setGen({ ...gen, period: e.target.value })} aria-label="Mois" />
          <label className="cs-check"><input type="checkbox" checked={gen.force} onChange={(e) => setGen({ ...gen, force: e.target.checked })} /> Mois en cours (avant la fin du mois)</label>
          <button className="btn sm primary" type="submit" disabled={busy || !gen.person || !gen.client}>Générer</button>
          <button className="btn sm" type="button" onClick={() => setGen(null)}>Annuler</button>
          <small className="muted">Toutes les saisies du mois doivent être validées (CP{` puis client si le circuit l'exige`}).</small>
        </form>
      )}
      {rows.length === 0 ? <p className="muted">Aucun CRA pour l'instant : ils apparaissent automatiquement quand un mois est entièrement validé.</p> : (
        <div className="cs-table-wrap">
          <table className="tbl cs-table">
            <thead><tr><th>Mois</th><th>Consultant</th><th>Client</th><th>Projets</th><th className="num">Jours</th><th className="num">HT</th><th className="num">TTC</th><th>Facture</th><th>Documents</th></tr></thead>
            <tbody>
              {rows.map(({ cra, inv }) => {
                const d = (cra ?? inv)!;
                return (
                  <tr key={d.id}>
                    <td>{d.periodLabel}</td><td>{d.person}</td><td>{d.clientName}</td><td>{d.projects.join(", ")}</td>
                    <td className="num">{n(cra?.days ?? inv?.days ?? null).toLocaleString("fr-FR")}</td><td className="num">{eur(inv?.amountHt ?? cra?.amountHt ?? null)}</td>
                    <td className="num">{eur(inv?.amountTtc ?? null)}</td>
                    <td>{inv?.number}{d.version > 1 && <small className="cs-v"> v{d.version}</small>}{inv?.due && <small className="muted"><br />échéance {new Date(inv.due).toLocaleDateString("fr-FR")}</small>}</td>
                    <td className="cs-dl">{cra && <a className="btn sm" href={dl(cra.id)}>⬇ CRA</a>}{inv && <a className="btn sm" href={dl(inv.id)}>⬇ Facture</a>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Validation({ onDone }: { onDone: () => void }) {
  const groups = useApi(() => api.get<Group[]>("/client-space/time-validation"));
  const { run, busy } = useAction();
  const [open, setOpen] = useState<string | null>(null);
  const [reason, setReason] = useState<Record<string, string>>({});
  if (groups.error) return <ErrorNotice error={groups.error} onRetry={groups.reload} />;
  if (!groups.data) return <Loading />;
  const decide = (g: Group, decision: "approved" | "rejected") =>
    void run(() => api.post<{ updated: number; invoice: string | null }>("/client-space/time-validation",
      { client: g.client, person: g.person, period: g.period, decision, comment: reason[`${g.client}|${g.person}|${g.period}`] ?? "" }),
    decision === "approved" ? "Temps validés" : "Temps refusés").then(() => { groups.reload(); onDone(); }, () => undefined);
  const [refusing, setRefusing] = useState<{ id: number; comment: string } | null>(null);
  const decideOne = (g: Group, id: number, decision: "approved" | "rejected", comment = "") =>
    void run(() => api.post<{ updated: number; invoice: string | null }>("/client-space/time-validation",
      { client: g.client, person: g.person, period: g.period, decision, comment, entries: [id] }),
    decision === "approved" ? "Saisie validée" : "Saisie refusée").then(() => { setRefusing(null); groups.reload(); onDone(); }, () => undefined);
  if (groups.data.length === 0) return <section className="cs-card"><p className="muted">✅ Aucun temps en attente de votre validation.</p></section>;
  return (
    <section className="cs-card cs-val">
      <p className="muted">Ces temps ont été validés par le chef de projet. Votre validation déclenche le compte rendu d'activité et la facture du mois.</p>
      {groups.data.map((g) => {
        const k = `${g.client}|${g.person}|${g.period}`;
        return (
          <div key={k} className="cs-group">
            <div className="cs-group-h">
              <div><b>{g.personName}</b> · {g.periodLabel} · {g.clientName}<small>{g.projects.join(", ")} · {n(g.days).toLocaleString("fr-FR")} j ({n(g.hours)} h) · {g.entries.length} saisie(s)</small></div>
              <button type="button" className="btn sm" onClick={() => setOpen(open === k ? null : k)}>{open === k ? "Masquer" : "Détail"}</button>
              <button type="button" className="btn sm primary" disabled={busy} onClick={() => decide(g, "approved")}>✔ Valider le mois</button>
            </div>
            {open === k && (
              <table className="tbl cs-detail"><thead><tr><th>Date</th><th>Projet</th><th>Tâche</th><th className="num">Heures</th><th>Validé par</th><th>Votre décision</th></tr></thead>
                <tbody>{g.entries.map((e, i) => <tr key={e.id ?? i}><td>{new Date(e.date).toLocaleDateString("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit" })}</td><td>{e.project}</td><td>{e.task}</td><td className="num">{n(e.hours)}</td><td>{e.approvedBy}</td>
                  <td>{e.id != null && (refusing?.id === e.id ? (
                    <span style={{ display: "inline-flex", gap: 6 }}>
                      <input className="inp" style={{ minWidth: 200 }} autoFocus placeholder="Motif du refus (obligatoire)" aria-label="Motif du refus de la saisie" value={refusing.comment} onChange={(ev) => setRefusing({ id: e.id as number, comment: ev.target.value })} />
                      <button type="button" className="btn sm" disabled={busy || !refusing.comment.trim()} onClick={() => decideOne(g, e.id as number, "rejected", refusing.comment)}>Refuser</button>
                      <button type="button" className="btn sm ghost" onClick={() => setRefusing(null)}>Annuler</button>
                    </span>
                  ) : (
                    <span style={{ display: "inline-flex", gap: 6 }}>
                      <button type="button" className="btn sm primary" disabled={busy} onClick={() => decideOne(g, e.id as number, "approved")}>✔ Valider</button>
                      <button type="button" className="btn sm" disabled={busy} onClick={() => setRefusing({ id: e.id as number, comment: "" })}>✖ Refuser</button>
                    </span>
                  ))}</td></tr>)}</tbody>
              </table>
            )}
            <div className="cs-refuse">
              <input className="inp" placeholder="Motif en cas de refus" aria-label="Motif du refus" value={reason[k] ?? ""} onChange={(e) => setReason({ ...reason, [k]: e.target.value })} />
              <button type="button" className="btn sm" disabled={busy || !(reason[k] ?? "").trim()} onClick={() => decide(g, "rejected")}>✖ Refuser</button>
            </div>
          </div>
        );
      })}
    </section>
  );
}

type Staff = { id: number; name: string; role: string; roleLabel: string };
function Support({ s, reload }: { s: Space; reload: () => void }) {
  const staff = useApi(() => (s.isAdmin ? api.get<{ staff: Staff[] }>("/client-space/support") : Promise.resolve({ staff: [] as Staff[] })), [s.isAdmin]);
  const [edit, setEdit] = useState<string | null>(null);
  const [form, setForm] = useState<{ enabled: boolean; levels: string[]; members: number[]; rates: Record<string, string>; startsOn: string; endsOn: string }>({ enabled: false, levels: [], members: [], rates: {}, startsOn: "", endsOn: "" });
  const { run, busy } = useAction();
  const lic = s.supportLicense;
  const open = (code: string) => {
    const c = s.clients.find((x) => x.code === code)!.support;
    setForm({ enabled: c.enabled, levels: c.levels, members: c.members.map((m) => m.id), rates: Object.fromEntries(Object.entries(c.rates ?? {}).map(([k, v]) => [k, String(v ?? "")])), startsOn: c.startsOn ?? "", endsOn: c.endsOn ?? "" });
    setEdit(code);
  };
  const save = () => edit && void run(() => api.put("/client-space/support", { client: edit, ...form, rates: Object.fromEntries(Object.entries(form.rates).filter(([, v]) => v !== "").map(([k, v]) => [k, Number(v)])) }), "Contrat de support enregistré")
    .then(() => { setEdit(null); reload(); }, () => undefined);
  const roleOf: Record<string, string> = { N1: "support_n1", N2: "support_n2", N3: "support_n3" };
  return (
    <section className="cs-card">
      <p className={`cs-lic ${lic.enabled ? "ok" : "off"}`}>{lic.enabled ? `Licence support accordée par le Pilote : ${lic.levels.join(", ")}${lic.maxClients ? ` · ${lic.maxClients} client(s) maximum` : ""}.` : "La licence support n'est pas accordée à votre entreprise : elle s'active dans l'espace Pilote."}
        {" "}Un contrat couvre tous les projets du client ; ses membres saisissent leurs temps et suivent le même circuit de validation et de CRA que le run.</p>
      <div className="cs-contracts">
        {s.clients.map((c) => (
          <div key={c.code} className={`cs-contract ${c.support.enabled ? "on" : ""}`}>
            <div className="cs-contract-h"><b>{c.name}</b>
              <span className={`pill ${c.support.enabled ? "ok" : ""}`}>{c.support.enabled ? `Support ${c.support.levels.join(" / ")}` : "Pas de support"}</span>
              {s.isAdmin && edit !== c.code && <button type="button" className="btn sm" onClick={() => open(c.code)}>Paramétrer</button>}
            </div>
            {c.support.enabled && <small>{c.support.members.map((m) => `${m.name} (${m.role})`).join(", ") || "Aucun membre"}{c.support.endsOn ? ` · jusqu'au ${new Date(c.support.endsOn).toLocaleDateString("fr-FR")}` : ""}
              {c.support.rates && Object.keys(c.support.rates).length > 0 && ` · TJM ${Object.entries(c.support.rates).map(([k, v]) => `${k} ${eur(v)}`).join(", ")}`}</small>}
            {edit === c.code && (
              <div className="cs-contract-form">
                <label className="cs-check"><input type="checkbox" checked={form.enabled} disabled={!lic.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} /> Support actif pour ce client</label>
                <div className="cs-levels">
                  {s.levels.map((lv) => (
                    <label key={lv.code} className={`cs-level ${lic.levels.includes(lv.code) ? "" : "off"}`}>
                      <input type="checkbox" disabled={!lic.levels.includes(lv.code)} checked={form.levels.includes(lv.code)}
                        onChange={(e) => setForm({ ...form, levels: e.target.checked ? [...form.levels, lv.code] : form.levels.filter((x) => x !== lv.code) })} />
                      {lv.label}
                      <input className="inp" type="number" min={0} step={10} placeholder="TJM €" aria-label={`TJM ${lv.label}`} value={form.rates[lv.code] ?? ""}
                        onChange={(e) => setForm({ ...form, rates: { ...form.rates, [lv.code]: e.target.value } })} />
                    </label>
                  ))}
                </div>
                <div className="cs-members">
                  <small>Membres du support (profils Support N1/N2/N3 des niveaux cochés) :</small>
                  {(staff.data?.staff ?? []).filter((u) => form.levels.some((lv) => roleOf[lv] === u.role)).map((u) => (
                    <label key={u.id} className="cs-check"><input type="checkbox" checked={form.members.includes(u.id)}
                      onChange={(e) => setForm({ ...form, members: e.target.checked ? [...form.members, u.id] : form.members.filter((x) => x !== u.id) })} /> {u.name} <small>{u.roleLabel}</small></label>
                  ))}
                  {(staff.data?.staff ?? []).length === 0 && <small className="muted">Aucun utilisateur avec un profil Support : créez-en dans Paramétrage › Utilisateurs.</small>}
                </div>
                <div className="cs-dates">
                  <label>Du <input className="inp" type="date" value={form.startsOn} onChange={(e) => setForm({ ...form, startsOn: e.target.value })} /></label>
                  <label>au <input className="inp" type="date" value={form.endsOn} onChange={(e) => setForm({ ...form, endsOn: e.target.value })} /></label>
                </div>
                <div className="cs-actions"><button type="button" className="btn sm primary" disabled={busy} onClick={save}>Enregistrer</button><button type="button" className="btn sm" onClick={() => setEdit(null)}>Annuler</button></div>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

const BILLING_FIELDS: [string, string, string?][] = [["legalForm", "Forme juridique"], ["capital", "Capital social"], ["siret", "SIRET"], ["vatNumber", "N° TVA intracommunautaire"],
  ["iban", "IBAN"], ["prefix", "Préfixe des factures"], ["vatRate", "Taux de TVA (%)", "number"], ["paymentDays", "Délai de paiement (jours)", "number"]];
function Billing({ conf, reload }: { conf: Record<string, unknown>; reload: () => void }) {
  const [v, setV] = useState<Record<string, unknown>>(conf);
  const { run, busy } = useAction();
  return (
    <section className="cs-card cs-billing">
      <p className="muted">Mentions portées sur chaque facture. La numérotation est continue par année ({String(v.prefix || "FAC")}-AAAA-0001).</p>
      <div className="cs-grid">
        {BILLING_FIELDS.map(([k, l, t]) => (
          <label key={k}><span>{l}</span><input className="inp" type={t ?? "text"} value={String(v[k] ?? "")} onChange={(e) => setV({ ...v, [k]: e.target.value })} /></label>
        ))}
      </div>
      <label className="cs-check"><input type="checkbox" checked={!!v.auto} onChange={(e) => setV({ ...v, auto: e.target.checked })} /> Génération automatique des CRA et factures</label>
      <label className="cs-full"><span>Mentions légales</span><textarea className="inp" rows={3} value={String(v.legalNotice ?? "")} onChange={(e) => setV({ ...v, legalNotice: e.target.value })} /></label>
      <div><button type="button" className="btn primary" disabled={busy} onClick={() => void run(() => api.put("/client-space/billing-settings", v), "Facturation enregistrée").then(reload, () => undefined)}>Enregistrer</button></div>
    </section>
  );
}

/** Profils qui voient le module CRA & facturation (en plus de l'administrateur). */
function ModuleProfiles() {
  const r = useApi(() => api.get<{ enabled: string[]; roles: { code: string; label: string; internal: boolean }[] }>("/client-space/profiles"));
  const { run, busy } = useAction();
  if (!r.data) return null;
  const toggle = (code: string, on: boolean) => {
    const next = on ? [...r.data!.enabled, code] : r.data!.enabled.filter((x) => x !== code);
    void run(() => api.put("/client-space/profiles", { roles: next }), "Accès au module enregistré").then(() => r.reload(), () => undefined);
  };
  return (
    <section className="cs-card cs-billing">
      <b>Profils ayant accès au module CRA &amp; facturation</b>
      <p className="muted">Chaque profil coché voit l’Espace client (CRA, factures, support, consommation IA) pour ses projets et ses clients.</p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
        {r.data.roles.map((role) => (
          <label key={role.code} className="cs-check"><input type="checkbox" disabled={busy} checked={r.data!.enabled.includes(role.code)} onChange={(e) => toggle(role.code, e.target.checked)} /> {role.label}{role.internal ? "" : " (externe)"}</label>
        ))}
      </div>
    </section>
  );
}
