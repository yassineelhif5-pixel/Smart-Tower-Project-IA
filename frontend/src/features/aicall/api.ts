// Appels IA : types et accès à l'API /projects/<id>/ai-calls.
import { api } from "../../api/client";

export type Mate = {
  code: string; name: string; role: string; avatar: string; color: string; mission: string;
  enabled: boolean; canLead: boolean; docType: string | null; docLabel: string;
};
export type Turn = { id: string; at: string; speaker: string; name: string; text: string; kind: "speech" | "system" | "file" };
export type CardOption = { id: string; label: string; hint: string; recommended: boolean };
export type Card = {
  id: string; by: string; type: "choice" | "validation" | "question" | "invite"; question: string; options: CardOption[];
  section: string | null; meta: Record<string, unknown>; status: "open" | "answered"; answer: string | null; answeredBy: string | null;
};
export type Section = { key: string; title: string; question: string | null; content: string; status: "empty" | "draft" | "skipped" | "done"; author: string; updatedAt: string | null };
export type CallSummary = {
  id: string; status: "live" | "closed"; mode: "audio" | "video"; objective: string; docTitle: string; lead: string; leadName: string;
  startedAt: string; endedAt: string | null; duration: number; organizer: string; turns: number; stopped: boolean;
  document: { id: string; name: string; version: number } | null;
};
export type Call = CallSummary & {
  assistants: Mate[]; participants: { id: number; name: string; role: string }[]; docType: string; docLabel: string;
  sections: Section[]; turns: Turn[]; cards: Card[]; files: { id: string; name: string; words: number }[];
  llm: boolean; promptVersion: string; projectId: string; projectCode: string; cursor: number | null;
};
export type Lobby = { assistants: Mate[]; calls: CallSummary[]; hasSpecs: boolean; isPm: boolean; speechProvider: string };

const base = (projectId: string) => `/projects/${encodeURIComponent(projectId)}/ai-calls`;

export const aiCalls = {
  lobby: (projectId: string) => api.get<Lobby>(base(projectId)),
  start: (projectId: string, body: { lead: string; assistants: string[]; mode: string; objective: string; docTitle: string }) =>
    api.post<Call>(base(projectId), body),
  get: (projectId: string, id: string) => api.get<Call>(`${base(projectId)}/${encodeURIComponent(id)}`),
  act: (projectId: string, id: string, body: Record<string, unknown>) => api.post<Call>(`${base(projectId)}/${encodeURIComponent(id)}`, body),
};
