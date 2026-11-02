// Types du calendrier et de la collaboration (1.4.0). Noms de champs identiques aux réponses de l'API Django.

export type EventKind = "action" | "milestone" | "meeting" | "task";
export type EventStatus = "todo" | "planned" | "doing" | "review" | "blocked" | "done" | "cancelled";
export type Priority = "low" | "normal" | "high" | "critical";
export type AssignmentRole = "owner" | "contributor" | "reviewer";

export interface Person {
  id: number;
  username: string;
  name: string;
  team?: string;
}

export interface Assignment {
  id?: number;
  user: Person;
  role: AssignmentRole;
  roleLabel?: string;
  estimatedWorkload: number | null;
  actualWorkload: number | null;
  status?: string;
}

export interface CalendarEvent {
  id: number;
  kind: EventKind;
  title: string;
  description: string;
  phase: string;
  project: { id: string; code: string; name: string } | null;
  action: { id: string; title: string } | null;
  start: string;
  end: string;
  allDay: boolean;
  timezone: string;
  startDate: string;
  endDate: string;
  status: EventStatus;
  statusLabel: string;
  priority: Priority;
  priorityLabel: string;
  progress: number;
  late: boolean;
  assignments: Assignment[];
  dependencies: { id: number; predecessor: number; type: string }[];
  canEdit: boolean;
  canUpdateProgress: boolean;
  canDelete: boolean;
  createdBy: string | null;
  completedAt: string | null;
}

export interface EventPage {
  count: number;
  limit: number;
  offset: number;
  results: CalendarEvent[];
}

/** Corps envoyé pour créer ou modifier un événement. Dates : AAAA-MM-JJ (journée) ou AAAA-MM-JJTHH:MM (local). */
export interface EventInput {
  project?: string | null;
  action?: string | null;
  kind?: EventKind;
  title?: string;
  description?: string;
  phase?: string;
  start?: string;
  end?: string;
  allDay?: boolean;
  timezone?: string;
  status?: EventStatus;
  priority?: Priority;
  progress?: number;
  actualWorkload?: number;
  assignments?: { user: number; role: AssignmentRole; estimatedWorkload?: number | null }[];
  dependencies?: { predecessor: number; type: string }[];
  confirm?: boolean;
}

export interface Conflict {
  type: "double_booking" | "overload" | "unassigned" | "dependency" | "deadline" | "late";
  severity: "warning" | "critical";
  title: string;
  explanation: string;
  events: number[];
  users: number[];
  suggestion: {
    event: number;
    action: "move" | "extend" | "assign";
    start?: string;
    end?: string;
    allDay?: boolean;
    user?: number;
  } | null;
}

export interface WorkloadRow {
  key: string;
  label: string;
  user?: Person;
  members?: number;
  team?: string;
  capacity: number;
  load: Record<string, number>;
  total: number;
  over: string[];
}

export interface Workload {
  group: "user" | "team";
  days: string[];
  rows: WorkloadRow[];
}

export interface LoadSummary {
  key: string;
  label: string;
  total: number;
  overDays: number;
  capacity: number;
}

export interface CalendarDashboardData {
  period: { start: string; end: string };
  planned: number;
  done: number;
  inProgress: number;
  blocked: number;
  late: number;
  upcoming: number;
  milestones: { id: number; title: string; date: string; project: string | null; status: string }[];
  progressRate: number;
  onTimeRate: number | null;
  workloadByUser: LoadSummary[];
  workloadByTeam: LoadSummary[];
  delaysByProject: {
    project: { id: string; code: string; name: string };
    late: number;
    total: number;
    avgDelayDays: number;
  }[];
}

export interface PortfolioRow {
  id: string;
  code: string;
  name: string;
  client: string;
  pm: string | null;
  start: string | null;
  end: string | null;
  forecastEnd: string | null;
  progress: number;
  events: number;
  late: number;
  milestones: { title: string; date: string; status: string }[];
  health: "ok" | "late";
}

export interface CalendarColors {
  status: Record<EventStatus, string>;
  priority: Record<Priority, string>;
  colorBy: "status" | "priority";
  canEdit: boolean;
}

export interface Reminder {
  id: number;
  remindAt: string;
  channel: "inapp" | "email" | "teams";
  kind: string;
  status: string;
  error?: string;
}

export interface ProjectRef {
  id: string;
  code: string;
  name: string;
  client: { code: string; name: string };
}

// --------------------------------------------------------------------------- collaboration
export type Destination = "internal" | "teams" | "both";
export type TeamsKind = "none" | "oneOnOne" | "group" | "channel";

export interface Discussion {
  id: number;
  title: string;
  project: { id: string; code: string; name: string };
  action: { id: string; title: string } | null;
  destination: Destination;
  destinationLabel: string;
  teamsKind: TeamsKind;
  teamsKindLabel: string;
  teamsUrl: string;
  status: "active" | "archived" | "error";
  lastError: string;
  createdBy: Person | null;
  createdAt: string;
  lastMessageAt: string | null;
  lastSyncedAt: string | null;
  private: boolean;
  participants: (Person & { role: string })[];
  canPost: boolean;
  messageCount?: number;
  failedCount?: number;
}

export interface DiscussionInput {
  project: string;
  action?: string | null;
  title: string;
  destination: Destination;
  teamsKind?: TeamsKind;
  participants: number[];
  teamId?: string;
  channelId?: string;
  message?: string;
}

export interface Message {
  id: number;
  kind: "message" | "system";
  author: Person | null;
  externalAuthor: string;
  body: string;
  deleted: boolean;
  parent: number | null;
  origin: "pct" | "teams";
  publicationStatus: "internal" | "pending" | "published" | "failed";
  publicationError: string;
  mentions: Person[];
  attachments: { id: string; name: string; ext: string }[];
  createdAt: string;
  editedAt: string | null;
  deletedAt: string | null;
  historyCount: number;
  mine: boolean;
  canEdit: boolean;
  canRetry: boolean;
}

export interface TeamsStatus {
  configured: boolean;
  channels: boolean;
  channelCreation: boolean;
  linked: boolean;
  account: { name: string; upn: string } | null;
  needsReconsent: boolean;
  missingScopes: string[];
  tokenExpiresAt: string | null;
  webhooks: boolean;
}

export interface TeamsConnectorSettings {
  directoryId: string;
  clientId: string;
  enabled: boolean;
  allowChannels: boolean;
  allowChannelCreation: boolean;
  allowEditInTeams: boolean;
  status: "not_configured" | "configured" | "ok" | "error";
  lastCheckAt: string | null;
  lastError: string;
  secretExpiresOn: string | null;
  secretSet: boolean;
  secretHint: string;
  scopes: string[];
  redirectUri: string;
  webhookUrl: string;
  linkedUsers: number;
}

export interface NotificationPreferences {
  channels: { kind: string; label: string }[];
  events: { event: string; label: string; channels: Record<string, { allowed: boolean; enabled: boolean }> }[];
}
