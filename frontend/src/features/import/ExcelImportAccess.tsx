// Accès au module « Import Excel des projets et des actions » : profils autorisés (administrateur ou Pilote),
// et activation du module pour l'entreprise (Pilote uniquement).
import { api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { Card, Pill, useAction } from "../../components/ui";

type Access = { enabled: boolean; profiles: string[]; roles: { code: string; label: string; internal: boolean }[] };

export function ExcelImportAccessCard({ url, pilot = false }: { url: string; pilot?: boolean }) {
  const r = useApi(() => api.get<Access>(url), [url]);
  const { run, busy } = useAction();
  if (!r.data) return null;
  const d = r.data;
  const save = (body: Partial<Access>, msg: string) => void run(() => api.put<Access>(url, body), msg).then((res) => res && r.setData(res), () => undefined);
  const toggle = (code: string, on: boolean) => save({ profiles: on ? [...d.profiles, code] : d.profiles.filter((x) => x !== code) }, "Profils autorisés enregistrés");
  return (
    <Card title="Module « Import Excel des projets et des actions »"
      sub={pilot ? "Activez le module pour cette entreprise et choisissez les profils qui voient l’option d’import (l’administrateur de l’entreprise peut aussi ajuster les profils)."
        : "Choisissez les profils qui voient l’option d’import Excel dans Projets. L’administrateur y a toujours accès."}
      extra={<Pill tone={d.enabled ? "ok" : ""}>{d.enabled ? "Module activé" : "Module désactivé par le Pilote"}</Pill>}>
      {pilot && (
        <label style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
          <input type="checkbox" checked={d.enabled} disabled={busy} onChange={(e) => save({ enabled: e.target.checked }, e.target.checked ? "Module activé" : "Module désactivé")} />
          Module d’import Excel activé pour l’entreprise
        </label>
      )}
      {!d.enabled && !pilot ? <p className="muted">Le Pilote a désactivé ce module pour votre entreprise.</p> : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12, opacity: d.enabled ? 1 : 0.5 }}>
          <label style={{ display: "flex", gap: 6, alignItems: "center" }}><input type="checkbox" checked disabled /> Administrateur</label>
          {d.roles.map((role) => (
            <label key={role.code} style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input type="checkbox" disabled={busy || !d.enabled} checked={d.profiles.includes(role.code)} onChange={(e) => toggle(role.code, e.target.checked)} />
              {role.label}{role.internal ? "" : " (externe)"}
            </label>
          ))}
        </div>
      )}
    </Card>
  );
}
