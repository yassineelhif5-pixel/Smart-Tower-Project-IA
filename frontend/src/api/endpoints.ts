import type {
  CapabilityMatrix,
  CreatedTenant,
  LicenseList,
  LicenseRequest,
  LicenseRow,
  LicensingOverview,
  MyAccess,
  Offer,
  OfferVersion,
  PilotDashboard,
  PlatformAuditRow,
  SessionRow,
  TenantDetail,
  TenantRow,
  TenantSubscriptionDetail,
  UserCapabilities,
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

export const meApi = {
  access: () => api.get<MyAccess>("/me/access"),
};

/** Délégation des droits d'administration (administrateur du tenant). */
export const delegationApi = {
  matrix: () => api.get<CapabilityMatrix>("/admin/capabilities"),
  setMatrix: (roles: Record<string, string[]>) => api.put<CapabilityMatrix>("/admin/capabilities", { roles }),
  ofUser: (id: number) => api.get<UserCapabilities>(`/admin/users/${id}/capabilities`),
  setUser: (id: number, overrides: { code: string; granted: boolean }[]) =>
    api.put<UserCapabilities>(`/admin/users/${id}/capabilities`, { overrides }),
};

/** Espace entreprise : licences, sessions, demandes. */
export const licensingApi = {
  overview: () => api.get<LicensingOverview>("/licensing/overview"),
  licenses: () => api.get<LicenseList>("/licensing/licenses"),
  act: (id: number, action: "assign" | "release" | "reassign", body: { user?: number; reason?: string }) =>
    api.post<LicenseRow>(`/licensing/licenses/${id}/${action}`, body),
  sessions: () => api.get<SessionRow[]>("/licensing/sessions"),
  revokeSession: (id: number) => api.post<void>(`/licensing/sessions/${id}/revoke`),
  requests: () => api.get<LicenseRequest[]>("/licensing/requests"),
  request: (id: number) => api.get<LicenseRequest>(`/licensing/requests/${id}`),
  createRequest: (body: {
    kind: string;
    quantity?: number | null;
    targetOffer?: number | null;
    justification: string;
  }) => api.post<LicenseRequest>("/licensing/requests", body),
  requestAction: (id: number, action: "submit" | "cancel" | "comment", comment = "") =>
    api.post<LicenseRequest>(`/licensing/requests/${id}/${action}`, { comment }),
  offers: () => api.get<{ id: number; code: string; name: string; description: string }[]>("/licensing/offers"),
};

/** Espace Pilote (Super Admin Global). */
export const platformApi = {
  dashboard: () => api.get<PilotDashboard>("/platform/dashboard"),
  tenants: (q = "", status = "") =>
    api.get<TenantRow[]>(`/platform/tenants?q=${encodeURIComponent(q)}&status=${encodeURIComponent(status)}`),
  tenant: (id: number) => api.get<TenantDetail>(`/platform/tenants/${id}`),
  createTenant: (body: Record<string, unknown>) => api.post<CreatedTenant>("/platform/tenants", body),
  updateTenant: (id: number, body: { name?: string; status?: string; reason?: string }) =>
    api.patch<TenantDetail>(`/platform/tenants/${id}`, body),
  subscription: (id: number) => api.get<TenantSubscriptionDetail>(`/platform/tenants/${id}/subscription`),
  subscribe: (id: number, body: Record<string, unknown>) =>
    api.post<TenantSubscriptionDetail>(`/platform/tenants/${id}/subscription`, body),
  changeSubscription: (id: number, body: { status?: string; endDate?: string; reason?: string }) =>
    api.patch<TenantSubscriptionDetail>(`/platform/tenants/${id}/subscription`, body),
  allocate: (id: number, body: { kind: string; delta: number; reason: string }) =>
    api.post<LicensingOverview>(`/platform/tenants/${id}/allocations`, body),
  offers: () => api.get<Offer[]>("/platform/offers"),
  createOffer: (body: { code: string; name: string; description?: string }) =>
    api.post<Offer>("/platform/offers", body),
  updateOffer: (id: number, body: { name?: string; description?: string; isActive?: boolean }) =>
    api.patch<Offer>(`/platform/offers/${id}`, body),
  createVersion: (offerId: number, body: Partial<OfferVersion> & { publish?: boolean }) =>
    api.post<OfferVersion>(`/platform/offers/${offerId}/versions`, body),
  updateVersion: (id: number, body: Partial<OfferVersion> & { publish?: boolean }) =>
    api.patch<OfferVersion>(`/platform/versions/${id}`, body),
  requests: (status = "") => api.get<LicenseRequest[]>(`/platform/requests?status=${encodeURIComponent(status)}`),
  request: (id: number) => api.get<LicenseRequest>(`/platform/requests/${id}`),
  requestAction: (
    id: number,
    action: "decide" | "fulfil" | "comment",
    body: { status?: string; quantityGranted?: number | null; comment?: string },
  ) => api.post<LicenseRequest>(`/platform/requests/${id}/${action}`, body),
  audit: (tenant?: number) => api.get<PlatformAuditRow[]>(`/platform/audit${tenant ? `?tenant=${tenant}` : ""}`),
};
