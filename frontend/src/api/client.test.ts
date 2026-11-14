import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, onSessionProblem, request } from "./client";

const json = (status: number, body: unknown) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

afterEach(() => {
  vi.restoreAllMocks();
  document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

describe("client API", () => {
  it("n'appelle que /api/v1 et envoie le jeton CSRF sur les écritures", async () => {
    document.cookie = "csrftoken=abc123";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() => json(200, { ok: true }));
    await request("POST", "/admin/users", { username: "x" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/users");
    expect((init as RequestInit).credentials).toBe("same-origin");
    expect(((init as RequestInit).headers as Record<string, string>)["X-CSRFToken"]).toBe("abc123");
  });

  it("transforme l'erreur uniforme du backend en ApiError avec erreurs par champ", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      json(400, {
        code: "VALIDATION_ERROR",
        message: "Certaines valeurs sont invalides.",
        details: [{ field: "role", message: "Obligatoire." }],
        traceId: "7f3a9c21",
      }),
    );
    const error = (await request("GET", "/admin/users").catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("VALIDATION_ERROR");
    expect(error.traceId).toBe("7f3a9c21");
    expect(error.fieldErrors()).toEqual({ role: "Obligatoire." });
  });

  it("prévient l'application quand un changement de mot de passe est exigé", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      json(403, { code: "PASSWORD_CHANGE_REQUIRED", message: "…", details: [], traceId: "1" }),
    );
    const listener = vi.fn();
    const off = onSessionProblem(listener);
    await request("GET", "/projects").catch(() => undefined);
    off();
    expect(listener).toHaveBeenCalledOnce();
  });

  it("signale un serveur injoignable sans planter", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => Promise.reject(new TypeError("Failed to fetch")));
    const error = (await request("GET", "/auth/me").catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe("NETWORK_ERROR");
  });
});
