// Pilote : toutes les demandes d'adhésion des comptes inscrits, avec décision possible à la place de l'admin du tenant.
import { useState } from "react";

import { api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Loading, useAction } from "../../components/ui";
import type { JoinRequestRow } from "../../types/api";
import { JoinRequestTable } from "../configuration/JoinRequestsPanel";
import { InvitePanel } from "../configuration/InvitePanel";

export function PilotJoinRequests() {
  const [filter, setFilter] = useState("pending");
  const q = useApi(() => api.get<{ requests: JoinRequestRow[] }>(`/platform/join-requests?status=${filter}`), [filter]);
  const { run, busy } = useAction();
  const decide = (id: number, action: "approve" | "reject", role: string, comment: string) =>
    void run(() => api.post(`/platform/join-requests/${id}`, { action, role, comment }), action === "approve" ? "Adhésion acceptée" : "Demande refusée")
      .then(() => q.reload(), () => undefined);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
    <InvitePanel pilot />
    <Card title="Demandes d’adhésion" sub="Comptes inscrits librement qui demandent à rejoindre une entreprise avec son code. L’administrateur de l’entreprise ou le Pilote valide.">
      <div style={{ marginBottom: 10 }}>
        <select className="inp" style={{ maxWidth: 220 }} value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filtrer">
          <option value="pending">À traiter</option><option value="approved">Acceptées</option><option value="rejected">Refusées</option><option value="all">Toutes</option>
        </select>
      </div>
      {q.error ? <ErrorNotice error={q.error} onRetry={q.reload} /> : !q.data ? <Loading /> :
        <JoinRequestTable rows={q.data.requests} rolesFor={(r) => r.roles ?? []} onDecide={decide} busy={busy} showTenant />}
    </Card>
    </div>
  );
}
