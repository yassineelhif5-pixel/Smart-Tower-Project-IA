import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CalendarEvent, Conflict } from "../../types/collab";
import { ConflictDialog } from "./CalendarConflicts";
import { DEFAULT_COLORS, moved, rangeFor, shift } from "./calendarUtils";
import { RowTimeline } from "./RowTimeline";

const ev = (over: Partial<CalendarEvent> = {}): CalendarEvent => ({
  id: 7,
  kind: "task",
  title: "Recette",
  description: "",
  phase: "",
  project: { id: "p1", code: "NDL-MIG", name: "Migration" },
  action: null,
  start: "2026-11-09T23:00:00Z",
  end: "2026-11-11T23:00:00Z",
  allDay: true,
  timezone: "Europe/Paris",
  startDate: "2026-11-10",
  endDate: "2026-11-11",
  status: "planned",
  statusLabel: "Planifiée",
  priority: "normal",
  priorityLabel: "Normale",
  progress: 40,
  late: false,
  assignments: [],
  dependencies: [],
  canEdit: true,
  canUpdateProgress: true,
  canDelete: true,
  createdBy: "e.navarro",
  completedAt: null,
  ...over,
});

describe("dates du calendrier", () => {
  it("la vue Mois couvre des semaines complètes du lundi au dimanche", () => {
    const r = rangeFor("month", new Date(2026, 10, 15), 6);
    expect(r.start.getDay()).toBe(1);
    expect(r.end.getDay()).toBe(0);
    expect(r.start <= new Date(2026, 10, 1) && r.end >= new Date(2026, 10, 30)).toBe(true);
  });
  it("déplacer une journée entière garde la durée ; allonger ne bouge que la fin", () => {
    expect(moved(ev(), 3)).toEqual({ start: "2026-11-13", end: "2026-11-14", allDay: true });
    expect(moved(ev(), 0, 2)).toEqual({ start: "2026-11-10", end: "2026-11-13", allDay: true });
  });
  it("un événement horaire déplacé part en instant UTC explicite", () => {
    const r = moved(ev({ allDay: false, start: "2026-11-10T09:00:00Z", end: "2026-11-10T10:00:00Z" }), 1);
    expect(r).toEqual({ start: "2026-11-11T09:00:00.000Z", end: "2026-11-11T10:00:00.000Z", allDay: false });
  });
  it("navigation : mois suivant, semaine suivante", () => {
    expect(shift("month", new Date(2026, 0, 31), 1, 6).getMonth()).toBe(1);
    expect(shift("week", new Date(2026, 10, 2), 1, 6).getDate()).toBe(9);
  });
});

describe("frise en lignes", () => {
  it("se déplace au clavier sans rien enregistrer d'autre", () => {
    const onMove = vi.fn().mockResolvedValue(true);
    render(
      <RowTimeline
        start={new Date(2026, 10, 9)}
        end={new Date(2026, 10, 22)}
        rows={[{ key: "p1", label: "NDL-MIG", events: [ev()] }]}
        colors={DEFAULT_COLORS}
        onOpen={vi.fn()}
        onMove={onMove}
      />,
    );
    const bar = screen.getByRole("button", { name: /Recette/ });
    fireEvent.keyDown(bar, { key: "ArrowRight" });
    expect(onMove).toHaveBeenCalledWith(expect.objectContaining({ id: 7 }), {
      start: "2026-11-11",
      end: "2026-11-12",
      allDay: true,
    });
    fireEvent.keyDown(bar, { key: "ArrowRight", shiftKey: true });
    expect(onMove).toHaveBeenLastCalledWith(expect.objectContaining({ id: 7 }), {
      start: "2026-11-10",
      end: "2026-11-12",
      allDay: true,
    });
  });
  it("un élément non modifiable ne bouge pas", () => {
    const onMove = vi.fn();
    render(
      <RowTimeline
        start={new Date(2026, 10, 9)}
        end={new Date(2026, 10, 22)}
        rows={[{ key: "p1", label: "NDL-MIG", events: [ev({ canEdit: false })] }]}
        colors={DEFAULT_COLORS}
        onOpen={vi.fn()}
        onMove={onMove}
      />,
    );
    fireEvent.keyDown(screen.getByRole("button", { name: /Recette/ }), { key: "ArrowRight" });
    expect(onMove).not.toHaveBeenCalled();
  });
});

describe("conflits", () => {
  const conflict: Conflict = {
    type: "double_booking",
    severity: "warning",
    title: "S. Mansouri est attendue à deux endroits",
    explanation: "« Revue » et « Démo » se chevauchent pour S. Mansouri.",
    events: [1, 2],
    users: [3],
    suggestion: { event: 2, action: "move", start: "2026-11-10T11:00:00Z", end: "2026-11-10T13:00:00Z", allDay: false },
  };
  it("explique, propose et laisse décider", () => {
    const onApply = vi.fn();
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConflictDialog
        conflicts={[conflict]}
        onApply={onApply}
        onConfirm={onConfirm}
        onCancel={onCancel}
        busy={false}
      />,
    );
    expect(screen.getByText(/se chevauchent/)).toBeInTheDocument();
    expect(screen.getByText(/Rien n'a été enregistré/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Appliquer la proposition/ }));
    expect(onApply).toHaveBeenCalledWith(conflict);
    fireEvent.click(screen.getByRole("button", { name: "Enregistrer malgré tout" }));
    expect(onConfirm).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Annuler la modification" }));
    expect(onCancel).toHaveBeenCalled();
  });
});
