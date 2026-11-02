import { useEffect, useState } from "react";

import { methodologyApi } from "../api/methodology";
import { useApi } from "../api/useApi";
import { ErrorNotice, Loading, PageHead, Tabs } from "../components/ui";
import type { Feature } from "../types/methodology";
import type { Me } from "../types/api";
import { MethodologySettingsPage } from "./methodology/MethodologySettingsPage";
import { ProductBacklogPage } from "./methodology/ProductBacklogPage";
import { MethodologyReportsPage, RetrospectiveActionsPage, RetrospectivePage } from "./methodology/RetrospectivePages";
import { DailyScrumPage, ScrumDashboardPage, SprintGoalPage, SprintReviewPage } from "./methodology/ScrumPages";
import { SprintBoardPage } from "./methodology/SprintBoardPage";
import { SprintPlanningPage } from "./methodology/SprintPlanningPage";
import { TeamCapacityPage } from "./methodology/TeamCapacityPage";
import { WeeklyGoalPage } from "./methodology/WeeklyGoalPage";
import { WeeklyPlanningPage } from "./methodology/WeeklyPlanningPage";

type Tab =
  | "scrum"
  | "backlog"
  | "planning"
  | "board"
  | "goal"
  | "daily"
  | "review"
  | "week"
  | "goals"
  | "capacity"
  | "retro"
  | "improvements"
  | "reports"
  | "settings";

const TABS: [Tab, string, Feature | null][] = [
  ["week", "Semaine", "weekly"],
  ["goals", "Weekly Goals", "weekly"],
  ["scrum", "Tableau de bord Scrum", "scrum"],
  ["backlog", "Product Backlog", "scrum"],
  ["planning", "Sprint Planning", "scrum"],
  ["board", "Sprint Board", "scrum"],
  ["goal", "Sprint Goal", "scrum"],
  ["daily", "Daily Scrum", "scrum"],
  ["review", "Sprint Review", "scrum"],
  ["capacity", "Capacité", "capacity"],
  ["retro", "Rétrospectives", "retro"],
  ["improvements", "Actions d'amélioration", "retro"],
  ["reports", "Rapports", null],
  ["settings", "Méthodologie", null],
];

const fromHash = () => {
  const [, project, tab] = window.location.hash.replace("#", "").split("/");
  return { project: project ?? "", tab: (tab ?? "") as Tab };
};

/** Pilotage méthodologique : écrans activés selon la méthodologie du projet (Cycle en V, Scrum, hybride, personnalisée). */
export function MethodologyPage({ me }: { me: Me }) {
  const projects = useApi(methodologyApi.projects);
  const initial = fromHash();
  const [project, setProject] = useState(initial.project);
  const [tab, setTab] = useState<Tab>(initial.tab);
  const info = useApi(() => (project ? methodologyApi.get(project) : Promise.resolve(null)), [project]);

  useEffect(() => {
    if (!project && projects.data?.length) setProject(projects.data[0].id);
  }, [projects.data, project]);
  const tabs = TABS.filter(([, , f]) => !f || info.data?.features.includes(f));
  const active = tabs.some(([k]) => k === tab) ? tab : tabs[0]?.[0];
  useEffect(() => {
    if (project && active) window.history.replaceState(null, "", `#pilotage/${project}/${active}`);
  }, [project, active]);

  const props = info.data ? { info: info.data, reload: () => (info.reload(), projects.reload()) } : null;
  return (
    <div className="page">
      <PageHead
        eyebrow={me.tenant?.name ?? ""}
        title="Pilotage"
        sub="Cycle en V et Scrum, avec la capacité réelle de l'équipe. Rien n'est validé, affecté ou sélectionné sans vous."
        right={
          <select
            className="inp"
            aria-label="Projet"
            value={project}
            onChange={(e) => (setProject(e.target.value), setTab("" as Tab))}
            style={{ minWidth: 280 }}
          >
            {(projects.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.code} — {p.name} ({p.kindLabel})
              </option>
            ))}
          </select>
        }
      />
      {projects.error && <ErrorNotice error={projects.error} onRetry={projects.reload} />}
      {info.error && <ErrorNotice error={info.error} onRetry={info.reload} />}
      {(projects.loading || info.loading) && !props && <Loading />}
      {projects.data && !projects.data.length && <div className="empty">Aucun projet dans votre périmètre.</div>}
      {props && active && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="method-head">
            <span className="pill acc">{props.info.kindLabel}</span>
            {props.info.myScrumRole && (
              <span className="pill">
                {{ po: "Product Owner", sm: "Scrum Master", dev: "Developer" }[props.info.myScrumRole]}
              </span>
            )}
          </div>
          <Tabs<Tab> tabs={tabs.map(([k, l]) => [k, l])} value={active} onChange={setTab} />
          <div key={`${project}-${active}`}>
            {active === "week" && <WeeklyPlanningPage {...props} />}
            {active === "goals" && <WeeklyGoalPage {...props} />}
            {active === "scrum" && <ScrumDashboardPage {...props} />}
            {active === "backlog" && <ProductBacklogPage {...props} />}
            {active === "planning" && <SprintPlanningPage {...props} />}
            {active === "board" && <SprintBoardPage {...props} />}
            {active === "goal" && <SprintGoalPage {...props} />}
            {active === "daily" && <DailyScrumPage {...props} />}
            {active === "review" && <SprintReviewPage {...props} />}
            {active === "capacity" && <TeamCapacityPage {...props} />}
            {active === "retro" && <RetrospectivePage {...props} />}
            {active === "improvements" && <RetrospectiveActionsPage {...props} />}
            {active === "reports" && <MethodologyReportsPage {...props} />}
            {active === "settings" && <MethodologySettingsPage {...props} />}
          </div>
        </div>
      )}
    </div>
  );
}
