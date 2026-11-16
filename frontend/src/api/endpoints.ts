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
  OfferChoice,
  VoucherBatch,
  VoucherIssueResult,
  AdminProject,
  ProjectClientChoice,
  PlatformTenantRights,
  SaaSReport,
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
  Onboarding,
  NotificationSettings,
  RolesResponse,
  SSOSettings,
  SSOAccessQueue,
  AccessChangeQueue,
  TimeEntries,
  ConnectorCatalogView,
  TenantDomainRow,
  Secret,
  UserInput,
  TimeSettings,
  TimeDelegations,
  TimeDelegationRow,
  Role,
} from "../types/api";
import { api } from "./client";

export const authApi = {
  me: () => api.get<Me>("/auth/me"),
  login: (username: string, password: string) => api.post<Me>("/auth/login", { username, password }),
  logout: () => api.post<void>("/auth/logout"),
  changePassword: (current_password: string, new_password: string) =>
    api.post<Me>("/auth/change-password", { current_password, new_password }),
  forgotPassword: (identifier: string) => api.post<{ detail: string }>("/auth/password/forgot", { identifier }),
  resetPassword: (uid: string, token: string, new_password: string) =>
    api.post<{ detail: string; confirmed?: boolean; username?: string }>("/auth/password/reset", { uid, token, new_password }),
};

export type OnboardingResponse = { onboarding: Onboarding; me: Me; result?: { activated?: boolean; requested?: boolean } };
export const signupApi = {
  providers: () => api.get<{ google: boolean; signup: boolean }>("/auth/providers"),
  signup: (body: { firstName: string; lastName: string; email: string; password: string; acceptTerms: boolean; invite?: string }) =>
    api.post<{ detail: string; email: string; loggedIn?: boolean }>("/auth/signup", body),
  invitation: (token: string) =>
    api.get<{ valid: boolean; email?: string; tenant?: string | null; invitedBy?: string; message?: string }>(`/auth/invitation?token=${encodeURIComponent(token)}`),
  acceptInvite: (token: string) => api.post<OnboardingResponse>("/auth/invitation/accept", { token }),
  resend: (email: string) => api.post<{ detail: string }>("/auth/signup/resend", { email }),
  state: () => api.get<OnboardingResponse>("/auth/onboarding"),
  profile: (body: Record<string, string>) => api.post<OnboardingResponse>("/auth/onboarding/profile", body),
  demo: () => api.post<OnboardingResponse>("/auth/onboarding/demo"),
  join: (code: string, message: string) => api.post<OnboardingResponse>("/auth/onboarding/join", { code, message }),
  cancelJoin: (id: number) => api.post<OnboardingResponse>(`/auth/onboarding/join/${id}/cancel`),
  activate: (body: { mode: "voucher"; code: string } | { mode: "request"; versionId: number; justification: string }) =>
    api.post<OnboardingResponse>("/auth/onboarding/activate", body),
  enter: () => api.post<OnboardingResponse>("/auth/onboarding/enter"),
};

export const timeApi = {
  entries: () => api.get<TimeEntries>("/timesheets"),
  create: (body: { project: string; action?: string; workDate: string; amount: number }) => api.post("/timesheets", body),
  decide: (id: number, decision: "approved" | "rejected", comment = "") => api.post(`/timesheets/${id}/decision`, { decision, comment }),
  delegations: () => api.get<TimeDelegations>("/timesheets/delegations"),
  createDelegation: (body: { delegator?: number; delegate: number; startDate: string; endDate: string; reason?: string }) =>
    api.post<TimeDelegationRow>("/timesheets/delegations", body),
  deleteDelegation: (id: number) => api.delete<void>(`/timesheets/delegations/${id}`),
};

