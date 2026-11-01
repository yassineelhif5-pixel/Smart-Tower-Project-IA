import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { routesFor } from "./App";
import { ToastProvider } from "./components/ui";
import { LicensesTab } from "./features/licensing/LicensesTab";
import type { Me } from "./types/api";

const me = (over: Partial<Me>): Me => ({
  id: 1,
  username: "u",
  name: "U",
  email: "",
  title: "",
  role: { code: "dev", label: "Développeur" },
  isAdmin: false,
  isPlatformAdmin: false,
  tenant: { slug: "acme", name: "Acme", status: "active" },
  mustChangePassword: false,
  permissions: {},
  capabilities: [],
  ...over,
});

const json = (body: unknown) =>
  Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));

afterEach(() => vi.restoreAllMocks());

describe("écrans selon le profil", () => {
  it("le Pilote a sa console, jamais la configuration d'une entreprise", () => {
    expect(routesFor(me({ isPlatformAdmin: true, tenant: null }))).toEqual(["pilote", "acces"]);
  });
  it("l'administrateur du tenant a la configuration de son entreprise", () => {
    expect(routesFor(me({ isAdmin: true }))).toEqual(["configuration", "acces"]);
  });
  it("un responsable de licences délégué voit l'écran Licences", () => {
    expect(routesFor(me({ capabilities: ["licenses.view"] }))).toEqual(["licences", "acces"]);
  });
  it("un utilisateur standard ne voit que son accès", () => {
    expect(routesFor(me({}))).toEqual(["acces"]);
  });
});

describe("écran Licences", () => {
  it("n'affiche que les blocs autorisés par les droits", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((url) => (String(url).endsWith("/licensing/requests") ? json([]) : json({})));
    render(
      <ToastProvider>
        <LicensesTab capabilities={["requests.view"]} />
      </ToastProvider>,
    );
    await waitFor(() => expect(screen.getByText("Demandes au Pilote")).toBeInTheDocument());
    expect(screen.queryByText("Licences nominatives")).not.toBeInTheDocument();
    expect(screen.queryByText("Sessions actives")).not.toBeInTheDocument();
    expect(screen.queryByText("Nouvelle demande")).not.toBeInTheDocument(); // pas de requests.create
    const urls = fetchMock.mock.calls.map(([u]) => String(u));
    expect(urls.some((u) => u.includes("/licensing/licenses"))).toBe(false);
  });
});
