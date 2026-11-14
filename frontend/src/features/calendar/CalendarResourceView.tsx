import type { CalendarColors, CalendarEvent, Workload } from "../../types/collab";
import type { MovePayload } from "./CalendarGrid";
import { RowTimeline, type Row } from "./RowTimeline";

/** Vue par collaborateur ou par équipe : affectations et carte de charge (rouge au-delà de la capacité). */
export function CalendarResourceView({
  group,
  start,
  end,
  events,
  workload,
  colors,
  onOpen,
  onMove,
}: {
  group: "user" | "team";
  start: Date;
  end: Date;
  events: CalendarEvent[];
  workload: Workload | null;
  colors: CalendarColors;
  onOpen: (e: CalendarEvent) => void;
  onMove: (e: CalendarEvent, to: MovePayload) => Promise<boolean>;
}) {
  const rows = new Map<string, Row>();
  for (const w of workload?.rows ?? []) {
    rows.set(w.key, {
      key: w.key,
      label: w.label,
      sub:
        group === "user"
          ? `${w.team ?? ""} · ${w.total.toFixed(1)} h${w.over.length ? ` · ${w.over.length} j en surcharge` : ""}`
          : `${w.members ?? 0} pers. · ${w.total.toFixed(1)} h${w.over.length ? ` · ${w.over.length} j en surcharge` : ""}`,
      events: [],
      load: w.load,
      capacity: w.capacity,
    });
  }
  for (const e of events) {
    const keys = new Set(
      e.assignments.map((a) => (group === "user" ? String(a.user.id) : a.user.team || "Sans équipe")),
    );
    if (!keys.size) keys.add("_none");
    for (const k of keys) {
      const row = rows.get(k) ?? { key: k, label: k === "_none" ? "Sans affectation" : k, events: [] };
      row.events.push(e);
      rows.set(k, row);
    }
  }
  const list = [...rows.values()].sort((a, b) =>
    a.key === "_none" ? 1 : b.key === "_none" ? -1 : String(a.label).localeCompare(String(b.label)),
  );
  return <RowTimeline start={start} end={end} rows={list} colors={colors} onOpen={onOpen} onMove={onMove} />;
}