export const adminApi = {
  users: () => api.get<AdminUser[]>("/admin/users"),
  createUser: (input: UserInput) => api.post<CreatedUser>("/admin/users", input),
  updateUser: (id: number, input: UserInput) => api.patch<AdminUser>(`/admin/users/${id}`, input),
  resetPassword: (id: number) => api.post<{ temporaryPassword: string }>(`/admin/users/${id}/reset-password`),
  access: (id: number) => api.get<Access>(`/admin/users/${id}/access`),
  setAccess: (id: number, access: Access) => api.put<Access>(`/admin/users/${id}/access`, access),
  projects: () => api.get<AdminProject[]>("/admin/projects"),
  companyProfile: () => api.get<TenantRow>("/admin/company"),
  updateCompanyProfile: (body: Partial<Pick<TenantRow, "industry" | "website" | "phone" | "address" | "city" | "country" | "contactName" | "contactEmail" | "contactPhone" | "description">>) =>
    api.patch<TenantRow>("/admin/company", body),
  saasReport: () => api.get<SaaSReport>("/admin/saas-report"),
  projectClients: () => api.get<ProjectClientChoice[]>("/admin/project-clients"),
  createClient: (body: { name: string; sector?: string; city?: string }) =>
    api.post<ProjectClientChoice>("/admin/project-clients", body),
  createProject: (body: { code: string; name: string; client: string; method?: string; description?: string; startDate?: string; endDate?: string; pm?: number | null; tl?: number | null; projectType?: string; baseProject?: string | null; baseVersion?: string }) =>
    api.post<AdminProject>("/admin/projects", body),
  updateProject: (id: string, body: { name?: string; client?: string; method?: string; description?: string; startDate?: string; endDate?: string; pm?: number | null; tl?: number | null; projectType?: string; baseProject?: string | null; baseVersion?: string }) =>
    api.patch<AdminProject>(`/admin/projects/${encodeURIComponent(id)}`, body),
  roles: () => api.get<RolesResponse>("/admin/roles"),
  createRole: (body: { label: string; question?: string; internal: boolean; money: boolean; margin: boolean }) =>
    api.post<Role>("/admin/roles", body),
  setPermissions: (code: string, permissions: Record<string, Flags>) =>
    api.put<{ code: string; permissions: Record<string, Flags> }>(`/admin/roles/${code}/permissions`, { permissions }),
  database: () => api.get<DatabaseStatus>("/admin/database"),
  testDatabase: () => api.post<DatabaseStatus>("/admin/database/test"),
  sso: () => api.get<SSOSettings>("/admin/sso"),
  saveSso: (body: { issuer: string; clientId: string; clientSecret?: string; defaultRole: string; enabled: boolean }) =>
    api.put<SSOSettings>("/admin/sso", body),
  ssoRequests: () => api.get<SSOAccessQueue>("/admin/sso/requests"),
  timeSettings: () => api.get<TimeSettings>("/admin/time-settings"),
  saveTimeSettings: (body: { unit: "hour" | "day"; hoursPerDay: number; clientVisible: boolean; approval: string; clientApproval?: boolean }) =>
    api.put<TimeSettings>("/admin/time-settings", body),
  decideSsoRequest: (id: number, action: "approve" | "reject", role?: string) =>
    api.post<{ id: number; email: string; status: string }>(`/admin/sso/requests/${id}`, { action, ...(role ? { role } : {}) }),
  accessChangeRequests: () => api.get<AccessChangeQueue>("/admin/access-requests"),
  requestAccessChange: (body: { user: number; role: string; reason: string }) => api.post<{ id: number; status: string }>("/admin/access-requests", body),
  decideAccessChange: (id: number, action: "approve" | "reject", role?: string) =>
    api.post<{ id: number; status: string }>(`/admin/access-requests/${id}`, { action, ...(role ? { role } : {}) }),
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
    targetVersion?: number | null;
    justification: string;
  }) => api.post<LicenseRequest>("/licensing/requests", body),
  requestAction: (id: number, action: "submit" | "cancel" | "comment", comment = "") =>
    api.post<LicenseRequest>(`/licensing/requests/${id}/${action}`, { comment }),
  offers: () => api.get<OfferChoice[]>("/licensing/offers"),
  redeemVoucher: (code: string) => api.post<{ tenant: string; offer: string; version: number; status: string; endDate: string | null }>("/licensing/vouchers/redeem", { code }),
};

