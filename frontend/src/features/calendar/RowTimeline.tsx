// Frise en lignes (collaborateurs, équipes, projets, Gantt) : jours en colonnes, barres déplaçables et
// redimensionnables au pointeur (souris, stylet ou doigt) ou au clavier (flèches, Maj+flèches pour la durée).
import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";

import type { CalendarColors, CalendarEvent } from "../../types/collab";
import { addDays, colorOf, diffDays, iso, isWeekend, moved, parseDay } from "./calendarUtils";
import type { MovePayload } from "./CalendarGrid";

export interface Row {
  key: string;
  label: ReactNode;
  sub?: ReactNode;
  events: CalendarEvent[];
  /** Charge par jour (heures) et capacité, pour la carte de chaleur des vues Collaborateurs et Équipes. */
  load?: Record<string, number>;
  capacity?: number;
  group?: string;
}

type Drag = { id: number; mode: "move" | "resize"; x: number; delta: number; width: number };

function lanes(events: CalendarEvent[]) {
  const sorted = [...events].sort(
    (a, b) => a.startDate.localeCompare(b.startDate) || b.endDate.localeCompare(a.endDate),
  );
  const ends: string[] = [];
  return sorted.map((e) => {
    let lane = ends.findIndex((end) => end < e.startDate);
    if (lane === -1) lane = ends.length;
    ends[lane] = e.endDate;
    return { e, lane };
  });
}

