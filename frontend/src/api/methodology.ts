// Appels du pilotage méthodologique (Cycle en V, Scrum, capacité, rétrospectives).
import type {
  Allocation,
  Assist,
  Availability,
  BacklogItem,
  Capacity,
  DailyData,
  DailyEntry,
  Impact,
  Improvement,
  MethodInfo,
  MethodProject,
  Phase,
  PlanningData,
  RetroDetail,
  RetroRow,
  ReviewData,
  ScrumDashboard,
  SprintDetail,
  SprintEntry,
  SprintRow,
  Velocity,
  WeekData,
  WeeklyGoal,
  WeeklyPlan,
  Tracking,
  BoardColumn,
} from "../types/methodology";
import { api } from "./client";
import { qs } from "./collab";

type Body = Record<string, unknown>;
const P = (id: string) => `/methodology/projects/${encodeURIComponent(id)}`;

export const methodologyApi = {
  projects: () => api.get<MethodProject[]>("/methodology/projects"),
  get: (id: string) => api.get<MethodInfo>(P(id)),
  save: (id: string, body: Body) => api.put<MethodInfo>(P(id), body),
  impact: (id: string, kind: string, features?: string[]) => api.post<Impact>(`${P(id)}/impact`, { kind, features }),
  policy: () => api.get<{ reminderHours: number[]; allowAnonymous: boolean }>("/methodology/policy"),
  savePolicy: (body: Body) =>
    api.put<{ reminderHours: number[]; allowAnonymous: boolean }>("/methodology/policy", body),
  assist: (id: string, topic: string) => api.get<Assist>(`${P(id)}/assist?topic=${topic}`),
  reports: (id: string) => api.get<Record<string, unknown>>(`${P(id)}/reports`),

  capacity: (id: string, start: string, end: string) => api.get<Capacity>(`${P(id)}/capacity${qs({ start, end })}`),
  allocations: (id: string) => api.get<Allocation[]>(`${P(id)}/allocations`),
  addAllocation: (id: string, body: Body) => api.post<Allocation>(`${P(id)}/allocations`, body),
  saveAllocation: (aid: number, body: Body) => api.patch<Allocation>(`/methodology/allocations/${aid}`, body),
  removeAllocation: (aid: number) => api.delete<void>(`/methodology/allocations/${aid}`),
  availabilities: (params: Record<string, string>) =>
    api.get<{ kinds: { code: string; label: string }[]; rows: Availability[] }>(
      `/methodology/availabilities${qs(params)}`,
    ),
  addAvailability: (body: Body) => api.post<Availability>("/methodology/availabilities", body),
  removeAvailability: (aid: number) => api.delete<void>(`/methodology/availabilities/${aid}`),

  phases: (id: string) =>
    api.get<{
      phases: Phase[];
      milestones: { id: number; title: string; date: string; status: string; phase: string }[];
    }>(`${P(id)}/phases`),
  addPhase: (id: string, body: Body) => api.post<Phase>(`${P(id)}/phases`, body),
  savePhase: (pid: number, body: Body) => api.patch<Phase>(`/methodology/phases/${pid}`, body),

  week: (id: string, week: string) => api.get<WeekData>(`${P(id)}/weeks/${week}`),
  weekAction: (id: string, week: string, action: string, body: Body = {}) =>
    api.post<{ plan: WeeklyPlan; tracking: Tracking }>(`${P(id)}/weeks/${week}/${action}`, body),
  saveGoal: (gid: number, body: Body) => api.patch<WeeklyGoal>(`/methodology/goals/${gid}`, body),
  removeGoal: (gid: number) => api.delete<void>(`/methodology/goals/${gid}`),

  backlog: (id: string, params: Record<string, string> = {}) => api.get<BacklogItem[]>(`${P(id)}/backlog${qs(params)}`),
  addItem: (id: string, body: Body) => api.post<BacklogItem>(`${P(id)}/backlog`, body),
  saveItem: (iid: number, body: Body) => api.patch<BacklogItem>(`/methodology/backlog/${iid}`, body),
  item: (iid: number) =>
    api.get<BacklogItem & { history: { at: string; by: string; event: string }[] }>(`/methodology/backlog/${iid}`),
  reorder: (id: string, ids: number[]) => api.post<{ ok: boolean }>(`${P(id)}/backlog/reorder`, { ids }),

  sprints: (id: string) =>
    api.get<{ sprints: SprintRow[]; velocity: Velocity; columns: BoardColumn[] }>(`${P(id)}/sprints`),
  addSprint: (id: string, body: Body) => api.post<SprintRow>(`${P(id)}/sprints`, body),
  sprint: (sid: number) => api.get<SprintDetail>(`/methodology/sprints/${sid}`),
  planning: (sid: number) => api.get<PlanningData>(`/methodology/sprints/${sid}/planning`),
  sprintAction: (sid: number, action: string, body: Body = {}) =>
    api.post<SprintRow & { retro?: RetroRow }>(`/methodology/sprints/${sid}/${action}`, body),
  moveEntry: (eid: number, body: Body) => api.patch<SprintEntry>(`/methodology/sprint-items/${eid}`, body),
  daily: (sid: number, date: string) => api.get<DailyData>(`/methodology/sprints/${sid}/daily?date=${date}`),
  saveDaily: (sid: number, body: Body) => api.post<DailyData>(`/methodology/sprints/${sid}/daily`, body),
  saveImpediment: (eid: number, body: Body) => api.patch<DailyEntry>(`/methodology/impediments/${eid}`, body),
  review: (sid: number) => api.get<ReviewData>(`/methodology/sprints/${sid}/review`),
  saveReview: (sid: number, body: Body) => api.post<ReviewData>(`/methodology/sprints/${sid}/review`, body),
  scrumDashboard: (id: string) => api.get<ScrumDashboard>(`${P(id)}/scrum-dashboard`),

  retros: (id: string) =>
    api.get<{ retros: RetroRow[]; improvements: Improvement[]; rate: number | null }>(`${P(id)}/retros`),
  addRetro: (id: string, body: Body) => api.post<RetroRow>(`${P(id)}/retros`, body),
  retro: (rid: number) => api.get<RetroDetail>(`/methodology/retros/${rid}`),
  saveRetro: (rid: number, body: Body) => api.patch<RetroDetail>(`/methodology/retros/${rid}`, body),
  retroAction: (rid: number, action: string, body: Body) =>
    api.post<RetroDetail>(`/methodology/retros/${rid}/${action}`, body),
  vote: (fid: number) => api.post<void>(`/methodology/feedback/${fid}/vote`),
  saveImprovement: (iid: number, body: Body) => api.patch<Improvement>(`/methodology/improvements/${iid}`, body),
};
