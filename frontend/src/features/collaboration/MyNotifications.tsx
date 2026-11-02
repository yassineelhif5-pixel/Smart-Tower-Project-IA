import { useState } from "react";

import { calendarApi, preferencesApi } from "../../api/collab";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Loading, OneTimeSecret, useAction } from "../../components/ui";

/** Préférences personnelles de notification : elles restreignent les règles de l'entreprise. */
export function MyNotificationPreferences() {
  const p = useApi(preferencesApi.get);
  const { run, busy } = useAction();
  if (p.error) return <ErrorNotice error={p.error} onRetry={p.reload} />;
  if (!p.data) return <Loading />;
  const toggle = (event: string, channel: string, enabled: boolean) =>
    void run(() => preferencesApi.save([{ event, channel, enabled }])).then(
      (r) => r && p.setData(r),
      () => undefined,
    );
  return (
    <Card
      title="Mes notifications"
      sub="Choisissez ce que vous recevez. Un canal désactivé par votre entreprise ne peut pas être activé ici."
    >
      <div className="tbl-wrap">
        <table className="tbl tight">
          <thead>
            <tr>
              <th>Événement</th>
              {p.data.channels.map((c) => (
                <th key={c.kind} className="r">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {p.data.events.map((e) => (
              <tr key={e.event}>
                <td>{e.label}</td>
                {p.data!.channels.map((c) => {
                  const cell = e.channels[c.kind];
                  return (
                    <td key={c.kind} className="r">
                      <input
                        type="checkbox"
                        aria-label={`${e.label} — ${c.label}`}
                        checked={cell.enabled}
                        disabled={busy || !cell.allowed}
                        title={cell.allowed ? undefined : "Désactivé par votre entreprise"}
                        onChange={(ev) => toggle(e.event, c.kind, ev.target.checked)}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/** Lien d'abonnement ICS (Outlook, Google Agenda, Apple Calendrier), en lecture seule et révocable. */
export function MyCalendarFeed() {
  const { run, busy } = useAction();
  const [url, setUrl] = useState<string | null>(null);
  return (
    <Card
      title="Mon agenda dans Outlook ou Google"
      sub="Abonnement en lecture seule à vos éléments planifiés (mis à jour toutes les quelques heures par votre agenda)."
    >
      {url ? (
        <OneTimeSecret label="Lien d'abonnement personnel." value={url} />
      ) : (
        <p className="muted">
          Créer un lien révoque le précédent. Ne le partagez pas : il donne accès à votre planning.
        </p>
      )}
      <div className="btns" style={{ marginTop: 10 }}>
        <button
          className="btn"
          disabled={busy}
          onClick={() =>
            void run(calendarApi.feedToken).then(
              (r) => r && setUrl(r.url),
              () => undefined,
            )
          }
        >
          {url ? "Générer un nouveau lien" : "Créer mon lien d'abonnement"}
        </button>
        <button
          className="btn ghost"
          disabled={busy}
          onClick={() =>
            void run(calendarApi.revokeFeed, "Lien révoqué").then(
              () => setUrl(null),
              () => undefined,
            )
          }
        >
          Révoquer
        </button>
      </div>
    </Card>
  );
}
