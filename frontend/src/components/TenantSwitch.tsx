import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { Card, useAction } from "./ui";

export type TenantRef = { id: number; slug: string; name: string; current: boolean; role: string | null; active: boolean; reason?: string | null };

/** Sélecteur d'entreprise (rail gauche) : bascule entre les tenants auxquels l'utilisateur a accès. */
export function TenantSwitcher({ label, name, tenants }: { label: string; name: string; tenants: TenantRef[] }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const many = tenants.length > 1;
  const go = async (t: TenantRef) => {
    if (t.current) return setOpen(false);
    setBusy(t.id);
    setErr("");
    try {
      await api.post("/auth/tenants", { tenant: t.id });
      try { localStorage.removeItem("pct-compare-projects"); } catch { /* */ }
      window.location.hash = "";
      window.location.reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Bascule impossible.");
      setBusy(null);
    }
  };
  return (
    <div className="tenant tsw" ref={ref}>
      <span className="dot" />
      <div style={{ flex: 1, minWidth: 0 }}>
        <small>{label}</small>
        {many ? (
          <button type="button" className="tsw-btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)} title="Changer d’entreprise / de client">
            <span>{name}</span><i>⇅</i>
          </button>
        ) : (
          name
        )}
      </div>
      {open && many && (
        <div className="tsw-pop" role="menu">
          <div className="tsw-h">Basculer vers…</div>
          {tenants.map((t) => (
            <button key={t.id} type="button" role="menuitem" className={`tsw-item${t.current ? " on" : ""}`} disabled={!t.active || busy !== null} title={t.reason ?? undefined} onClick={() => void go(t)}>
              <span className="tsw-av">{t.name.slice(0, 2).toUpperCase()}</span>
              <span className="tsw-txt"><b>{t.name}</b><small>{t.role ?? "—"}{!t.active ? ` · ${t.reason ?? "indisponible"}` : ""}</small></span>
              {t.current ? <em>✓</em> : busy === t.id ? <em>…</em> : null}
            </button>
          ))}
          {err && <div className="tsw-err">{err}</div>}
        </div>
      )}
    </div>
  );
}

type Guest = { id: number; user: string; email: string; username: string; home: string; role: string | null; roleCode: string; since: string; lastUsed: string | null };

/** Administrateur : donner accès à son entreprise à des utilisateurs d'autres entreprises (ex. chef de projet d'une ESN). */
export function GuestsTab() {
  const [data, setData] = useState<{ guests: Guest[]; roles: { code: string; label: string }[] } | null>(null);
  const [form, setForm] = useState({ user: "", role: "cdp" });
  const { run, busy } = useAction();
  useEffect(() => {
    api.get<{ guests: Guest[]; roles: { code: string; label: string }[] }>("/admin/guests").then(setData, () => setData({ guests: [], roles: [] }));
  }, []);
  if (!data) return null;
  return (
    <Card title="Accès multi-entreprises (invités)"
      sub="Donnez accès à votre entreprise à un utilisateur déjà inscrit dans une autre entreprise (ex. chef de projet d’un prestataire). Il pourra basculer entre ses entreprises depuis le menu de gauche.">
      <div className="frow" style={{ alignItems: "flex-end", marginBottom: 12 }}>
        <label className="rd-f" style={{ flex: 2 }}>Identifiant ou e-mail de l’utilisateur
          <input className="inp" value={form.user} placeholder="prenom.nom@prestataire.com" onChange={(e) => setForm({ ...form, user: e.target.value })} />
        </label>
        <label className="rd-f">Profil dans votre entreprise
          <select className="inp" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            {data.roles.map((r) => <option key={r.code} value={r.code}>{r.label}</option>)}
          </select>
        </label>
        <button className="btn primary" type="button" disabled={busy || !form.user.trim()}
          onClick={() => run(() => api.post<typeof data>("/admin/guests", form), "Accès accordé").then((d) => { if (d) { setData(d); setForm({ ...form, user: "" }); } }, () => undefined)}>
          Donner l’accès
        </button>
      </div>
      {data.guests.length === 0 ? (
        <div className="empty">Aucun invité d’une autre entreprise.</div>
      ) : (
        <div className="tbl-wrap">
          <table className="tbl tight">
            <thead><tr><th>Utilisateur</th><th>Entreprise d’origine</th><th>Profil chez vous</th><th>Dernière bascule</th><th /></tr></thead>
            <tbody>
              {data.guests.map((g) => (
                <tr key={g.id}>
                  <td className="cell-main"><b>{g.user}</b><small>{g.email || g.username}</small></td>
                  <td>{g.home}</td>
                  <td>{g.role ?? "—"}</td>
                  <td>{g.lastUsed ? new Date(g.lastUsed).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "Jamais"}</td>
                  <td className="r">
                    <button className="btn ghost sm pj-del" type="button" disabled={busy}
                      onClick={() => window.confirm(`Retirer l’accès de ${g.user} à votre entreprise ?`) &&
                        run(() => api.delete<typeof data>(`/admin/guests/${g.id}`), "Accès retiré").then((d) => d && setData(d), () => undefined)}>
                      Retirer
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
