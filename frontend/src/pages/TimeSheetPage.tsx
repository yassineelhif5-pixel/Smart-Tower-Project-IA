import { timeApi } from "../api/endpoints";
import { useApi } from "../api/useApi";
import { Card, ErrorNotice, Loading, PageHead, useAction, useToast } from "../components/ui";
import { DelegationsCard } from "../features/timesheet/DelegationsCard";
import { MySheet } from "../features/timesheet/MySheet";
import { EntryHistory } from "../features/timesheet/EntryHistory";
import type { Me } from "../types/api";


function fmt(n: number) {
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/0$/, "").replace(".", ",");
}

export function TimeSheetPage({ me }: { me: Me }) {
  const rows = useApi(timeApi.entries);
  const { run, busy } = useAction();
  const toast = useToast();
  const canSubmit = !!me.permissions.timesheet?.[1] && me.role?.code !== "client";
  const canApprove = !!me.permissions.timesheet?.[4];

  if (rows.error) return <ErrorNotice error={rows.error} onRetry={rows.reload} />;
  if (!rows.data) return <Loading />;

  const decide = (id: number, decision: "approved" | "rejected") =>
    run(() => timeApi.decide(id, decision), decision === "approved" ? "Temps validé" : "Saisie refusée").then(
      () => rows.reload(),
      () => undefined,
    );
  const toApprove = rows.data.rows.filter((r) => r.canDecide);
  const autoMode = rows.data.approval === "auto";
  const approveAll = async () => {
    for (const r of toApprove) {
      try {
        await run(() => timeApi.decide(r.id, "approved"));
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

      {(canApprove || toApprove.length > 0) && !autoMode && (
        <Card
          title="À valider"
          sub="Saisies dont vous êtes le valideur (ou le remplaçant pendant une absence)."
          extra={
            toApprove.length > 1 ? (
              <button className="btn primary sm" type="button" disabled={busy} onClick={approveAll}>
                Tout valider ({toApprove.length})
              </button>
            ) : undefined
          }
        >
          <div className="tbl-wrap">
            <table className="tbl tight">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Personne</th>
                  <th>Projet</th>
                  <th className="r">Durée</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {toApprove.map((r) => (
                  <tr key={r.id}>
                    <td>{new Date(`${r.workDate}T00:00:00`).toLocaleDateString("fr-FR")}</td>
                    <td>{r.userName}</td>
                    <td>{r.projectName}</td>
                    <td className="r">
                      {fmt(Number(r.amount))} {r.unit === "day" ? "j" : "h"}
                    </td>
                    <td>
                      <div className="btns">
                        <button className="btn primary sm" disabled={busy} onClick={() => decide(r.id, "approved")}>
                          Valider
                        </button>
                        <button className="btn sm" disabled={busy} onClick={() => decide(r.id, "rejected")}>
                          Refuser
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {toApprove.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted">
                      Rien à valider pour le moment.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {canSubmit && <DelegationsCard me={me} />}

      <EntryHistory rows={rows.data.rows.filter((r) => !canSubmit || r.user === me.id)} title={canSubmit ? "Historique de mes saisies" : "Saisies validées"} withPerson={!canSubmit} />
    </div>
  );
}