export function RowTimeline({
  start,
  end,
  rows,
  colors,
  onOpen,
  onMove,
  showProgress = true,
  arrows,
  empty = "Rien à afficher sur cette période.",
}: {
  start: Date;
  end: Date;
  rows: Row[];
  colors: CalendarColors;
  onOpen: (e: CalendarEvent) => void;
  onMove: (e: CalendarEvent, to: MovePayload) => Promise<boolean>;
  showProgress?: boolean;
  arrows?: { from: number; to: number }[];
  empty?: string;
}) {
  const days = Array.from({ length: diffDays(start, end) + 1 }, (_, i) => addDays(start, i));
  const total = days.length;
  const today = iso(new Date());
  const [drag, setDrag] = useState<Drag | null>(null);
  const grid = useRef<HTMLDivElement>(null);

  const span = (e: CalendarEvent, delta = 0, grow = 0) => {
    const s = Math.max(0, diffDays(start, parseDay(e.startDate)) + delta);
    const f = Math.min(total - 1, diffDays(start, parseDay(e.endDate)) + delta + grow);
    return {
      left: (s / total) * 100,
      width: (Math.max(f - s + 1, 1) / total) * 100,
      visible: f >= 0 && s <= total - 1,
    };
  };

  const down = (ev: PointerEvent, e: CalendarEvent, mode: Drag["mode"]) => {
    if (!e.canEdit) return;
    ev.stopPropagation();
    (ev.target as HTMLElement).setPointerCapture(ev.pointerId);
    setDrag({ id: e.id, mode, x: ev.clientX, delta: 0, width: (grid.current?.clientWidth ?? 1) / total });
  };
  const move = (ev: PointerEvent) => {
    if (drag) setDrag({ ...drag, delta: Math.round((ev.clientX - drag.x) / drag.width) });
  };
  const up = async (e: CalendarEvent) => {
    if (!drag) return;
    const d = drag;
    setDrag(null);
    if (d.delta === 0) return onOpen(e);
    if (d.mode === "resize" && diffDays(parseDay(e.startDate), parseDay(e.endDate)) + d.delta < 0) return;
    await onMove(e, d.mode === "move" ? moved(e, d.delta) : moved(e, 0, d.delta));
  };
  const key = (ev: KeyboardEvent, e: CalendarEvent) => {
    if (ev.key === "Enter") return onOpen(e);
    if (!e.canEdit || (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight")) return;
    ev.preventDefault();
    const step = ev.key === "ArrowLeft" ? -1 : 1;
    void onMove(e, ev.shiftKey ? moved(e, 0, step) : moved(e, step));
  };

  if (!rows.length) return <div className="empty">{empty}</div>;

  return (
    <div className="rt" style={{ ["--days" as string]: total }}>
      <div className="rt-head">
        <div className="rt-label" />
        <div className="rt-days" ref={grid}>
          {days.map((d) => (
            <div
              key={iso(d)}
              className={`rt-day ${isWeekend(d) ? "we" : ""} ${iso(d) === today ? "today" : ""}`}
              title={d.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" })}
            >
              {total <= 21 ? (
                <>
                  <small>{d.toLocaleDateString("fr-FR", { weekday: "narrow" })}</small>
                  {d.getDate()}
                </>
              ) : d.getDay() === 1 ? (
                <small className="rt-week">{d.toLocaleDateString("fr-FR", { day: "numeric", month: "short" })}</small>
              ) : null}
            </div>
          ))}
        </div>
      </div>
      {rows.map((row, idx) => {
        const placed = lanes(row.events.filter((e) => span(e).visible));
        const height = Math.max(1, ...placed.map((p) => p.lane + 1));
        const groupStart = row.group && (idx === 0 || rows[idx - 1].group !== row.group);
        return (
          <div key={row.key}>
            {groupStart && <div className="rt-group">{row.group}</div>}
            <div className="rt-row">
              <div className="rt-label">
                <b>{row.label}</b>
                {row.sub && <small>{row.sub}</small>}
              </div>
              <div className="rt-track" style={{ height: `${height * 30 + 10}px` }}>
                {days.map((d) => {
                  const h = row.load?.[iso(d)] ?? 0;
                  const ratio = row.capacity ? h / row.capacity : 0;
                  return (
                    <div
                      key={iso(d)}
                      className={`rt-cell ${isWeekend(d) ? "we" : ""} ${iso(d) === today ? "today" : ""} ${ratio > 1.001 ? "over" : ""}`}
                      style={row.load && h ? { ["--heat" as string]: Math.min(ratio, 1.4) } : undefined}
                      title={row.load && h ? `${h.toFixed(1)} h / ${row.capacity} h` : undefined}
                    />
                  );
                })}
                {placed.map(({ e, lane }) => {
                  const dragging = drag?.id === e.id ? drag : null;
                  const pos = span(
                    e,
                    dragging?.mode === "move" ? dragging.delta : 0,
                    dragging?.mode === "resize" ? dragging.delta : 0,
                  );
                  const owner = e.assignments.find((a) => a.role === "owner");
                  return (
                    <div
                      key={e.id}
                      role="button"
                      tabIndex={0}
                      data-event={e.id}
                      className={`rt-bar ${e.kind === "milestone" ? "milestone" : ""} ${e.late ? "late" : ""} ${dragging ? "drag" : ""} ${e.canEdit ? "editable" : ""}`}
                      style={{
                        left: `${pos.left}%`,
                        width: `${pos.width}%`,
                        top: `${lane * 30 + 5}px`,
                        ["--c" as string]: colorOf(e, colors),
                      }}
                      onPointerDown={(ev) => down(ev, e, "move")}
                      onPointerMove={move}
                      onPointerUp={() => void up(e)}
                      onClick={() => !e.canEdit && onOpen(e)}
                      onKeyDown={(ev) => key(ev, e)}
                      aria-label={`${e.title}, du ${e.startDate} au ${e.endDate}${e.late ? ", en retard" : ""}`}
                      title={`${e.title}${e.project ? ` · ${e.project.code}` : ""}${owner ? ` · ${owner.user.name}` : ""} · ${e.statusLabel}`}
                    >
                      {showProgress && e.progress > 0 && e.kind !== "milestone" && (
                        <i className="rt-prog" style={{ width: `${e.progress}%` }} />
                      )}
                      <span>
                        {e.kind === "milestone" ? "◆ " : ""}
                        {e.title}
                      </span>
                      {e.canEdit && e.kind !== "milestone" && (
                        <span className="rt-grip" aria-hidden="true" onPointerDown={(ev) => down(ev, e, "resize")} />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        );
      })}
      {arrows && arrows.length > 0 && <Arrows arrows={arrows} />}
    </div>
  );
}

/** Flèches de dépendance du Gantt, tracées après rendu à partir de la position des barres. */
function Arrows({ arrows }: { arrows: { from: number; to: number }[] }) {
  const ref = useRef<SVGSVGElement>(null);
  const [paths, setPaths] = useState<string[]>([]);
  const measure = () => {
    const svg = ref.current;
    const root = svg?.parentElement;
    if (!svg || !root) return;
    const box = root.getBoundingClientRect();
    const out: string[] = [];
    for (const a of arrows) {
      const f = root.querySelector(`[data-event="${a.from}"]`)?.getBoundingClientRect();
      const t = root.querySelector(`[data-event="${a.to}"]`)?.getBoundingClientRect();
      if (!f || !t) continue;
      const x1 = f.right - box.left;
      const y1 = f.top + f.height / 2 - box.top;
      const x2 = t.left - box.left;
      const y2 = t.top + t.height / 2 - box.top;
      const mid = Math.max(x1 + 8, Math.min(x2 - 8, (x1 + x2) / 2));
      out.push(`M${x1},${y1} H${mid} V${y2} H${x2 - 2}`);
    }
    if (out.join() !== paths.join()) setPaths(out);
  };
  // Mesure après chaque rendu (déplacement, redimensionnement) ; l'état ne change que si un tracé a bougé.
  useEffect(() => {
    const id = requestAnimationFrame(measure);
    return () => cancelAnimationFrame(id);
  });
  return (
    <svg ref={ref} className="rt-arrows" aria-hidden="true">
      <defs>
        <marker id="rt-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" fill="currentColor" />
        </marker>
      </defs>
      {paths.map((d, i) => (
        <path key={i} d={d} markerEnd="url(#rt-arrow)" />
      ))}
    </svg>
  );
}
