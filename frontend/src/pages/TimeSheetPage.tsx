import { useState } from "react";
import { timeApi } from "../api/endpoints";
import { useApi } from "../api/useApi";
import { Card, ErrorNotice, Loading, PageHead, useAction, useToast } from "../components/ui";
import { DelegationsCard } from "../features/timesheet/DelegationsCard";
import { MySheet } from "../features/timesheet/MySheet";
import { EntryHistory } from "../features/timesheet/EntryHistory";
import { ValidationBoard } from "../features/timesheet/ValidationBoard";
import { TimesheetReport } from "../features/timesheet/TimesheetReport";
import { MyCras } from "../features/timesheet/MyCras";
import "../features/timesheet/sheet.css";
import type { Me } from "../types/api";



export function TimeSheetPage({ me }: { me: Me }) {
  const rows = useApi(timeApi.entries);
  const { run, busy } = useAction();
  const toast = useToast();
  const [showSent, setShowSent] = useState(false);
  const canSubmit = !!me.permissions.timesheet?.[1] && me.role?.code !== "client";
  const canApprove = !!me.permissions.timesheet?.[4];

  if (rows.error) return <ErrorNotice error={rows.error} onRetry={rows.reload} />;
  if (!rows.data) return <Loading />;

  const runDecide = (id: number, decision: "approved" | "rejected", comment: string) =>
    run(() => timeApi.decide(id, decision, comment), decision === "approved" ? "Temps validé" : "Saisie refusée : le collaborateur est prévenu").then(
      () => rows.reload(),
      () => undefined,
    );
  const toApprove = rows.data.rows.filter((r) => r.canDecide);
  // Saisies en attente d'un autre valideur (visibles, non validables par moi)
  const upstream = rows.data.rows.filter((r) => r.status === "pending" && !r.canDecide && r.user !== me.id && r.waitingFor);
  // Saisies déjà validées en interne et transmises au client (suivi, lecture seule)
  const atClient = showSent ? rows.data.rows.filter((r) => r.status === "client" && r.user !== me.id) : [];
  const autoMode = rows.data.approval === "auto";
  const approveMany = async (ids: number[]) => {
    for (const id of ids) {
      try {
        await run(() => timeApi.decide(id, "approved"));
      } catch {
        /* le message d'erreur est déjà affiché */
      }
    }
    toast("Saisies validées");
    rows.reload();
  };

  return (
    <div className="page">
      <PageHead
        eyebrow={me.tenant?.name ?? ""}
        title="Saisie de temps"
        sub="Choisissez la vue (jour, semaine, mois), saisissez vos temps par projet et par ligne ainsi que vos absences : tout est enregistré au fil de l’eau. Quand chaque journée est complète, envoyez la période en validation."
      />

      {canSubmit && <MySheet />}

      {(canApprove || toApprove.length > 0 || upstream.length > 0) && !autoMode && (
        <Card
          title="À valider"
          sub="Saisies dont vous êtes le valideur (ou le délégué). Affichez-les par consultant, projet ou période, consultez le détail et la synthèse des heures avant de valider."
        >
          <ValidationBoard
            busy={busy}
            entries={[...toApprove, ...upstream, ...atClient].map((r) => r.status === "client" ? ({ id: r.id, date: r.workDate, person: r.userName, personId: r.user,
              project: r.projectCode ?? r.projectName, projectName: r.projectName, line: r.lineName ?? "", task: r.actionName || "Activité générale",
              hours: Number(r.hours ?? r.amount), readOnly: true, step: "✅ Validée en interne — en attente du client", approvedBy: r.approvedBy ?? undefined,
              locked: "Déjà validée en interne : en attente de la validation du client" }) : ({ id: r.id, date: r.workDate, person: r.userName, personId: r.user, project: r.projectCode ?? r.projectName,
              projectName: r.projectName, line: r.lineName ?? "", task: r.actionName || "Activité générale",
              hours: Number(r.hours ?? (r.unit === "day" ? NaN : r.amount)),
              step: r.canDecide ? (r.early ? `⚡ Validation anticipée — en attente de ${r.waitingFor}` : r.stepLabel) : `En attente de ${r.waitingFor}`,
              readOnly: !r.canDecide, locked: r.canDecide ? undefined : `En attente de ${r.waitingFor} (vous n'êtes pas le valideur de cette étape)` }))}
            toolbar={<label className="vb-check"><input type="checkbox" checked={showSent} onChange={(e) => setShowSent(e.target.checked)} /> Inclure les saisies transmises au client</label>}
            onApprove={(ids) => approveMany(ids)}
            onReject={(id, comment) => runDecide(id, "rejected", comment)}
          />
        </Card>
      )}

      {canSubmit && <MyCras />}

      <TimesheetReport />

      {canSubmit && <DelegationsCard me={me} />}

      <EntryHistory rows={rows.data.rows.filter((r) => !canSubmit || r.user === me.id)} title={canSubmit ? "Historique de mes saisies" : "Saisies validées"} withPerson={!canSubmit} />
    </div>
  );
}
