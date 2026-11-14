import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LoginPage } from "./LoginPage";

afterEach(() => vi.restoreAllMocks());

describe("LoginPage", () => {
  it("affiche le message d'erreur du backend", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((url) =>
      Promise.resolve(
        String(url).endsWith("/csrf")
          ? new Response(null, { status: 204 })
          : new Response(
              JSON.stringify({
                code: "INVALID_CREDENTIALS",
                message: "Identifiant ou mot de passe incorrect.",
                details: [],
                traceId: "a",
              }),
              { status: 401 },
            ),
      ),
    );
    const onLogged = vi.fn();
    render(<LoginPage onLogged={onLogged} />);
    fireEvent.change(screen.getByLabelText("Identifiant"), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText("Mot de passe"), { target: { value: "faux" } });
    fireEvent.click(screen.getByRole("button", { name: "Se connecter" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Identifiant ou mot de passe incorrect."));
    expect(onLogged).not.toHaveBeenCalled();
  });

  it("transmet le profil après une connexion réussie", async () => {
    const me = {
      id: 1,
      username: "admin",
      name: "Administrateur",
      email: "",
      title: "",
      role: { code: "admin", label: "Administrateur" },
      isAdmin: true,
      mustChangePassword: true,
      permissions: {},
    };
    vi.spyOn(globalThis, "fetch").mockImplementation((url) =>
      Promise.resolve(
        String(url).endsWith("/csrf")
          ? new Response(null, { status: 204 })
          : new Response(JSON.stringify(me), { status: 200 }),
      ),
    );
    const onLogged = vi.fn();
    render(<LoginPage onLogged={onLogged} />);
    fireEvent.change(screen.getByLabelText("Identifiant"), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText("Mot de passe"), { target: { value: "admin" } });
    fireEvent.click(screen.getByRole("button", { name: "Se connecter" }));
    await waitFor(() => expect(onLogged).toHaveBeenCalledWith(me));
  });
});
