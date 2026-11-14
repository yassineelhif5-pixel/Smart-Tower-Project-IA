import type { CalendarColors, CalendarEvent } from "../../types/collab";
import type { MovePayload } from "./CalendarGrid";
import { RowTimeline, type Row } from "./RowTimeline";

/** Chronologie : une ligne par projet, toutes ses actions, jalons et réunions sur la période. */
export function CalendarTimelineView({
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
  const byProject = new Map<string, Row>();
  for (const e of events) {
    const key = e.project?.id ?? "_perso";
    const row = byProject.get(key) ?? {
      key,
      label: e.project ? e.project.code : "Hors projet",
      sub: e.project?.name ?? "Tâches personnelles et réunions",
      events: [],
    };
    row.events.push(e);
    byProject.set(key, row);
  }
  const rows = [...byProject.values()].sort((a, b) => String(a.label).localeCompare(String(b.label)));
  return <RowTimeline start={start} end={end} rows={rows} colors={colors} onOpen={onOpen} onMove={onMove} />;
}
