// Libellés et tons partagés par les écrans Pilote, entreprise et utilisateur.
import type { RequestStatus } from "../../types/api";

type Tone = "ok" | "warn" | "crit" | "info" | "acc" | "";

export const TENANT_TONE: Record<string, Tone> = { active: "ok", suspended: "warn", disabled: "crit", archived: "" };

export const SUB_TONE: Record<string, Tone> = {
  trial: "info",
  active: "ok",
  suspended: "warn",
  expired: "crit",
  cancelled: "",
};

export const REQUEST_LABEL: Record<RequestStatus, string> = {
  DRAFT: "Brouillon",
  SUBMITTED: "Soumise",
  UNDER_REVIEW: "En cours d'examen",
  ADDITIONAL_INFORMATION_REQUIRED: "Informations demandées",
  APPROVED: "Approuvée",
  PARTIALLY_APPROVED: "Approuvée partiellement",
  REJECTED: "Refusée",
  CANCELLED: "Annulée",
  FULFILLED: "Réalisée",
};

export const REQUEST_TONE: Record<RequestStatus, Tone> = {
  DRAFT: "",
  SUBMITTED: "info",
  UNDER_REVIEW: "info",
  ADDITIONAL_INFORMATION_REQUIRED: "warn",
  APPROVED: "acc",
  PARTIALLY_APPROVED: "acc",
  REJECTED: "crit",
  CANCELLED: "",
  FULFILLED: "ok",
};

export const REQUEST_KINDS: [string, string][] = [
  ["named", "Licences nominatives supplémentaires"],
  ["concurrent", "Licences concurrentes supplémentaires"],
  ["quota", "Augmentation de quota"],
  ["offer", "Évolution d'offre"],
  ["option", "Option contractuelle"],
];

export const KIND_LABEL: Record<string, string> = { named: "Nominative", concurrent: "Concurrente" };

export const fmtDay = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("fr-FR") : "—");

export const fmtPrice = (price: string | null, currency: string, period: string) =>
  price === null
    ? "Prix à définir"
    : `${Number(price).toLocaleString("fr-FR", { style: "currency", currency })} / ${
        { month: "mois", year: "an", once: "unique" }[period] ?? period
      }`;
