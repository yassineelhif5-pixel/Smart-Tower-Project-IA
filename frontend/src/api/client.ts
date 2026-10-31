// Couche d'accès unique au backend Django. Aucun autre fichier n'appelle fetch.
// Le navigateur ne parle qu'à /api (Django) : jamais directement à Supabase ou à PostgreSQL.
import type { ApiErrorBody } from "../types/api";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ApiErrorBody["details"];
  readonly traceId: string;

  constructor(status: number, body: Partial<ApiErrorBody>) {
    super(body.message ?? "La requête a échoué.");
    this.status = status;
    this.code = body.code ?? "ERROR";
    this.details = body.details ?? [];
    this.traceId = body.traceId ?? "";
  }

  /** Messages d'erreur rattachés à un champ de formulaire. */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const d of this.details) {
      if (typeof d === "object" && d.field) out[d.field] = out[d.field] ? `${out[d.field]} ${d.message}` : d.message;
    }
    return out;
  }
}

type Listener = (error: ApiError) => void;
const sessionListeners = new Set<Listener>();

/** Prévient l'application quand la session expire ou qu'un changement de mot de passe est exigé. */
export function onSessionProblem(listener: Listener): () => void {
  sessionListeners.add(listener);
  return () => sessionListeners.delete(listener);
}

function readCookie(name: string): string | null {
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=")[1]) : null;
}

let csrfReady: Promise<void> | null = null;
function ensureCsrf(): Promise<void> {
  if (readCookie("csrftoken")) return Promise.resolve();
  csrfReady ??= fetch("/api/auth/csrf", { credentials: "same-origin" }).then(() => undefined);
  return csrfReady;
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const unsafe = method !== "GET";
  if (unsafe) await ensureCsrf();
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(unsafe ? { "X-CSRFToken": readCookie("csrftoken") ?? "" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, { code: "NETWORK_ERROR", message: "Serveur injoignable. Vérifiez votre connexion." });
  }
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new ApiError(response.status, data as Partial<ApiErrorBody>);
    if (response.status === 401 || error.code === "PASSWORD_CHANGE_REQUIRED") {
      sessionListeners.forEach((listener) => listener(error));
    }
    throw error;
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),
};