/** Espace Pilote (Super Admin Global). */
export const platformApi = {
  saasReport: () => api.get<SaaSReport>("/platform/saas-report"),
  dashboard: () => api.get<PilotDashboard>("/platform/dashboard"),
  tenantRights: (id: number) => api.get<PlatformTenantRights>(`/platform/tenants/${id}/access-rights`),
  setTenantRights: (id: number, roles: Record<string, { projectCreate: boolean; capabilities: string[] }>) =>
    api.put<PlatformTenantRights>(`/platform/tenants/${id}/access-rights`, { roles }),
  domains: () => api.get<TenantDomainRow[]>("/platform/domains"),
  connectorAssignments: () => api.get<ConnectorCatalogView>("/platform/connectors"),
  setClientConnector: (tenant: number, client: string, connector: string, enabled: boolean) =>
    api.post<{ client: string; connector: string; enabled: boolean; projects: number }>("/platform/connectors", { tenant, client, connector, enabled }),
  setProjectConnector: (project: string, connector: string, enabled: boolean) =>
    api.post<{ project: string; connector: string; enabled: boolean }>("/platform/connectors", { project, connector, enabled }),
  maintenance: () => api.get<MaintenanceDashboard>("/platform/maintenance"),
  setMaintenance: (tenant: number, body: { enabled: boolean; plan?: string; startsAt?: string | null; endsAt?: string | null }) =>
    api.post(`/platform/maintenance/${tenant}`, body),
  supportUsers: () => api.get<{ id: number; username: string; email: string; isActive: boolean }[]>("/platform/support/users"),
  createSupportUser: (body: { username: string; email?: string }) =>
    api.post<{ id: number; username: string; email: string; isActive: boolean; temporaryPassword: string }>("/platform/support/users", body),
  assignDomain: (body: { domain: string; tenant: number; enabled: boolean; client?: string | null }) =>
    api.post<TenantDomainRow>("/platform/domains", body),
  updateDomain: (id: number, body: { tenant?: number; enabled?: boolean; client?: string | null }) =>
    api.patch<TenantDomainRow>(`/platform/domains/${id}`, body),
  tenants: (q = "", status = "") =>
    api.get<TenantRow[]>(`/platform/tenants?q=${encodeURIComponent(q)}&status=${encodeURIComponent(status)}`),
  tenant: (id: number) => api.get<TenantDetail>(`/platform/tenants/${id}`),
  createTenant: (body: Record<string, unknown>) => api.post<CreatedTenant>("/platform/tenants", body),
  updateTenant: (id: number, body: { name?: string; status?: string; reason?: string; industry?: string; website?: string; phone?: string; address?: string; city?: string; country?: string; contactName?: string; contactEmail?: string; contactPhone?: string; description?: string }) =>
    api.patch<TenantDetail>(`/platform/tenants/${id}`, body),
  subscription: (id: number) => api.get<TenantSubscriptionDetail>(`/platform/tenants/${id}/subscription`),
  subscribe: (id: number, body: Record<string, unknown>) =>
    api.post<TenantSubscriptionDetail>(`/platform/tenants/${id}/subscription`, body),
  changeSubscription: (id: number, body: { status?: string; endDate?: string; reason?: string }) =>
    api.patch<TenantSubscriptionDetail>(`/platform/tenants/${id}/subscription`, body),
  allocate: (id: number, body: { kind: string; delta: number; reason: string }) =>
    api.post<LicensingOverview>(`/platform/tenants/${id}/allocations`, body),
  offers: () => api.get<Offer[]>("/platform/offers"),
  voucherBatches: () => api.get<VoucherBatch[]>("/platform/vouchers"),
  createVouchers: (body: { version: number; targetTenant: number; quantity: number; expiresAt: string | null; features?: string[]; clientEmail?: string }) =>
    api.post<VoucherIssueResult>("/platform/vouchers", body),
  revokeVoucherBatch: (batchId: string) => api.post<{ revoked: number }>(`/platform/vouchers/${batchId}/revoke`),
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

export interface MaintenanceTicket {
  id: number; tenant: number; tenantName: string; requester: string; email: string; title: string; description: string;
  category: string; status: "new" | "triaged" | "in_progress" | "resolved" | "closed";
  assignedTo: string | null; createdAt: string; updatedAt: string;
  aiStatus: "pending" | "ready" | "unavailable" | "error"; aiAnalysis: string; aiReply: string;
}

export interface MaintenanceDashboard {
  entitlements: { tenant: number; tenantName: string; enabled: boolean; plan: string; startsAt: string | null;
    endsAt: string | null; assignedBy: string | null; updatedAt: string; requestCount: number }[];
  requests: MaintenanceTicket[];
  statistics: { total: number; byStatus: Record<string, number> };
}

export const supportApi = {
  tenants: () => api.get<{ id: number; name: string; status: string }[]>("/platform/support/tenants"),
  clientRequests: () => api.get<{ enabled: boolean; plan: string; endsAt: string | null; requests: MaintenanceTicket[] }>("/maintenance/requests"),
  createRequest: (body: { title: string; description: string; category: string }) => api.post<MaintenanceTicket>("/maintenance/requests", body),
  queue: () => api.get<{ requests: MaintenanceTicket[]; staff: { id: number; username: string }[] }>("/platform/support/requests"),
  update: (id: number, body: { status?: string; assignedTo?: number | null }) => api.patch<MaintenanceTicket>(`/platform/support/requests/${id}`, body),
};

export const assistantApi = {
  ask: (question: string) => api.post<{ answer: string }>("/assistant/chat", { question }),
};
