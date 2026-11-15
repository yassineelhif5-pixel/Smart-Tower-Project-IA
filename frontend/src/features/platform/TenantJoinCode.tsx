// Pilote : code secret d'une entreprise (adhésion des comptes inscrits) et état de démo.
import { useState } from "react";

import { api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { useAction } from "../../components/ui";

export function TenantJoinCode({ tenantId }: { tenantId: number }) {
  const r = useApi(() => api.get<{ code: string | null; isDemo: boolean; demoUntil: string | null }>(`/platform/tenants/${tenantId}/join-code`), [tenantId]);
  const { run, busy } = useAction();
  const [show, setShow] = useState(false);
  if (!r.data) return null;
  if (r.data.isDemo)
    return <div className="callout info" style={{ display: "block" }}><b>Tenant de démonstration</b> · fin le {r.data.demoUntil ? new Date(r.data.demoUntil).toLocaleDateString("fr-FR") : "—"} (2 projets max.). Il devient une entreprise normale dès qu’une offre est activée.</div>;
  return (
    <div className="callout info" style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
      <b>Code entreprise :</b> <code className="join-code">{show ? r.data.code : "••••-••••"}</code>
      <button type="button" className="btn sm" onClick={() => setShow((v) => !v)}>{show ? "Masquer" : "Afficher"}</button>
      <button type="button" className="btn ghost sm" disabled={busy}
        onClick={() => { if (window.confirm("Régénérer le code ? L’ancien ne fonctionnera plus.")) void run(() => api.post(`/platform/tenants/${tenantId}/join-code`, {}), "Nouveau code généré").then(() => { setShow(true); r.reload(); }, () => undefined); }}>Régénérer</button>
      <span className="muted" style={{ fontSize: 12 }}>À communiquer aux personnes qui doivent rejoindre cette entreprise après leur inscription.</span>
    </div>
  );
}
