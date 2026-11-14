import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../components/ui";
import type { Message } from "../../types/collab";
import { DiscussionMessage } from "./DiscussionMessage";

const msg = (over: Partial<Message> = {}): Message => ({
  id: 1,
  kind: "message",
  author: { id: 2, username: "ib", name: "S. Mansouri" },
  externalAuthor: "",
  body: "Bonjour l'équipe",
  deleted: false,
  parent: null,
  origin: "pct",
  publicationStatus: "published",
  publicationError: "",
  mentions: [],
  attachments: [],
  createdAt: "2026-11-01T10:00:00Z",
  editedAt: null,
  deletedAt: null,
  historyCount: 0,
  mine: false,
  canEdit: false,
  canRetry: false,
  ...over,
});

const show = (m: Message) =>
  render(
    <ToastProvider>
      <DiscussionMessage message={m} onReply={vi.fn()} onChanged={vi.fn()} showStatus />
    </ToastProvider>,
  );

describe("message de discussion", () => {
  it("seul l'auteur peut modifier ou supprimer", () => {
    show(msg());
    expect(screen.queryByText("Modifier")).not.toBeInTheDocument();
    expect(screen.queryByText("Supprimer")).not.toBeInTheDocument();
    expect(screen.getByText("Répondre")).toBeInTheDocument();
  });
  it("l'auteur voit ses actions et l'état de publication Teams", () => {
    show(msg({ mine: true, canEdit: true }));
    expect(screen.getByText("Modifier")).toBeInTheDocument();
    expect(screen.getByText("Supprimer")).toBeInTheDocument();
    expect(screen.getByText("Publié dans Teams")).toBeInTheDocument();
  });
  it("un échec de publication s'explique et se renvoie", () => {
    show(msg({ mine: true, canRetry: true, publicationStatus: "failed", publicationError: "Permission manquante." }));
    expect(screen.getByText("Échec Teams")).toBeInTheDocument();
    expect(screen.getByText("Permission manquante.")).toBeInTheDocument();
    expect(screen.getByText("Renvoyer dans Teams")).toBeInTheDocument();
  });
  it("un message reçu de Teams sans compte PCT garde le nom de son auteur", () => {
    show(msg({ author: null, externalAuthor: "Client X", origin: "teams" }));
    expect(screen.getByText("Client X")).toBeInTheDocument();
    expect(screen.getByText("Teams")).toBeInTheDocument();
  });
  it("un message supprimé n'affiche plus son contenu", () => {
    show(msg({ deleted: true, body: "" }));
    expect(screen.getByText("Message supprimé")).toBeInTheDocument();
  });
});
