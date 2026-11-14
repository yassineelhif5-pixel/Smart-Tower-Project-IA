// Types du pilotage méthodologique (1.5.0), alignés sur les réponses de /api/v1/methodology/.

export type MethodKind = "vcycle" | "scrum" | "hybrid" | "custom";
export type Feature = "phases" | "weekly" | "scrum" | "capacity" | "retro";
export interface Ref {
  id: number;
  name: string;
}

export interface MethodProject {
  id: string;
  code: string;
  name: string;
  client: string;
  kind: MethodKind;
  kindLabel: string;
  features: Feature[];
  activeSprint: SprintRow | null;
}

export interface BoardColumn {
  key: string;
  label: string;
  done: boolean;
}

export interface MethodSettings {
  productiveRatio: number;
  sprintWeeks: number;
  boardColumns: BoardColumn[];
  retroFrequency: string;
  reminderHours: number[];
  dailyTime: string;
  dailyMinutes: number;
  dailyInCalendar: boolean;
  weeklyPlanningDay: number;
  weeklyPlanningTime: string;
  timezone: string;
}

export interface MethodInfo {
  project: { id: string; code: string; name: string; start: string | null; end: string | null; pm: string | null };
  kind: MethodKind;
  kindLabel: string;
  features: Feature[];
  customFeatures: Feature[];
  settings: MethodSettings;
  history: { at: string; by: string; from: string; to: string }[];
  myScrumRole: "" | "po" | "sm" | "dev";
  can: { edit: boolean; plan: boolean; approve: boolean; capacity: boolean; prioritize: boolean };
  tenantPolicy: { reminderHours: number[]; allowAnonymous: boolean };
}

export interface Impact {
  from: string;
  to: string;
  enabled: Feature[];
  disabled: Feature[];
  warnings: string[];
  activeSprints: number;
  backlogItems: number;
  openWeeklyPlans: number;
  phases: number;
  openRetros: number;
}

export interface MemberCapacity {
  user: { id: number; name: string; team: string };
  allocationId: number;
  role: string;
  scrumRole: string;
  allocationPct: number;
  hoursPerDay: number;
  daysPerWeek: number;
  meetingHoursPerWeek: number;
  skills: string[];
  theoretical: number;
  unavailable: number;
  meetings: number;
  available: number;
  productive: number;
  planned: number;
  consumed: number;
  remaining: number;
  otherProjects: number;
  utilization: number;
  state: "ok" | "over" | "under";
  perDay: Record<string, number>;
  offDays: string[];
}

export interface Capacity {
  start: string;
  end: string;
  productiveRatio: number;
  members: MemberCapacity[];
  totals: Record<
    | "theoretical"
    | "unavailable"
    | "meetings"
    | "available"
    | "productive"
    | "planned"
    | "consumed"
    | "remaining"
    | "utilization",
    number
  >;
  overloaded: Ref[];
  underUsed: Ref[];
  weeks?: { week: string; productive: number; planned: number; consumed: number }[];
}

export interface Allocation {
  id: number;
  user: { id: number; name: string; team: string };
  projectRole: string;
  scrumRole: string;
  allocationPct: number;
  hoursPerDay: number;
  daysPerWeek: number;
  meetingHoursPerWeek: number;
  skills: string[];
  start: string | null;
  end: string | null;
  active: boolean;
}

export interface Availability {
  id: number;
  user: Ref | null;
  kind: string;
  kindLabel: string;
  start: string;
  end: string;
  hours: number | null;
  note: string;
  mine: boolean;
}

export interface ActionRow {
  id: string;
  title: string;
  status: string;
  priority: string;
  due: string | null;
  phase: string;
  owner: Ref | null;
  estimate: number;
  done: number;
  block: string;
  hours?: number;
  suggested?: boolean;
  planned?: boolean;
  plannedHours?: number;
  carriedOver?: boolean;
}

export interface WeeklyGoal {
  id: number;
  title: string;
  expectedResults: string;
  deliverables: string;
  phases: Ref[];
  owner: Ref | null;
  priority: string;
  risks: string;
  successCriteria: string;
  status: string;
  result: string;
  actions: ActionRow[];
}

export interface WeeklyPlan {
  id: number;
  weekStart: string;
  state: "draft" | "validated" | "closed";
  status: string;
  statusLabel: string;
  validatedBy: string | null;
  validatedAt: string | null;
  meeting: {
    agenda?: string;
    objectives?: string;
    progress?: string;
    problems?: string;
    decisions?: string;
    participants?: number[];
    actions?: string[];
    report?: string;
  };
  meetingEvent: number | null;
  review: {
    summary?: string;
    gaps?: { goal: string; action: string; status: string; cause: string; owner: string | null }[];
    causes?: string;
    risks?: string;
    correctiveActions?: string;
  };
  goals: WeeklyGoal[];
}

export interface Tracking {
  goals: {
    id: number;
    title: string;
    status: string;
    suggestedStatus: string;
    planned: number;
    done: number;
    doing: number;
    blocked: number;
    reported: number;
    plannedHours: number;
    consumedHours: number;
    rate: number;
  }[];
  totals: Record<string, number>;
  plannedHours: number;
  consumedHours: number;
  rate: number;
  deliverablesDone: number;
  status: string;
}

export interface WeekData {
  plan: WeeklyPlan;
  weekStart: string;
  weekEnd: string;
  unfinished: ActionRow[];
  carriedOver: ActionRow[];
  capacity: Capacity;
  proposals: ActionRow[];
  proposedHours: number;
  conflicts: { type: string; title: string; explanation: string }[];
  tracking: Tracking;
  history: { weekStart: string; status: string; statusLabel: string; state: string }[];
}

