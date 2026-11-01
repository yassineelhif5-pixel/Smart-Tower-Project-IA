// Types des réponses de l'API Django. Les noms de champs suivent exactement les serializers du backend.

export interface ApiErrorBody {
  code: string;
  message: string;
  details: { field: string | null; message: string }[] | string[];
  traceId: string;
}

export type Flags = [boolean, boolean, boolean, boolean, boolean];

export interface Me {
  id: number;
  username: string;
  name: string;
  email: string;
  title: string;
  role: { code: string; label: string } | null;
  isAdmin: boolean;
  isPlatformAdmin: boolean;
  tenant: { slug: string; name: string; status: string } | null;
  mustChangePassword: boolean;
  permissions: Record<string, Flags>;
  capabilities: string[];
}

export interface AdminUser {
  id: number;
  username: string;
  firstName: string;
  lastName: string;
  email: string;
  role: string;
  title: string;
  team: string;
  client: string | null;
  isActive: boolean;
  mustChangePassword: boolean;
  lastLogin: string | null;
  projectCount: number;
}

export type UserInput = Partial<Omit<AdminUser, "id" | "mustChangePassword" | "lastLogin" | "projectCount">> & {
  password?: string;
};

export interface CreatedUser extends AdminUser {
  temporaryPassword: string;
}

export interface Role {
  code: string;
  label: string;
  internal: boolean;
  money: boolean;
  margin: boolean;
  userCount: number;
  permissions: Record<string, Flags>;
}

export interface RolesResponse {
  modules: { code: string; label: string }[];
  verbs: { code: string; label: string }[];
  roles: Role[];
}

export interface Access {
  projects: { project: string; canEdit: boolean }[];
  actions: { action: string; canEdit: boolean }[];
}

export interface AdminProject {
  id: string;
  code: string;
  name: string;
  client: { code: string; name: string };
  actions: { id: string; title: string; status: string }[];
}

export interface DatabaseStatus {
  provider: string;
  engine: string;
  configuredBy: string;
  location: "local" | "distant";
  connected: boolean;
  serverVersion?: string;
  latencyMs?: number;
  ssl?: boolean | null;
  migrations?: { applied: number; pending: string[] };
  error?: string;
}

export interface Endpoint {
  path: string;
  methods: string[];
  access: "admin" | "public" | "connecté";
}

export interface ApiStats {
  hours: number;
  requests: number;
  avgMs: number;
  clientErrors: number;
  serverErrors: number;
  top: { method: string; path: string; requests: number; avgMs: number; errors: number }[];
}

export interface ApiLog {
  at: string;
  method: string;
  path: string;
  status: number;
  durationMs: number;
  user: string | null;
  token: string | null;
}

export interface ApiToken {
  id: number;
  name: string;
  prefix: string;
  user: { id: number; username: string };
  readOnly: boolean;
  createdAt: string;
  expiresAt: string | null;
  lastUsedAt: string | null;
  revokedAt: string | null;
  active: boolean;
}

export interface Secret {
  key: string;
  label: string;
  used_by: string;
  isSet: boolean;
  hint: string | null;
  updatedAt: string | null;
}

export interface Channel {
  kind: "inapp" | "email" | "teams" | "slack";
  label: string;
  enabled: boolean;
  settings: Record<string, string | number>;
  secret: { key: string; isSet: boolean } | null;
}

export interface NotificationSettings {
  channels: Channel[];
  events: { code: string; label: string }[];
  rules: Record<string, Record<string, boolean>>;
}

export interface AuditRow {
  at: string;
  actor: string | null;
  entity: string;
  event: string;
  old: string;
  new: string;
  trace: string;
}

// --- Multi-tenant, offres et licences ---------------------------------------------------------

export interface TenantRow {
  id: number;
  slug: string;
  name: string;
  status: "active" | "suspended" | "disabled" | "archived";
  statusLabel: string;
  statusReason: string;
  statusChangedAt: string | null;
  language: string;
  createdAt: string;
  users: number | null;
  activeUsers: number | null;
}

export interface TenantDetail extends TenantRow {
  userList: {
    id: number;
    username: string;
    name: string;
    role: string | null;
    isActive: boolean;
    lastLogin: string | null;
  }[];
}

export interface CreatedTenant extends TenantRow {
  admin: { id: number; username: string };
  temporaryPassword: string;
}

