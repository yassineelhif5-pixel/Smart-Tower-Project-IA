// Configuration › Notifications : état de l'envoi e-mail et journal des envois de l'entreprise.
import { api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { Card } from "../../components/ui";
import { DeliveryLog, type DeliveryData } from "./DeliveryLog";

type Data = DeliveryData & { email: { enabled: boolean; host: string; port: number; security: string; from_address: string; passwordSet: boolean };
  platform: { configured: boolean }; defaultEmailEvents: string[] };

export function AdminDeliveries() {
  const r = useApi(() => api.get<Data>("/admin/notifications/deliveries"));
  if (!r.data) return null;
  const e = r.data.email;
  return (
    <Card title="Envoi des notifications par e-mail" sub="Socle commun : demandes de licence, actions créées / modifiées / assignées, échéances, récap hebdomadaire des projets, alertes…"
      extra={<button type="button" className="btn sm" onClick={r.reload}>Actualiser</button>}>
      <div className="callout" style={{ marginBottom: 10, display: "block" }}>
        <div>{e.enabled ? <>✅ Envoi actif via <b>{e.host}:{e.port}</b> ({e.security}) — expéditeur <b>{e.from_address || "—"}</b> — clé SMTP {e.passwordSet ? "définie" : <b style={{ color: "#b91c1c" }}>manquante</b>}.</>
          : <>⚠️ Le canal e-mail est <b>désactivé</b> : les notifications restent dans l'application (cloche). Activez-le dans la carte « E-mail (SMTP) » ci-dessous, après avoir saisi la clé SMTP.</>}</div>
        <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
          Les règles d'envoi ci-dessous décident, événement par événement, du canal utilisé ; sans réglage, l'e-mail part pour : demande de licence, action assignée,
          échéance atteinte, action en retard, validation demandée et récap hebdomadaire. Le Pilote voit aussi cette configuration.
        </div>
      </div>
      <DeliveryLog data={r.data} />
    </Card>
  );
}