export interface Phase {
  id: number;
  order: number;
  name: string;
  start: string | null;
  end: string | null;
  forecastEnd: string | null;
  owner: Ref | null;
  status: string;
  statusLabel: string;
  progress: number;
  deliverables: { title: string; done: boolean }[];
  validationCriteria: string;
  risks: string;
  dependsOn: number[];
}

export interface BacklogItem {
  id: number;
  key: string;
  kind: string;
  title: string;
  description: string;
  userStory: string;
  acceptance: string;
  rank: number;
  priority: string;
  storyPoints: number | null;
  estimateHours: number | null;
  assignee: Ref | null;
  team: string;
  status: string;
  statusLabel: string;
  parent: { id: number; title: string } | null;
  dependencies: { id: number; title: string; status: string }[];
  attachments: { id: string; name: string }[];
  historyCount: number;
  selected?: boolean;
  suggested?: boolean;
}

export interface SprintGoal {
  objective: string;
  value: string;
  expectedResults: string;
  successCriteria: string;
  risks: string;
  owner: Ref | null;
  status: string;
  statusLabel: string;
  progress: number;
  items: { id: number; title: string }[];
}

export interface SprintRow {
  id: number;
  number: number;
  label: string;
  start: string;
  end: string;
  team: string;
  status: string;
  statusLabel: string;
  capacityHours: number | null;
  committedPoints: number | null;
  completedPoints: number | null;
  goal: SprintGoal | null;
  poValidated: { by: string; at: string } | null;
  teamValidated: { by: string; at: string } | null;
  events: { sprint?: number; planning?: number; review?: number; daily?: number[] };
}

export interface Velocity {
  sprints: { number: number; label: string; committed: number; completed: number }[];
  average: number | null;
}

export interface SprintMetrics {
  sprint: SprintRow;
  goal: SprintGoal | null;
  daysElapsed: number;
  daysRemaining: number;
  workingDays: number;
  pointsPlanned: number;
  pointsDone: number;
  pointsRemaining: number;
  tasksDoneRate: number;
  capacityInitial: number;
  capacityConsumed: number;
  remainingHours: number;
  velocity: Velocity;
  blocked: { id: number; title: string; reason: string }[];
  burndown: { date: string; remaining: number | null; ideal: number }[];
  burnup: { date: string; done: number | null; scope: number | null }[];
  byMember: { name: string; points: number; done: number; items: number }[];
}

export interface SprintEntry {
  id: number;
  item: BacklogItem;
  column: string;
  order: number;
  points: number | null;
  assignee: Ref | null;
  blocked: boolean;
  blockReason: string;
  remainingHours: number | null;
  doneAt: string | null;
  removed: boolean;
  history: { at: string; by: string; event: string; from?: string; to?: string }[];
}

export interface SprintDetail {
  sprint: SprintRow;
  columns: BoardColumn[];
  items: SprintEntry[];
  removed: SprintEntry[];
  metrics: SprintMetrics;
  myScrumRole: string;
}

export interface PlanningData {
  sprint: SprintRow;
  backlog: BacklogItem[];
  velocity: Velocity;
  capacity: Capacity;
  selectedPoints: number;
  selectedHours: number;
  dependencyIssues: { item: string; dependsOn: string; status: string }[];
  canPrioritize: boolean;
  myScrumRole: string;
}

export interface DailyEntry {
  id: number;
  date: string;
  user: Ref;
  progress: string;
  plan: string;
  impediment: string;
  impedimentStatus: string;
  resolution: string;
  resolutionOwner: Ref | null;
  resolutionDue: string | null;
  mine: boolean;
}

export interface DailyData {
  date: string;
  notes: string;
  entries: DailyEntry[];
  impediments: DailyEntry[];
  team: Ref[];
}

export interface ReviewData {
  sprint: SprintRow;
  increment: string;
  demos: string;
  feedback: string;
  decisions: string;
  backlogChanges: string;
  heldAt: string | null;
  report: string;
  done: BacklogItem[];
  notDone: BacklogItem[];
}

export interface RetroRow {
  id: number;
  title: string;
  trigger: string;
  triggerLabel: string;
  format: string;
  formatLabel: string;
  scheduledAt: string;
  durationMinutes: number;
  status: string;
  statusLabel: string;
  report: string;
  periodLabel: string;
  sprint: { id: number; label: string } | null;
  phase: Ref | null;
  facilitator: Ref | null;
  calendarEvent: number | null;
  forcedClose: boolean;
  closedAt: string | null;
  feedbackCount: number;
  improvementCount: number;
}

export interface Improvement {
  id: number;
  title: string;
  description: string;
  status: string;
  priority: string;
  owner: Ref | null;
  due: string | null;
  resultIndicator: string;
  targetSprint: { id: number; label: string } | null;
  targetPeriod: string;
  action: string | null;
  retro: { id: number; title: string };
  late: boolean;
}

export interface RetroDetail extends RetroRow {
  categories: string[];
  participants: { id: number; name: string; contributed: boolean }[];
  feedback: {
    id: number;
    category: string;
    text: string;
    votes: number;
    anonymous: boolean;
    author: Ref | null;
    mine: boolean;
  }[];
  improvements: Improvement[];
  previousOpen: Improvement[];
  improvementRate: number | null;
  isParticipant: boolean;
  allowAnonymous: boolean;
}

export interface ScrumDashboard {
  sprint: SprintRow | null;
  metrics: SprintMetrics | null;
  velocity: Velocity;
  backlog: { ready: number; new: number; readyPoints: number };
  ceremonies: { id: number; title: string; start: string }[];
  retros: RetroRow[];
  improvementRate: number | null;
}

export interface Assist {
  topic: string;
  engine: string;
  note: string;
  items: { title: string; reason: string; action?: string; actions?: string[]; items?: number[] }[];
}
