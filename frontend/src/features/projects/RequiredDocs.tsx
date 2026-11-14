import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { api } from "../../api/client";
import { Card, useAction } from "../../components/ui";

type Item = {
  id?: string; label: string; type: string; keywords: string[]; phase?: string; due?: string | null; note?: string;
  ok?: boolean; late?: boolean; docs?: { id: string; name: string; version: number }[];
};
type Data = { items: Item[]; canEdit: boolean; presets: Item[]; docTypes: { code: string; label: string }[]; done: number; total: number };

/** Documents obligatoires du projet (paramétrables par le chef de projet, le tech lead ou l'admin) et leur statut. */
export function RequiredDocs({ projectId, refreshKey, onConsult }: { projectId: string; refreshKey?: unknown; onConsult?: (docId: string) => void }) {
  const [data, setData] = useState<Data | null>(null);
  const [edit, setEdit] = useState(false);
  const load = useCallback(() => {
    api.get<Data>(`/projects/${encodeURIComponent(projectId)}/required-docs`).then(setData, () => setData(null));
  }, [projectId]);
  useEffect(load, [load, refreshKey]);
  if (!data || (!data.total && !data.canEdit)) return null;
  const pct = data.total ? Math.round((data.done / data.total) * 100) : 0;
  return (
    <Card
      title="📋 Documents obligatoires"
      sub={data.total ? `${data.done} / ${data.total} fourni(s)` : "Aucun document obligatoire défini pour ce projet."}
      extra={data.canEdit ? <button className="btn sm" type="button" onClick={() => setEdit(true)}>⚙ Paramétrer</button> : undefined}
    >
      {data.total > 0 && (
        <>
          <div className="rd-bar"><i style={{ width: `${pct}%` }} /></div>
          <ul className="rd-list">
            {data.items.map((it) => (
              <li key={it.id} className={it.ok ? "ok" : it.late ? "late" : "miss"}>
                <span className="rd-ic">{it.ok ? "✅" : it.late ? "⛔" : "⬜"}</span>
                <div>
                  <b>{it.label}</b>
                  <small>
                    {it.ok
                      ? <>Fourni : {it.docs!.map((d, i) => <span key={d.id}>{i ? ", " : ""}{onConsult ? <a href="#" onClick={(e) => { e.preventDefault(); onConsult(d.id); }}>{d.name}</a> : d.name} (v{d.version})</span>)}</>
                      : it.late ? `En retard — attendu pour le ${new Date(it.due!).toLocaleDateString("fr-FR")}` : `Manquant${it.due ? ` — attendu pour le ${new Date(it.due).toLocaleDateString("fr-FR")}` : ""}`}
                    {it.phase ? ` · phase ${it.phase}` : ""}{it.note ? ` · ${it.note}` : ""}
                  </small>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
      {edit && <RequiredDocsEditor projectId={projectId} data={data} onClose={() => setEdit(false)} onSaved={(d) => { setData(d); setEdit(false); }} />}
    </Card>
  );
}

function RequiredDocsEditor({ projectId, data, onClose, onSaved }: { projectId: string; data: Data; onClose: () => void; onSaved: (d: Data) => void }) {
  const { run, busy } = useAction();
  const [items, setItems] = useState<Item[]>(data.items.map(({ ok: _o, late: _l, docs: _d, ...x }) => x));
  const add = (it: Item) => setItems([...items, { ...it, keywords: [...it.keywords] }]);
  const upd = (i: number, patch: Partial<Item>) => setItems(items.map((x, k) => (k === i ? { ...x, ...patch } : x)));
  const save = () => run(() => api.put<Data>(`/projects/${encodeURIComponent(projectId)}/required-docs`, { items }), "Documents obligatoires enregistrés")
    .then((d) => d && onSaved(d), () => undefined);
  return createPortal(
    <div className="scrim" onClick={onClose}>
      <div className="modal rd-modal" role="dialog" aria-label="Documents obligatoires" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <h3>⚙ Documents obligatoires du projet</h3>
          <button className="icon-btn" type="button" aria-label="Fermer" onClick={onClose}>✕</button>
        </div>
        <div className="modal-b rd-body">
          <div>
            <small className="faint">Ajouter un modèle :</small>
            <div className="rd-presets">
              {data.presets.filter((p) => !items.some((x) => x.label === p.label)).map((p) => (
                <button key={p.label} type="button" className="tk-stage" onClick={() => add(p)}>+ {p.label}</button>
              ))}
              <button type="button" className="tk-stage on" onClick={() => add({ label: "", type: "other", keywords: [] })}>+ Document personnalisé</button>
            </div>
          </div>
          {items.length === 0 && <div className="empty">Aucun document obligatoire. Ajoutez un modèle ou un document personnalisé.</div>}
          {items.map((it, i) => (
            <div key={i} className="rd-item">
              <div className="frow">
                <label className="rd-f" style={{ flex: 2 }}>Document
                  <input className="inp" value={it.label} placeholder="Ex. HLD, dossier d’architecture…" onChange={(e) => upd(i, { label: e.target.value })} />
                </label>
                <label className="rd-f">Type
                  <select className="inp" value={it.type} onChange={(e) => upd(i, { type: e.target.value })}>
                    {data.docTypes.map((t) => <option key={t.code} value={t.code}>{t.label}</option>)}
                  </select>
                </label>
                <label className="rd-f">Attendu pour le
                  <input className="inp" type="date" value={it.due ?? ""} onChange={(e) => upd(i, { due: e.target.value || null })} />
                </label>
                <button className="btn ghost sm pj-del" type="button" aria-label="Retirer" onClick={() => setItems(items.filter((_, k) => k !== i))}>🗑</button>
              </div>
              <div className="frow">
                <label className="rd-f" style={{ flex: 2 }}>Mots-clés de reconnaissance (dans le nom du fichier, séparés par des virgules)
                  <input className="inp" value={it.keywords.join(", ")} placeholder="hld, high level design"
                    onChange={(e) => upd(i, { keywords: e.target.value.split(",").map((k) => k.trim()).filter(Boolean) })} />
                </label>
                <label className="rd-f">Phase
                  <input className="inp" value={it.phase ?? ""} placeholder="Ex. Conception" onChange={(e) => upd(i, { phase: e.target.value })} />
                </label>
              </div>
            </div>
          ))}
          <p className="faint" style={{ fontSize: 12, margin: 0 }}>
            Un document est considéré comme fourni dès qu’un fichier du projet contient un des mots-clés dans son nom ou sa description
            (ou, sans mot-clé, dès qu’un document du type choisi est déposé). Le Chef de projet IA (Nova) proposera de réclamer les documents manquants.
          </p>
        </div>
        <div className="modal-f">
          <button className="btn ghost" type="button" onClick={onClose}>Annuler</button>
          <button className="btn primary" type="button" disabled={busy || items.some((x) => !x.label.trim())} onClick={save}>Enregistrer</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
