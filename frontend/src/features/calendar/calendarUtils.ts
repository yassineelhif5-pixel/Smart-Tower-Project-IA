// Outils de dates et de couleurs du calendrier. Les dates « journée » circulent en AAAA-MM-JJ (fin incluse),
// les heures en AAAA-MM-JJTHH:MM dans le fuseau de l'événement : le serveur convertit et stocke en UTC.
import type { CalendarColors, CalendarEvent, EventStatus, Priority } from "../../types/collab";

export type View =
  | "month"
  | "week"
  | "day"
  | "people"
  | "teams"
  | "portfolio"
  | "timeline"
  | "gantt"
  | "mine"
  | "dashboard";

export const VIEWS: [View, string][] = [
  ["month", "Mois"],
  ["week", "Semaine"],
  ["day", "Jour"],
  ["people", "Collaborateurs"],
  ["teams", "Équipes"],
  ["portfolio", "Portefeuille"],
  ["timeline", "Chronologie"],
  ["gantt", "Gantt"],
  ["mine", "Mon planning"],
  ["dashboard", "Tableau de bord"],
];

export const STATUS_LABEL: Record<EventStatus, string> = {
  todo: "À faire",
  planned: "Planifiée",
  doing: "En cours",
  review: "En revue",
  blocked: "Bloquée",
  done: "Terminée",
  cancelled: "Annulée",
};

export const PRIORITY_LABEL: Record<Priority, string> = {
  low: "Basse",
  normal: "Normale",
  high: "Haute",
  critical: "Critique",
};

export const KIND_LABEL = { action: "Action", milestone: "Jalon", meeting: "Réunion", task: "Tâche" } as const;

export const DEFAULT_COLORS: CalendarColors = {
  status: {
    todo: "#8C95A5",
    planned: "#2D6CCB",
    doing: "#0B7A75",
    review: "#9A4E8E",
    blocked: "#C8372C",
    done: "#1D8A57",
    cancelled: "#B0B7C3",
  },
  priority: { low: "#8C95A5", normal: "#2D6CCB", high: "#B87304", critical: "#C8372C" },
  colorBy: "status",
  canEdit: false,
};

export const colorOf = (e: CalendarEvent, colors: CalendarColors) =>
  colors.colorBy === "priority" ? colors.priority[e.priority] : colors.status[e.status];

const pad = (n: number) => String(n).padStart(2, "0");

/** Date locale du navigateur au format AAAA-MM-JJ. */
export const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const isoLocal = (d: Date) => `${iso(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

export const parseDay = (s: string) => {
  const [y, m, d] = s.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
};

export const addDays = (d: Date, n: number) => {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
};

export const diffDays = (a: Date, b: Date) =>
  Math.round(
    (Date.UTC(b.getFullYear(), b.getMonth(), b.getDate()) - Date.UTC(a.getFullYear(), a.getMonth(), a.getDate())) /
      864e5,
  );

export const startOfWeek = (d: Date) => addDays(d, -((d.getDay() + 6) % 7));

/** Période chargée pour une vue donnée autour de la date de référence. */
export function rangeFor(view: View, anchor: Date, zoom: number): { start: Date; end: Date } {
  if (view === "day") return { start: anchor, end: anchor };
  if (view === "week" || view === "mine") {
    const s = startOfWeek(anchor);
    return { start: s, end: addDays(s, view === "mine" ? 13 : 6) };
  }
  if (view === "month" || view === "dashboard") {
    const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
    const last = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0);
    return { start: startOfWeek(first), end: addDays(startOfWeek(last), 6) };
  }
  // Vues en lignes (collaborateurs, équipes, chronologie, Gantt) : largeur selon le zoom (semaines).
  const s = startOfWeek(anchor);
  return { start: s, end: addDays(s, zoom * 7 - 1) };
}

export function shift(view: View, anchor: Date, dir: -1 | 1, zoom: number): Date {
  if (view === "day") return addDays(anchor, dir);
  if (view === "week") return addDays(anchor, 7 * dir);
  if (view === "mine") return addDays(anchor, 14 * dir);
  if (view === "month" || view === "dashboard") return new Date(anchor.getFullYear(), anchor.getMonth() + dir, 1);
  return addDays(anchor, Math.max(1, Math.round(zoom / 2)) * 7 * dir);
}

export function title(view: View, anchor: Date, zoom: number): string {
  const r = rangeFor(view, anchor, zoom);
  if (view === "month" || view === "dashboard")
    return anchor.toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
  if (view === "day")
    return anchor.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const f = (d: Date) => d.toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
  return `${f(r.start)} – ${f(r.end)} ${r.end.getFullYear()}`;
}

export const fmtDay = (s: string) => parseDay(s).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" });

export const isWeekend = (d: Date) => d.getDay() === 0 || d.getDay() === 6;

/** Nouvelles dates d'un événement déplacé de `days` jours (et/ou allongé de `grow` jours en fin). */
export function moved(e: CalendarEvent, days: number, grow = 0) {
  if (e.allDay) {
    return {
      start: iso(addDays(parseDay(e.startDate), days)),
      end: iso(addDays(parseDay(e.endDate), days + grow)),
      allDay: true,
    };
  }
  // Heures : instant UTC explicite, indépendant du fuseau du navigateur et de celui de l'événement.
  const s = new Date(e.start);
  const en = new Date(e.end);
  return { start: addDays(s, days).toISOString(), end: addDays(en, days + grow).toISOString(), allDay: false };
}

export const initials = (name: string) =>
  name
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
