import type { ReactNode } from "react";

import { fmtDate, Pill } from "../../components/ui";
import type { LicenseRequest } from "../../types/api";
import { REQUEST_LABEL, REQUEST_TONE } from "./labels";

/** Contenu d'une demande et son historique ; les actions (tenant ou Pilote) sont passées par l'appelant. */
export function RequestView({ request, children }: { request: LicenseRequest; children?: ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div>
        <Pill tone={REQUEST_TONE[request.status]}>{REQUEST_LABEL[request.status]}</Pill> <b>{request.kindLabel}</b>
        {request.quantity !== null && <> · {request.quantity} demandée(s)</>}
        {request.quantityGranted !== null && <> · {request.quantityGranted} accordée(s)</>}
        {request.targetOffer && <> · offre souhaitée : {request.targetOffer.name}</>}
      </div>
      <div className="notice">{request.justification}</div>
      <div className="tbl-wrap">
        <table className="tbl tight">
          <thead>
            <tr>
              <th>Date</th>
              <th>Par</th>
              <th>Étape</th>
              <th>Commentaire</th>
            </tr>
          </thead>
          <tbody>
            {(request.events ?? []).map((e, i) => (
              <tr key={i}>
                <td className="muted" style={{ whiteSpace: "nowrap" }}>
                  {fmtDate(e.at)}
                </td>
                <td className="mono">{e.actor ?? "—"}</td>
                <td>{e.from === e.to ? "Commentaire" : (REQUEST_LABEL[e.to as keyof typeof REQUEST_LABEL] ?? e.to)}</td>
                <td>{e.comment || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {children}
    </div>
  );
}
