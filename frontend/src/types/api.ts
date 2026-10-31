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
  mustChangePassword: boolean;
  permissions: Record<string, Flags>;
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
