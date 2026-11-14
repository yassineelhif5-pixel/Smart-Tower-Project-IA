import { Icon } from "../../components/ui";
import { VIEWS, type View } from "./calendarUtils";

const ZOOMABLE: View[] = ["people", "teams", "timeline", "gantt"];

/** Navigation de période, choix de la vue, zoom, recherche et création. */
export function CalendarToolbar({
  view,
  onView,
  label,
  onPrev,
  onNext,
  onToday,
  zoom,
  onZoom,
  search,
  onSearch,
  filtersOpen,
  onToggleFilters,
  activeFilters,
  canCreate,
  onCreate,
}: {
  view: View;
  onView: (v: View) => void;
  label: string;
  onPrev: () => void;
  onNext: () => void;
  onToday: () => void;
  zoom: number;
  onZoom: (z: number) => void;
  search: string;
  onSearch: (s: string) => void;
  filtersOpen: boolean;
  onToggleFilters: () => void;
  activeFilters: number;
  canCreate: boolean;
  onCreate: () => void;
}) {
  return (
    <div className="cal-toolbar">
      <div className="cal-nav">
        <button className="btn sm" onClick={onToday}>
          Aujourd'hui
        </button>
        <button className="icon-btn" onClick={onPrev} aria-label="Période précédente">
          <Icon name="chevL" />
        </button>
        <button className="icon-btn" onClick={onNext} aria-label="Période suivante">
          <Icon name="chevR" />
        </button>
        <h2 className="cal-title" aria-live="polite">
          {label}
        </h2>
      </div>
      <div className="cal-views" role="tablist" aria-label="Vues du calendrier">
        {VIEWS.map(([v, l]) => (
          <button
            key={v}
            role="tab"
            aria-selected={view === v}
            className={view === v ? "on" : ""}
            onClick={() => onView(v)}
          >
            {l}
          </button>
        ))}
      </div>
      <div className="cal-tools">
        {ZOOMABLE.includes(view) && (
          <div className="seg" aria-label="Zoom">
            {[
              [2, "2 sem."],
              [6, "6 sem."],
              [13, "Trimestre"],
            ].map(([z, l]) => (
              <button key={z} className={zoom === z ? "on" : ""} onClick={() => onZoom(Number(z))}>
                {l}
              </button>
            ))}
          </div>
        )}
        <input
          className="inp cal-search"
          type="search"
          placeholder="Rechercher (titre, projet)…"
          aria-label="Rechercher dans le calendrier"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
        />
        <button className={`btn sm ${filtersOpen ? "on" : ""}`} onClick={onToggleFilters} aria-expanded={filtersOpen}>
          <Icon name="filter" size={15} /> Filtres{activeFilters ? ` (${activeFilters})` : ""}
        </button>
        {canCreate && (
          <button className="btn sm primary" onClick={onCreate}>
            <Icon name="plus" size={15} /> Nouvel événement
          </button>
        )}
      </div>
    </div>
  );
}
