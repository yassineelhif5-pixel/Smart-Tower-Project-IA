import { useCallback, useMemo, useState } from "react";

import { ApiError } from "../api/client";
import { calendarApi, type Query } from "../api/collab";
import { useApi } from "../api/useApi";
import { ErrorNotice, Loading, PageHead, useToast } from "../components/ui";
import { CalendarDashboard } from "../features/calendar/CalendarDashboard";
import { CalendarDayView } from "../features/calendar/CalendarDayView";
import { CalendarEventModal } from "../features/calendar/CalendarEventModal";
import { CalendarFilters, countFilters, EMPTY_FILTERS, type Filters } from "../features/calendar/CalendarFilters";
import { CalendarGanttView } from "../features/calendar/CalendarGanttView";
import { CalendarGrid, type MovePayload } from "../features/calendar/CalendarGrid";
import { CalendarMonthView } from "../features/calendar/CalendarMonthView";
import { CalendarPortfolioView } from "../features/calendar/CalendarPortfolioView";
import { CalendarResourceView } from "../features/calendar/CalendarResourceView";
import { CalendarTimelineView } from "../features/calendar/CalendarTimelineView";
import { CalendarToolbar } from "../features/calendar/CalendarToolbar";
import { CalendarWeekView } from "../features/calendar/CalendarWeekView";
import { ConflictDialog } from "../features/calendar/CalendarConflicts";
import { DEFAULT_COLORS, iso, rangeFor, shift, title, VIEWS, type View } from "../features/calendar/calendarUtils";
import type { Me } from "../types/api";
import type { CalendarEvent, Conflict, EventInput } from "../types/collab";

type Pending = { conflicts: Conflict[]; id: number | null; input: EventInput; resolve: (ok: boolean) => void };
type Editing = { event: CalendarEvent | null; preset?: { start: string; end: string; allDay: boolean } } | null;

const viewFromHash = (): View => {
  const v = window.location.hash.split("/")[1] as View;
  return VIEWS.some(([k]) => k === v) ? v : "month";
};

