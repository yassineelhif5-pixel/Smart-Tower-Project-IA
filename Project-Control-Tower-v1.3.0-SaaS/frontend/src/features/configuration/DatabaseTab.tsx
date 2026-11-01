import { adminApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Icon, Loading, Pill, useAction } from "../../components/ui";

export function DatabaseTab() {
  const db = useApi(adminApi.database);
  const { run, busy } = useAction();

  if (db.error) return <ErrorNotice error={db.error} onRetry={db.reload} />;
  if (!db.data) return <Loading />;
  const d = db.data;

  async function test() {
    const result = await run(() => adminApi.testDatabase(), "Connexion réussie").catch(() => undefined);
    if (result) db.setData({ ...d, ...result });
  }

  const rows: [string, React.ReactNode][] = [
    ["Fournisseur", d.provider],
    ["État", d.connected ? <Pill tone="ok">Connectée</Pill> : <Pill tone="crit">Injoignable ({d.error})</Pill>],
    ["Version du serveur", d.serverVersion ?? "—"],
    ["Temps de réponse", d.latencyMs != null ? `${d.latencyMs} ms` : "—"],
    [
      "Chiffrement de la connexion (SSL)",
      d.ssl == null ? (
        "Inconnu"
      ) : d.ssl ? (
        <Pill tone="ok">Activé</Pill>
      ) : (
        <Pill tone={d.location === "local" ? "" : "warn"}>Non chiffrée</Pill>
      ),
    ],
    ["Hébergement", d.location === "local" ? "Base locale (développement)" : "Serveur distant"],
    ["Migrations appliquées", d.migrations ? `${d.migrations.applied}` : "—"],
    [
      "Migrations en attente",
      d.migrations ? (
        d.migrations.pending.length ? (
          <Pill tone="warn">{d.migrations.pending.join(", ")}</Pill>
        ) : (
          <Pill tone="ok">Aucune</Pill>
        )
      ) : (
        "—"
      ),
    ],
  ];

  return (
    <div className="grid g2">
      <Card
        title="Connexion à la base de données"
        sub="Seul le serveur Django se connecte à la base"
        extra={
          <button className="btn primary" onClick={test} disabled={busy}>
            {busy ? "Test…" : "Tester la connexion"}
          </button>
        }
      >
        <div className="list">
          {rows.map(([label, value]) => (
            <div className="li" key={label}>
              <div className="grow">
                <b>{label}</b>
              </div>
              <span>{value}</span>
            </div>
          ))}
        </div>
      </Card>
      <Card title="Modifier la connexion" sub="Les identifiants ne transitent jamais par le navigateur">
        <div style={{ display: "flex", flexDirection: "column", gap: 12, fontSize: 13.5 }}>
          <p style={{ margin: 0 }}>
            La connexion est définie par la variable d'environnement <code className="mono">{d.configuredBy}</code> du
            serveur. Pour la changer (passer à Supabase, changer de mot de passe) :
          </p>
          <ol style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 4 }}>
            <li>
              mettez à jour <code className="mono">{d.configuredBy}</code> dans la configuration du serveur, avec{" "}
              <code className="mono">?sslmode=require</code> pour Supabase ;
            </li>
            <li>redémarrez le backend ;</li>
            <li>
              appliquez les migrations : <code className="mono">python manage.py migrate</code> ;
            </li>
            <li>revenez ici et cliquez sur « Tester la connexion ».</li>
          </ol>
          <div className="notice">
            <Icon name="lock" size={15} /> Cet écran n'affiche ni l'adresse du serveur, ni l'utilisateur, ni le mot de
            passe de la base.
          </div>
        </div>
      </Card>
    </div>
  );
}
