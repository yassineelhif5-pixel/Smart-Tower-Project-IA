// Vues Mois, Semaine, Jour et liste « Mon planning » : FullCalendar (paquets MIT uniquement).
import type { DateSelectArg, EventClickArg, EventContentArg, EventDropArg, EventInput } from "@fullcalendar/core";
import frLocale from "@fullcalendar/core/locales/fr";
import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin, { type EventResizeDoneArg } from "@fullcalendar/interaction";
import listPlugin from "@fullcalendar/list";
import FullCalendar from "@fullcalendar/react";
import timeGridPlugin from "@fullcalendar/timegrid";
import { useEffect, useRef } from "react";

import type { CalendarColors, CalendarEvent } from "../../types/collab";
import { addDays, colorOf, iso, isoLocal, parseDay } from "./calendarUtils";

export type GridMode = "dayGridMonth" | "timeGridWeek" | "timeGridDay" | "listTwoWeeks";

export interface MovePayload {
  start: string;
  end: string;
  allDay: boolean;
}

function toInput(e: CalendarEvent, colors: CalendarColors): EventInput {
  const color = colorOf(e, colors);
  return {
    id: String(e.id),
    title: e.title,
    // Journée entière : FullCalendar attend une fin exclusive en date locale.
    start: e.allDay ? e.startDate : e.start,
    end: e.allDay ? iso(addDays(parseDay(e.endDate), 1)) : e.end,
    allDay: e.allDay,
    backgroundColor: color,
    borderColor: e.late ? "var(--crit)" : color,
    editable: e.canEdit,
    classNames: [e.late ? "ev-late" : "", e.kind === "milestone" ? "ev-milestone" : "", `ev-${e.status}`],
    extendedProps: { event: e },
  };
}

function Content({ arg }: { arg: EventContentArg }) {
  const e = arg.event.extendedProps.event as CalendarEvent;
  const owner = e.assignments.find((a) => a.role === "owner");
  return (
    <div className="ev-c" title={`${e.title}${e.project ? ` · ${e.project.code}` : ""}`}>
      {arg.timeText && <span className="ev-t">{arg.timeText}</span>}
      <span className="ev-n">
        {e.kind === "milestone" ? "◆ " : ""}
        {e.title}
      </span>
      {arg.view.type !== "dayGridMonth" && (
        <span className="ev-m">
          {e.project?.code}
          {owner ? ` · ${owner.user.name}` : ""}
          {e.progress ? ` · ${e.progress} %` : ""}
        </span>
      )}
    </div>
  );
}

export function CalendarGrid({
  mode,
  anchor,
  events,
  colors,
  canCreate,
  onOpen,
  onMove,
  onSelect,
}: {
  mode: GridMode;
  anchor: Date;
  events: CalendarEvent[];
  colors: CalendarColors;
  canCreate: boolean;
  onOpen: (e: CalendarEvent) => void;
  onMove: (e: CalendarEvent, to: MovePayload) => Promise<boolean>;
  onSelect: (range: MovePayload) => void;
}) {
  const ref = useRef<FullCalendar>(null);
  useEffect(() => {
    const api = ref.current?.getApi();
    if (!api) return;
    if (api.view.type !== mode) api.changeView(mode, anchor);
    else api.gotoDate(anchor);
  }, [mode, anchor]);

  const payload = (start: Date, end: Date | null, allDay: boolean): MovePayload =>
    allDay
      ? { start: iso(start), end: iso(addDays(end ?? addDays(start, 1), -1)), allDay: true }
      : { start: start.toISOString(), end: (end ?? new Date(start.getTime() + 36e5)).toISOString(), allDay: false };

  const moved = async (info: EventDropArg | EventResizeDoneArg) => {
    const e = info.event.extendedProps.event as CalendarEvent;
    const ok = await onMove(e, payload(info.event.start!, info.event.end, info.event.allDay));
    if (!ok) info.revert(); // refus, conflit non confirmé ou erreur : rien n'a bougé
  };

  return (
    <div className="cal-grid">
      <FullCalendar
        ref={ref}
        plugins={[dayGridPlugin, timeGridPlugin, listPlugin, interactionPlugin]}
        initialView={mode}
        initialDate={anchor}
        locale={frLocale}
        headerToolbar={false}
        height="auto"
        firstDay={1}
        weekNumbers={mode !== "listTwoWeeks"}
        nowIndicator
        dayMaxEvents={4}
        slotMinTime="07:00:00"
        slotMaxTime="21:00:00"
        scrollTime="08:00:00"
        views={{
          listTwoWeeks: {
            type: "list",
            duration: { weeks: 2 },
            listDayFormat: { weekday: "long", day: "numeric", month: "long" },
          },
        }}
        events={events.map((e) => toInput(e, colors))}
        eventContent={(arg) => <Content arg={arg} />}
        eventClick={(info: EventClickArg) => {
          info.jsEvent.preventDefault();
          onOpen(info.event.extendedProps.event as CalendarEvent);
        }}
        editable
        eventDurationEditable
        eventStartEditable
        eventDrop={moved}
        eventResize={moved}
        selectable={canCreate}
        selectMirror
        select={(arg: DateSelectArg) => {
          onSelect(
            arg.allDay
              ? payload(arg.start, arg.end, true)
              : { start: isoLocal(arg.start), end: isoLocal(arg.end), allDay: false },
          );
          ref.current?.getApi().unselect();
        }}
        noEventsContent="Aucun événement sur cette période."
      />
    </div>
  );
}

export type GridProps = Omit<Parameters<typeof CalendarGrid>[0], "mode">;
