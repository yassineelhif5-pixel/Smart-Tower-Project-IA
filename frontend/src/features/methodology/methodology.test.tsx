import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { routesFor } from "../../App";
import { ToastProvider } from "../../components/ui";
import { MethodologySettingsPage } from "../../pages/methodology/MethodologySettingsPage";
import type { Me } from "../../types/api";
import type { MethodInfo } from "../../types/methodology";
import { LineChart, Status, toneOf } from "./shared";

const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
afterEach(() => vi.restoreAllMocks());

const info = (over: Partial<MethodInfo> = {}): MethodInfo => ({
  project: { id: "p1", code: "NDL-MIG", name: "Migration", start: null, end: null, pm: "É. Navarro" },
  kind: "vcycle",
  kindLabel: "Cycle en V",
  features: ["phases", "weekly", "capacity", "retro"],
  customFeatures: [],
  settings: {
    productiveRatio: 1,
    sprintWeeks: 2,
    boardColumns: [
      { key: "todo", label: "À faire", done: false },
      { key: "done", label: "Terminé", done: true },
    ],
    retroFrequency: "phase",
    reminderHours: [48, 24, 0],
    dailyTime: "09:30",
    dailyMinutes: 15,
    dailyInCalendar: true,
    weeklyPlanningDay: 0,
    weeklyPlanningTime: "09:00",
    timezone: "Europe/Paris",
  },
  history: [],
  myScrumRole: "",
  can: { edit: true, plan: true, approve: true, capacity: true, prioritize: false },
  tenantPolicy: { reminderHours: [48, 24, 0], allowAnonymous: false },
  ...over,
});

describe("écran Pilotage selon les droits", () => {
  const me = (permissions: Me["permissions"], over: Partial<Me> = {}): Me => ({
    id: 1,
    username: "u",
    name: "U",
    email: "",
    title: "",
    role: { code: "cdp", label: "CdP" },
    isAdmin: false,
    isPlatformAdmin: false,
    tenant: { slug: "a", name: "A", status: "active" },
    mustChangePassword: false,
    permissions,
    capabilities: [],
    ...over,
  });
  const read: [boolean, boolean, boolean, boolean, boolean] = [true, false, false, false, false];
  it("apparaît avec le droit Méthodologie · Voir", () => {
    expect(routesFor(me({ methodology: read }))).toEqual(["pilotage", "acces"]);
  });
  it("n'apparaît jamais pour le Pilote", () => {
    expect(routesFor(me({ methodology: read }, { isPlatformAdmin: true, tenant: null }))).toEqual(["pilote", "acces"]);
  });
});

describe("changement de méthodologie", () => {
  it("exige une analyse d'impact avant d'appliquer", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((url) =>
      String(url).endsWith("/impact")
        ? json({
            from: "vcycle",
            to: "scrum",
            enabled: ["scrum"],
            disabled: ["phases", "weekly"],
            warnings: ["2 semaine(s) non clôturée(s) ne seront plus suivies."],
            activeSprints: 0,
            backlogItems: 0,
            openWeeklyPlans: 2,
            phases: 12,
            openRetros: 0,
          })
        : json({}),
    );
    render(
      <ToastProvider>
        <MethodologySettingsPage info={info()} reload={() => undefined} />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByLabelText(/Scrum/, { selector: "input" }));
    const apply = screen.getByRole("button", { name: "Appliquer le changement" });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Analyser l'impact" }));
    await waitFor(() => expect(screen.getByText(/ne seront plus suivies/)).toBeInTheDocument());
    expect(screen.getByText(/Aucune donnée n'est supprimée/)).toBeInTheDocument();
    expect(apply).toBeEnabled();
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/methodology/projects/p1/impact"))).toBe(true);
  });
  it("est réservé au droit Valider", () => {
    render(
      <ToastProvider>
        <MethodologySettingsPage
          info={info({ can: { edit: false, plan: false, approve: false, capacity: false, prioritize: false } })}
          reload={() => undefined}
        />
      </ToastProvider>,
    );
    expect(screen.getByText(/réservé au droit « Méthodologie · Valider »/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Analyser l'impact" })).not.toBeInTheDocument();
  });
});

describe("éléments communs", () => {
  it("les statuts ont une tonalité cohérente", () => {
    expect([toneOf("achieved"), toneOf("partial"), toneOf("missed"), toneOf("over")]).toEqual([
      "ok",
      "warn",
      "crit",
      "crit",
    ]);
    render(<Status value="partial" />);
    expect(screen.getByText("Partiellement atteint")).toBeInTheDocument();
  });
  it("le burndown ne trace pas les jours futurs", () => {
    const { container } = render(
      <LineChart
        labels={["2026-11-02", "2026-11-03", "2026-11-04"]}
        series={[{ name: "Restant", values: [10, 6, null], color: "red" }]}
      />,
    );
    expect(container.querySelector("polyline")!.getAttribute("points")!.split(" ")).toHaveLength(2);
  });
});
