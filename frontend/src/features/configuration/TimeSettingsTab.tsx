import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { adminApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Loading, useAction } from "../../components/ui";
import type { Me } from "../../types/api";
import { DelegationsCard } from "../timesheet/DelegationsCard";
import { TimeWorkflowCard } from "./TimeWorkflowCard";

const MODE_HELP: Record<string, string> = {
  pm: "Chaque saisie part au chef de projet du projet. Sans chef de projet, les administrateurs valident.",
  pm_tl: "Le chef de projet ou le Tech Lead du projet peut valider.",
  role: "Toute personne ayant le droit « Valider » sur la saisie de temps (Matrice des droits) et accès au projet.",
  admin: "Seuls les administrateurs de l’entreprise valident.",
  auto: "Les temps sont validés dès l’envoi, sans étape de validation.",
};

export function TimeSettingsTab({ me }: { me: Me }) {
  const data = useApi(adminApi.timeSettings);
  const { run, busy } = useAction();
  const [unit, setUnit] = useState<"hour" | "day">("hour");
  const [hoursPerDay, setHoursPerDay] = useState(8);
  const [clientVisible, setClientVisible] = useState(true);
  const [approval, setApproval] = useState("pm");
  const [clientApproval, setClientApproval] = useState(false);
  useEffect(() => {
    if (data.data) {
      setUnit(data.data.unit);
      setHoursPerDay(data.data.hoursPerDay);
      setClientVisible(data.data.clientVisible);
      setApproval(data.data.approval ?? "pm");
      setClientApproval(!!(data.data as { clientApproval?: boolean }).clientApproval);
    }
  }, [data.data]);
  if (data.error) return <ErrorNotice error={data.error} onRetry={data.reload} />;
  if (!data.data) return <Loading />;
  const modes = data.data.approvalModes ?? [];

  const save = () =>
    run(() => adminApi.saveTimeSettings({ unit, hoursPerDay, clientVisible, approval, clientApproval }), "Règles de temps enregistrées").then(
      (v) => v && data.setData(v),
      () => undefined,
    );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Card title="Circuit de validation" sub="Qui valide les temps saisis par les collaborateurs. Par défaut : le chef de projet.">
        <div className="wf-modes" role="radiogroup" aria-label="Circuit de validation">
          {modes.map((m) => (
            <label key={m.code} className={`wf-mode${approval === m.code ? " on" : ""}`}>
              <input type="radio" name="approval" value={m.code} checked={approval === m.code} onChange={() => setApproval(m.code)} />
              <span>
                <b>
                  {m.label}
                  {m.code === "pm" && <em className="wf-default">Par défaut</em>}
                </b>
                <small>{MODE_HELP[m.code]}</small>
              </span>
            </label>
          ))}
        </div>
        <p className="muted" style={{ fontSize: 12.5, margin: "12px 0 0" }}>
          Dans tous les cas, un administrateur peut valider, et personne ne valide ses propres temps.
        </p>
        <label className={`wf-mode${clientApproval ? " on" : ""}`} style={{ marginTop: 12 }}>
          <input type="checkbox" checked={clientApproval} onChange={(e) => setClientApproval(e.target.checked)} />
          <span>
            <b>Puis validation par le client</b>
            <small>Après le valideur interne, les temps partent au client (Espace client › Temps à valider). Le CRA et la facture du mois
              sont générés automatiquement quand tout est validé.</small>
          </span>
        </label>
        {(approval !== (data.data.approval ?? "pm") || clientApproval !== !!(data.data as { clientApproval?: boolean }).clientApproval) && (
          <button className="btn primary" style={{ marginTop: 12 }} disabled={busy} onClick={save}>
            Enregistrer le circuit
          </button>
        )}
      </Card>

      <Card title="Règles de saisie" sub="L’unité est imposée à toute l’entreprise ; les heures restent la référence des calculs de capacité.">
        <div className="grid g2">
          <Field id="time-unit" label="Unité de saisie">
            <select className="inp" value={unit} onChange={(e) => setUnit(e.target.value as "hour" | "day")}>
              <option value="hour">Heure</option>
              <option value="day">Journée</option>
            </select>
          </Field>
          <Field id="hours-day" label="Heures par journée" hint="Utilisé pour convertir les journées en heures de capacité.">
            <input className="inp num" type="number" min={1} max={24} step={0.25} value={hoursPerDay} onChange={(e) => setHoursPerDay(Number(e.target.value))} />
          </Field>
        </div>
        <label style={{ display: "flex", gap: 8, alignItems: "center", margin: "12px 0" }}>
          <input type="checkbox" checked={clientVisible} onChange={(e) => setClientVisible(e.target.checked)} />
          Montrer au client les saisies validées des projets auxquels il est affecté (lecture seule)
        </label>
        <button className="btn primary" disabled={busy || !hoursPerDay || hoursPerDay > 24} onClick={save}>
          Enregistrer
        </button>
      </Card>

      <TimeWorkflowCard />
      <LineProfilesCard />
      <HistoryScopeCard />

      {approval !== "auto" && <DelegationsCard me={me} admin />}
    </div>
  );
}

/** Profils qui saisissent leurs temps par ligne (lignes définies dans le paramétrage de chaque projet). */
function LineProfilesCard() {
  const r = useApi(() => api.get<{ profiles: string[]; roles: { code: string; label: string }[] }>("/timesheets/line-profiles"));
  const { run, busy } = useAction();
  if (!r.data) return null;
  const toggle = (code: string, on: boolean) => {
    const next = on ? [...r.data!.profiles, code] : r.data!.profiles.filter((x) => x !== code);
    void run(() => api.put("/timesheets/line-profiles", { profiles: next }), "Profils enregistrés").then(() => r.reload(), () => undefined);
  };
  return (
    <Card title="Saisie par ligne de projet" sub="Les profils cochés imputent leur temps sur une ligne du projet (activité définie par le client ou l’administrateur dans Paramètres du projet → Lignes de saisie).">
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
        {r.data.roles.map((role) => (
          <label key={role.code} style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" disabled={busy} checked={r.data!.profiles.includes(role.code)} onChange={(e) => toggle(role.code, e.target.checked)} /> {role.label}
          </label>
        ))}
      </div>
    </Card>
  );
}

/** Qui voit l'historique des feuilles de temps de qui : par profil (ses feuilles, son équipe, toute l'entreprise). */
function HistoryScopeCard() {
  type S = { roles: Record<string, string>; profiles: { code: string; label: string }[]; scopes: { code: string; label: string }[] };
  const r = useApi(() => api.get<S>("/timesheets/history-settings"));
  const { run, busy } = useAction();
  if (!r.data) return null;
  const set = (code: string, scope: string) =>
    void run(() => api.put("/timesheets/history-settings", { roles: { ...r.data!.roles, [code]: scope } }), "Visibilité enregistrée").then(() => r.reload(), () => undefined);
  return (
    <Card title="Historique des feuilles de temps" sub="Chacun voit toujours ses propres feuilles. Choisissez pour chaque profil s’il voit aussi celles de son équipe ou de toute l’entreprise (l’administrateur voit tout).">
      <div className="grid g2">
        {r.data.profiles.map((p) => (
          <Field key={p.code} id={`hist-${p.code}`} label={p.label}>
            <select id={`hist-${p.code}`} className="inp" disabled={busy} value={r.data!.roles[p.code] ?? "own"} onChange={(e) => set(p.code, e.target.value)}>
              {r.data!.scopes.map((s) => <option key={s.code} value={s.code}>{s.label}</option>)}
            </select>
          </Field>
        ))}
      </div>
    </Card>
  );
}