/** Calendrier : vues Mois, Semaine, Jour, Collaborateurs, Équipes, Portefeuille, Chronologie, Gantt, Mon planning. */
export function CalendarPage({ me }: { me: Me }) {
  const toast = useToast();
  const [view, setViewState] = useState<View>(viewFromHash);
  const [anchor, setAnchor] = useState(() => new Date());
  const [zoom, setZoom] = useState(6);
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [editing, setEditing] = useState<Editing>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);

  const setView = (v: View) => {
    setViewState(v);
    window.history.replaceState(null, "", `#calendrier/${v}`);
  };
  const range = rangeFor(view, anchor, zoom);
  const params: Query = {
    start: iso(range.start),
    end: iso(range.end),
    q: search.trim(),
    project: filters.project,
    user: filters.user,
    team: filters.team,
    status: filters.status,
    priority: filters.priority,
    kind: filters.kind,
    late: filters.late,
    mine: view === "mine",
  };
  const key = JSON.stringify(params);
  const canCreate = !!me.permissions.planning?.[1];

  const events = useApi(() => calendarApi.events(params), [key]);
  const colors = useApi(calendarApi.settings);
  const projects = useApi(calendarApi.projects);
  const people = useApi(() => calendarApi.people());
  const needsLoad = view === "people" || view === "teams";
  const workload = useApi(
    () =>
      needsLoad
        ? calendarApi.workload({ ...params, group: view === "teams" ? "team" : "user" })
        : Promise.resolve(null),
    [key, view],
  );

  /** Enregistre ; en cas de conflits, affiche le choix (proposition, confirmer, annuler). Renvoie vrai si enregistré. */
  const save = useCallback(
    async (id: number | null, input: EventInput): Promise<boolean> => {
      try {
        if (id) await calendarApi.update(id, input);
        else await calendarApi.create(input);
        toast(id ? "Planning mis à jour" : "Événement créé");
        events.reload();
        workload.reload();
        return true;
      } catch (e) {
        if (e instanceof ApiError && e.code === "CALENDAR_CONFLICTS") {
          return new Promise<boolean>((resolve) =>
            setPending({ conflicts: e.details as unknown as Conflict[], id, input, resolve }),
          );
        }
        if (e instanceof ApiError) toast(e.message, true);
        return false;
      }
    },
    [events, workload, toast],
  );

  const settle = async (p: Pending, next: EventInput | null) => {
    if (!next) {
      setPending(null);
      p.resolve(false);
      return;
    }
    setBusy(true);
    setPending(null);
    const ok = await save(p.id, next).finally(() => setBusy(false));
    p.resolve(ok);
  };

  const applySuggestion = (c: Conflict): Promise<boolean> => {
    const s = c.suggestion;
    if (!s || s.action === "assign") return Promise.resolve(false);
    return save(s.event, { start: s.start, end: s.end, allDay: s.allDay });
  };

  const move = (e: CalendarEvent, to: MovePayload) => save(e.id, to);
  const open = (e: CalendarEvent) => setEditing({ event: e });
  const openId = async (id: number) => {
    try {
      setEditing({ event: await calendarApi.event(id) });
    } catch (err) {
      if (err instanceof ApiError) toast(err.message, true);
    }
  };

  const list = events.data?.results ?? [];
  const palette = colors.data ?? DEFAULT_COLORS;
  const gridProps = {
    anchor,
    events: list,
    colors: palette,
    canCreate,
    onOpen: open,
    onMove: move,
    onSelect: (r: MovePayload) => setEditing({ event: null, preset: r }),
  };
  const rowProps = { start: range.start, end: range.end, events: list, colors: palette, onOpen: open, onMove: move };
  const label = useMemo(() => title(view, anchor, zoom), [view, anchor, zoom]);

  return (
    <div className="page cal-page">
      <PageHead
        eyebrow={me.tenant?.name ?? ""}
        title="Calendrier"
        sub="Actions, jalons et réunions de vos projets. Les conflits sont signalés avant tout enregistrement, jamais corrigés à votre place."
      />
      <CalendarToolbar
        view={view}
        onView={setView}
        label={label}
        onPrev={() => setAnchor(shift(view, anchor, -1, zoom))}
        onNext={() => setAnchor(shift(view, anchor, 1, zoom))}
        onToday={() => setAnchor(new Date())}
        zoom={zoom}
        onZoom={setZoom}
        search={search}
        onSearch={setSearch}
        filtersOpen={filtersOpen}
        onToggleFilters={() => setFiltersOpen(!filtersOpen)}
        activeFilters={countFilters(filters)}
        canCreate={canCreate}
        onCreate={() => setEditing({ event: null })}
      />
      {filtersOpen && (
        <CalendarFilters
          value={filters}
          onChange={setFilters}
          projects={projects.data ?? []}
          people={people.data ?? []}
        />
      )}
      {events.error && <ErrorNotice error={events.error} onRetry={events.reload} />}
      {events.loading && !events.data && <Loading />}
      {events.data && (
        <div className={`cal-body ${events.loading ? "busy" : ""}`}>
          {events.data.count > events.data.results.length && (
            <div className="notice">
              {events.data.results.length} éléments affichés sur {events.data.count} : affinez la période ou les
              filtres.
            </div>
          )}
          {view === "month" && <CalendarMonthView {...gridProps} />}
          {view === "week" && <CalendarWeekView {...gridProps} />}
          {view === "day" && <CalendarDayView {...gridProps} />}
          {view === "mine" && <CalendarGrid mode="listTwoWeeks" {...gridProps} />}
          {view === "people" && <CalendarResourceView group="user" workload={workload.data} {...rowProps} />}
          {view === "teams" && <CalendarResourceView group="team" workload={workload.data} {...rowProps} />}
          {view === "timeline" && <CalendarTimelineView {...rowProps} />}
          {view === "gantt" && <CalendarGanttView {...rowProps} />}
          {view === "portfolio" && (
            <CalendarPortfolioView
              onProject={(id) => {
                setFilters({ ...EMPTY_FILTERS, project: id });
                setView("gantt");
              }}
            />
          )}
          {view === "dashboard" && (
            <CalendarDashboard params={params} onOpen={(id) => void openId(id)} onApply={applySuggestion} />
          )}
        </div>
      )}
      {editing && (
        <CalendarEventModal
          event={editing.event}
          preset={editing.preset}
          projects={projects.data ?? []}
          others={list}
          onSave={(input) => save(editing.event?.id ?? null, input)}
          onDelete={async () => {
            if (!editing.event || !window.confirm(`Supprimer « ${editing.event.title} » ?`)) return;
            try {
              await calendarApi.remove(editing.event.id);
              toast("Événement supprimé");
              setEditing(null);
              events.reload();
            } catch (err) {
              if (err instanceof ApiError) toast(err.message, true);
            }
          }}
          onClose={() => setEditing(null)}
        />
      )}
      {pending && (
        <ConflictDialog
          conflicts={pending.conflicts}
          busy={busy}
          onCancel={() => void settle(pending, null)}
          onConfirm={() => void settle(pending, { ...pending.input, confirm: true })}
          onApply={(c) => {
            const s = c.suggestion!;
            // La proposition remplace les dates saisies ; le reste de la modification est conservé.
            // Pour une création, l'identifiant proposé est celui de l'élément en cours (pas encore enregistré).
            const self = s.event === pending.id || (pending.id === null && !list.some((e) => e.id === s.event));
            if (self) void settle(pending, { ...pending.input, start: s.start, end: s.end, allDay: s.allDay });
            else {
              setPending(null);
              pending.resolve(false);
              void applySuggestion(c);
            }
          }}
        />
      )}
    </div>
  );
}
