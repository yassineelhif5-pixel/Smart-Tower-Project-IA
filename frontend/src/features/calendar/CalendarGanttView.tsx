import type { CalendarColors, CalendarEvent } from "../../types/collab";
import type { MovePayload } from "./CalendarGrid";
import { RowTimeline, type Row } from "./RowTimeline";

/** Gantt : une ligne par élément, regroupée par projet, avec avancement et flèches de dépendance. */
export function CalendarGanttView({
  start,
  end,
  events,
  colors,
  onOpen,
  onMove,
}: {
  start: Date;
  end: Date;
  events: CalendarEvent[];
  colors: CalendarColors;
  onOpen: (e: CalendarEvent) => void;
  onMove: (e: CalendarEvent, to: MovePayload) => Promise<boolean>;
}) {
  const sorted = [...events].sort(
    (a, b) =>
      (a.project?.code ?? "~").localeCompare(b.project?.code ?? "~") ||
      a.startDate.localeCompare(b.startDate) ||
      a.title.localeCompare(b.title),
  );
  const rows: Row[] = sorted.map((e) => {
    const owner = e.assignments.find((a) => a.role === "owner");
    return {
      key: String(e.id),
      group: e.project ? `${e.project.code} — ${e.project.name}` : "Hors projet",
      label: e.title,
      sub: `${owner?.user.name ?? "Sans responsable"} · ${e.progress} %`,
      events: [e],
    };
  });
  const ids = new Set(events.map((e) => e.id));
  const arrows = events.flatMap((e) =>
    e.dependencies.filter((d) => ids.has(d.predecessor)).map((d) => ({ from: d.predecessor, to: e.id })),
  );
  return (
    <RowTimeline
      start={start}
      end={end}
      rows={rows}
      colors={colors}
      onOpen={onOpen}
      onMove={onMove}
      arrows={arrows}
      empty="Aucun élément planifié sur cette période."
    />
  );
}
