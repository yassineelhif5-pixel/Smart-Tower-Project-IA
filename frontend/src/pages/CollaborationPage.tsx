import { useEffect, useState } from "react";

import { calendarApi, teamsApi } from "../api/collab";
import { useApi } from "../api/useApi";
import { Card, fmtDate, PageHead, Pill, useAction, useToast } from "../components/ui";
import { DiscussionPanel } from "../features/collaboration/DiscussionPanel";
import type { Me } from "../types/api";

const TEAMS_RESULT: Record<string, [string, boolean]> = {
  linked: ["Compte Microsoft Teams relié.", false],
  refused: ["Connexion à Microsoft annulée.", true],
  error: ["La connexion à Microsoft a échoué : recommencez ou contactez votre administrateur.", true],
};

/** Collaboration : discussions de tous les projets visibles et compte Teams personnel. */
export function CollaborationPage({ me }: { me: Me }) {
  const toast = useToast();
  const projects = useApi(calendarApi.projects);
  const status = useApi(teamsApi.status);
  const { run, busy } = useAction();
  const [project, setProject] = useState("");
  const [initial] = useState(() => Number(window.location.hash.split("/")[1]?.split("?")[0]) || undefined);

  useEffect(() => {
    const result = new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("teams");
    if (result && TEAMS_RESULT[result]) {
      toast(...TEAMS_RESULT[result]);
      window.history.replaceState(null, "", "#collaboration");
    }
  }, [toast]);

  const s = status.data;
  return (
    <div className="page">
      <PageHead
        eyebrow={me.tenant?.name ?? ""}
        title="Collaboration"
        sub="Discussions de projet, internes ou publiées dans Microsoft Teams. Vous ne voyez que les projets de votre périmètre."
      />
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <Card
          title="Microsoft Teams"
          sub="Chaque personne relie son propre compte : PCT publie en votre nom, avec les seules permissions nécessaires."
          extra={
            s?.configured &&
            (s.linked ? (
              <button
                className="btn sm"
                disabled={busy}
                onClick={() => void run(teamsApi.unlink, "Compte délié").then(status.reload, () => undefined)}
              >
                Délier mon compte
              </button>
            ) : (
              <button
                className="btn sm primary"
                disabled={busy}
                onClick={() =>
                  void run(teamsApi.connect).then(
                    (r) => r && window.location.assign(r.url),
                    () => undefined,
                  )
                }
              >
                {s.needsReconsent ? "Reconnecter mon compte" : "Relier mon compte Teams"}
              </button>
            ))
          }
        >
          {!s ? (
            <p className="muted">…</p>
          ) : !s.configured ? (
            <p className="muted">
              Le connecteur Teams n'est pas activé pour votre entreprise. Les discussions internes restent disponibles.
            </p>
          ) : (
            <div className="teams-status">
              <Pill tone={s.linked ? "ok" : s.needsReconsent ? "crit" : "warn"}>
                {s.linked ? "Relié" : s.needsReconsent ? "Autorisation expirée" : "Non relié"}
              </Pill>
              {s.account && (
                <span>
                  {s.account.name} <span className="muted mono">{s.account.upn}</span>
                </span>
              )}
              {s.linked && s.missingScopes.length > 0 && (
                <span className="t-warn">
                  Permissions manquantes : {s.missingScopes.join(", ")} — reconnectez votre compte.
                </span>
              )}
              {s.linked && (
                <span className="muted">
                  jeton valable jusqu'au {fmtDate(s.tokenExpiresAt)} (renouvelé automatiquement)
                </span>
              )}
              {!s.webhooks && (
                <span className="muted">Réponses Teams relues périodiquement (pas d'adresse publique configurée).</span>
              )}
            </div>
          )}
        </Card>
        <div className="disc-filter">
          <label>
            Projet{" "}
            <select className="inp" value={project} onChange={(e) => setProject(e.target.value)}>
              <option value="">Tous mes projets</option>
              {(projects.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.code} — {p.name}
                </option>
              ))}
            </select>
          </label>
          {!project && <small className="muted">Choisissez un projet pour créer une discussion.</small>}
        </div>
        <DiscussionPanel project={project || undefined} initial={initial} />
      </div>
    </div>
  );
}
