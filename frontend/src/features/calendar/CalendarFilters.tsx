import type { Person, ProjectRef } from "../../types/collab";
import { KIND_LABEL, PRIORITY_LABEL, STATUS_LABEL } from "./calendarUtils";

export interface Filters {
  project: string;
  user: string;
  team: string;
  status: string;
  priority: string;
  kind: string;
  late: boolean;
}

export const EMPTY_FILTERS: Filters = {
  project: "",
  user: "",
  team: "",
  status: "",
  priority: "",
  kind: "",
  late: false,
};

export const countFilters = (f: Filters) => Object.values(f).filter(Boolean).length;

/** Filtres appliqués côté serveur (le périmètre de l'utilisateur reste toujours celui du serveur). */
export function CalendarFilters({
  value,
  onChange,
  projects,
  people,
}: {
  value: Filters;
  onChange: (f: Filters) => void;
  projects: ProjectRef[];
  people: Person[];
}) {
  const set = (patch: Partial<Filters>) => onChange({ ...value, ...patch });
  const teams = [...new Set(people.map((p) => p.team).filter(Boolean))].sort() as string[];
  return (
    <div className="cal-filters" role="group" aria-label="Filtres du calendrier">
      <label>
        Projet
        <select className="inp" value={value.project} onChange={(e) => set({ project: e.target.value })}>
          <option value="">Tous</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.code} — {p.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Collaborateur
        <select className="inp" value={value.user} onChange={(e) => set({ user: e.target.value })}>
          <option value="">Tous</option>
          {people.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Équipe
        <select className="inp" value={value.team} onChange={(e) => set({ team: e.target.value })}>
          <option value="">Toutes</option>
          {teams.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
      </label>
      <label>
        Statut
        <select className="inp" value={value.status} onChange={(e) => set({ status: e.target.value })}>
          <option value="">Tous</option>
          {Object.entries(STATUS_LABEL).map(([k, l]) => (
            <option key={k} value={k}>
              {l}
            </option>
          ))}
        </select>
      </label>
      <label>
        Priorité
        <select className="inp" value={value.priority} onChange={(e) => set({ priority: e.target.value })}>
          <option value="">Toutes</option>
          {Object.entries(PRIORITY_LABEL).map(([k, l]) => (
            <option key={k} value={k}>
              {l}
            </option>
          ))}
        </select>
      </label>
      <label>
        Type
        <select className="inp" value={value.kind} onChange={(e) => set({ kind: e.target.value })}>
          <option value="">Tous</option>
          {Object.entries(KIND_LABEL).map(([k, l]) => (
            <option key={k} value={k}>
              {l}
            </option>
          ))}
        </select>
      </label>
      <label className="cal-check">
        <input type="checkbox" checked={value.late} onChange={(e) => set({ late: e.target.checked })} /> En retard
        uniquement
      </label>
      {countFilters(value) > 0 && (
        <button className="btn sm ghost" onClick={() => onChange(EMPTY_FILTERS)}>
          Effacer
        </button>
      )}
    </div>
  );
}