export interface OfferVersion {
  id: number;
  number: number;
  isPublished: boolean;
  inUse: boolean;
  price: string | null;
  currency: string;
  billingPeriod: "month" | "year" | "once";
  durationDays: number | null;
  trialDays: number;
  licenseModel: "named" | "concurrent" | "mixed";
  maxUsers: number | null;
  namedLicenses: number;
  concurrentLicenses: number;
  maxSessionsPerUser: number | null;
  features: string[];
  limits: Record<string, unknown>;
  conditions: string;
  createdAt: string;
}

export interface Offer {
  id: number;
  code: string;
  name: string;
  description: string;
  isActive: boolean;
  position: number;
  currentVersion: OfferVersion | null;
  versions: OfferVersion[];
}

export interface Subscription {
  id: number;
  status: "trial" | "active" | "suspended" | "expired" | "cancelled";
  statusLabel: string;
  startDate: string;
  endDate: string | null;
  trialEnd: string | null;
  offer: { id: number; code: string; name: string };
  version: OfferVersion;
  contract: { reference: string; terms: string } | null;
}

export interface StockLine {
  total: number;
  used: number;
  available: number;
}

export interface LicensingOverview {
  enforced: boolean;
  subscription: Subscription | null;
  stock: { named: StockLine; concurrent: StockLine };
  users: { active: number; max: number | null };
  activeSessions: number;
  pendingRequests: number;
}

export interface TenantSubscriptionDetail extends LicensingOverview {
  history: Subscription[];
  allocations: { at: string; kind: string; delta: number; reason: string; request: number | null; by: string | null }[];
}

export interface LicenseRow {
  id: number;
  number: string;
  kind: "named" | "concurrent";
  status: string;
  statusLabel: string;
  holder: { id: number; username: string; since: string } | null;
  session: { user: string; since: string } | null;
}

export interface LicenseList {
  licenses: LicenseRow[];
  unlicensedUsers: { id: number; username: string; name: string }[];
}

export interface SessionRow {
  id: number;
  user: { id: number; username: string };
  license: string | null;
  mode: string;
  startedAt: string;
  lastSeenAt: string;
  expiresAt: string;
}

export type RequestStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "UNDER_REVIEW"
  | "ADDITIONAL_INFORMATION_REQUIRED"
  | "APPROVED"
  | "PARTIALLY_APPROVED"
  | "REJECTED"
  | "CANCELLED"
  | "FULFILLED";

export interface LicenseRequest {
  id: number;
  tenant: { id: number; name: string };
  kind: "named" | "concurrent" | "quota" | "offer" | "option";
  kindLabel: string;
  quantity: number | null;
  quantityGranted: number | null;
  targetOffer: { id: number; name: string } | null;
  justification: string;
  status: RequestStatus;
  createdAt: string;
  submittedAt: string | null;
  decidedAt: string | null;
  fulfilledAt: string | null;
  createdBy: string | null;
  events?: { at: string; actor: string | null; from: string; to: string; comment: string }[];
}

export interface PilotDashboard {
  tenants: {
    total: number;
    active: number;
    suspended: number;
    disabled: number;
    archived: number;
    trial: number;
    withoutSubscription: number;
  };
  licenses: {
    sold: number;
    allocated: number;
    available: number;
    used: number;
    expired: number;
    byKind: Record<"named" | "concurrent", { allocated: number; used: number }>;
  };
  subscriptions: { active: number; trial: number; suspended: number; expired: number };
  pendingRequests: number;
  byOffer: { offer: string; tenants: number }[];
  recentOperations: {
    at: string;
    actor: string | null;
    tenant: string | null;
    entity: string;
    event: string;
    result: string;
  }[];
}

export interface PlatformAuditRow {
  at: string;
  actor: string | null;
  tenant: string | null;
  entity: string;
  event: string;
  old: string;
  new: string;
  trace: string;
}

export interface CapabilityMatrix {
  catalog: { code: string; domain: string; action: string; delegable: boolean }[];
  roles: { code: string; label: string; locked: boolean; capabilities: string[] }[];
}

export interface UserCapabilities {
  overrides: { code: string; granted: boolean }[];
  effective: string[];
}

export interface MyAccess {
  user: { username: string; name: string; email: string; title: string };
  company: { name: string; status: string } | null;
  role: { code: string | null; label: string | null };
  permissions: Record<string, Flags>;
  capabilities: string[];
  license: { mode: string; number: string | null };
  access: { status: string; validUntil: string | null; subscriptionStatus: string | null };
  session: { startedAt: string; expiresAt: string } | null;
}
