import type {
  Access,
  AdminProject,
  AdminUser,
  ApiLog,
  ApiStats,
  ApiToken,
  AuditRow,
  CreatedUser,
  DatabaseStatus,
  Endpoint,
  Flags,
  Me,
  NotificationSettings,
  RolesResponse,
  Secret,
  UserInput,
} from "../types/api";
import { api } from "./client";

export const authApi = {
  me: () => api.get<Me>("/auth/me"),
  login: (username: string, password: string) => api.post<Me>("/auth/login", { username, password }),
  logout: () => api.post<void>("/auth/logout"),
  changePassword: (current_password: string, new_password: string) =>
    api.post<Me>("/auth/change-password", { current_password, new_password }),
};

export const adminApi = {
  users: () => api.get<AdminUser[]>("/admin/users"),
  createUser: (input: UserInput) => api.post<CreatedUser>("/admin/users", input),
  updateUser: (id: number, input: UserInput) => api.patch<AdminUser>(`/admin/users/${id}`, input),
  resetPassword: (id: number) => api.post<{ temporaryPassword: string }>(`/admin/users/${id}/reset-password`),
  access: (id: number) => api.get<Access>(`/admin/users/${id}/access`),
  setAccess: (id: number, access: Access) => api.put<Access>(`/admin/users/${id}/access`, access),
  projects: () => api.get<AdminProject[]>("/admin/projects"),
  roles: () => api.get<RolesResponse>("/admin/roles"),
  setPermissions: (code: string, permissions: Record<string, Flags>) =>
    api.put<{ code: string; permissions: Record<string, Flags> }>(`/admin/roles/${code}/permissions`, { permissions }),
  database: () => api.get<DatabaseStatus>("/admin/database"),
  testDatabase: () => api.post<DatabaseStatus>("/admin/database/test"),
  endpoints: () => api.get<Endpoint[]>("/admin/api/endpoints"),
  stats: (hours: number) => api.get<ApiStats>(`/admin/api/stats?hours=${hours}`),
  logs: (errorsOnly: boolean) => api.get<ApiLog[]>(`/admin/api/logs?limit=100${errorsOnly ? "&errors=1" : ""}`),
  tokens: () => api.get<ApiToken[]>("/admin/api/tokens"),
  createToken: (input: { name: string; user: number; readOnly: boolean; expiresInDays: number | null }) =>
    api.post<ApiToken & { token: string }>("/admin/api/tokens", input),
  revokeToken: (id: number) => api.post<ApiToken>(`/admin/api/tokens/${id}/revoke`),
  secrets: () => api.get<Secret[]>("/admin/secrets"),
  setSecret: (key: string, value: string) => api.put<Secret>(`/admin/secrets/${key}`, { value }),
  deleteSecret: (key: string) => api.delete<Secret>(`/admin/secrets/${key}`),
  notifications: () => api.get<NotificationSettings>("/admin/notifications"),
  setChannel: (kind: string, enabled: boolean, settings: Record<string, string | number>) =>
    api.put<NotificationSettings>(`/admin/notifications/channels/${kind}`, { enabled, settings }),
  setRules: (rules: Record<string, Record<string, boolean>>) =>
    api.put<NotificationSettings>("/admin/notifications/rules", { rules }),
  testChannel: (kind: string, to?: string) =>
    api.post<{ sent: boolean }>(`/admin/notifications/channels/${kind}/test`, to ? { to } : {}),
  audit: () => api.get<AuditRow[]>("/admin/audit?limit=200"),
};
