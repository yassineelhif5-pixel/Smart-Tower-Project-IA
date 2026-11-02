// Appels du calendrier et de la collaboration. Tout passe par client.ts (cookie de session, jeton CSRF, erreurs).
import type {
  CalendarColors,
  CalendarDashboardData,
  CalendarEvent,
  Conflict,
  Discussion,
  DiscussionInput,
  EventInput,
  EventPage,
  Message,
  NotificationPreferences,
  Person,
  PortfolioRow,
  ProjectRef,
  Reminder,
  TeamsConnectorSettings,
  TeamsStatus,
  Workload,
} from "../types/collab";
import { api } from "./client";

export type Query = Record<string, string | number | boolean | undefined | null>;

export const qs = (params: Query) => {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, String(v === true ? 1 : v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const calendarApi = {
  events: (params: Query) => api.get<EventPage>(`/calendar/events${qs({ limit: 2000, ...params })}`),
  event: (id: number) => api.get<CalendarEvent>(`/calendar/events/${id}`),
  create: (input: EventInput) => api.post<CalendarEvent>("/calendar/events", input),
  update: (id: number, input: EventInput) => api.patch<CalendarEvent>(`/calendar/events/${id}`, input),
  remove: (id: number) => api.delete<void>(`/calendar/events/${id}`),
  workload: (params: Query) => api.get<Workload>(`/calendar/workload${qs(params)}`),
  conflicts: (params: Query) => api.get<Conflict[]>(`/calendar/conflicts${qs(params)}`),
  dashboard: (params: Query) => api.get<CalendarDashboardData>(`/calendar/dashboard${qs(params)}`),
  portfolio: () => api.get<PortfolioRow[]>("/calendar/portfolio"),
  settings: () => api.get<CalendarColors>("/calendar/settings"),
  saveSettings: (value: Partial<CalendarColors>) => api.put<CalendarColors>("/calendar/settings", value),
  people: (project?: string) => api.get<Person[]>(`/calendar/people${qs({ project })}`),
  projects: () => api.get<ProjectRef[]>("/projects"),
  reminders: (id: number) => api.get<Reminder[]>(`/calendar/events/${id}/reminders`),
  addReminder: (id: number, remindAt: string, channel: string) =>
    api.post<Reminder>(`/calendar/events/${id}/reminders`, { remindAt, channel }),
  cancelReminder: (id: number) => api.delete<void>(`/calendar/reminders/${id}`),
  feedToken: () => api.post<{ url: string }>("/calendar/feed-token"),
  revokeFeed: () => api.delete<void>("/calendar/feed-token"),
};

export const discussionApi = {
  list: (params: Query) => api.get<Discussion[]>(`/discussions${qs(params)}`),
  get: (id: number) => api.get<Discussion>(`/discussions/${id}`),
  create: (input: DiscussionInput) => api.post<Discussion>("/discussions", input),
  update: (id: number, input: { title?: string; status?: string }) =>
    api.patch<Discussion>(`/discussions/${id}`, input),
  messages: (id: number) => api.get<Message[]>(`/discussions/${id}/messages`),
  post: (
    id: number,
    input: { body: string; parent?: number | null; mentions?: number[]; attachments?: string[]; clientKey: string },
  ) => api.post<Message>(`/discussions/${id}/messages`, input),
  documents: (id: number) =>
    api.get<{ id: string; name: string; ext: string; status: string }[]>(`/discussions/${id}/documents`),
  edit: (id: number, body: string) => api.patch<Message>(`/messages/${id}`, { body }),
  remove: (id: number) => api.delete<void>(`/messages/${id}`),
  history: (id: number) =>
    api.get<Message & { history: { at: string; body: string; deleted?: boolean }[] }>(`/messages/${id}`),
  retry: (id: number) => api.post<Message>(`/messages/${id}/retry`),
  synchronize: (id: number) =>
    api.post<{ created: number; updated: number; deleted: number }>(`/discussions/${id}/synchronize`),
};

export const teamsApi = {
  status: () => api.get<TeamsStatus>("/teams/connection-status"),
  connect: () => api.post<{ url: string }>("/teams/oauth/start"),
  unlink: () => api.post<TeamsStatus>("/teams/unlink"),
  joinedTeams: () => api.get<{ id: string; name: string }[]>("/teams/joined-teams"),
  channels: (teamId: string) =>
    api.get<{ id: string; name: string; membership: string }[]>(`/teams/teams/${encodeURIComponent(teamId)}/channels`),
  createChannel: (teamId: string, name: string, description: string) =>
    api.post<{ id: string; name: string }>(`/teams/teams/${encodeURIComponent(teamId)}/channels`, {
      name,
      description,
    }),
  admin: () => api.get<TeamsConnectorSettings>("/admin/teams"),
  saveAdmin: (input: Partial<TeamsConnectorSettings> & { clientSecret?: string }) =>
    api.put<TeamsConnectorSettings>("/admin/teams", input),
  check: () => api.post<TeamsConnectorSettings & { ok: boolean; message: string }>("/admin/teams/check"),
};

export const preferencesApi = {
  get: () => api.get<NotificationPreferences>("/me/notification-preferences"),
  save: (preferences: { event: string; channel: string; enabled: boolean }[]) =>
    api.put<NotificationPreferences>("/me/notification-preferences", { preferences }),
};
