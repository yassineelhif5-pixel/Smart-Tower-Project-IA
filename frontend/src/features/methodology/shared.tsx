// Éléments communs du pilotage : graphiques SVG légers, libellés, choix du sprint, panneau de propositions.
import { useEffect, useState, type ReactNode } from "react";

import { ApiError } from "../../api/client";
import { methodologyApi } from "../../api/methodology";
import { useApi } from "../../api/useApi";
import { ErrorNotice, Loading, Pill, useToast } from "../../components/ui";
import type { SprintRow } from "../../types/methodology";

export const PRIORITY: Record<string, string> = {
  low: "Basse",
  normal: "Normale",
  high: "Haute",
  critical: "Critique",
};
export const GOAL_STATUS: Record<string, string> = {
  not_started: "Non démarré",
  in_progress: "En cours",
  achieved: "Atteint",
  partial: "Partiellement atteint",
  missed: "Non atteint",
  on_track: "En bonne voie",
  at_risk: "À risque",
};
export const ACTION_STATUS: Record<string, string> = {
  todo: "À faire",
  planned: "Planifiée",
  doing: "En cours",
  review: "En revue",
  blocked: "Bloquée",
  done: "Terminée",
};
export const toneOf = (s: string): "ok" | "warn" | "crit" | "info" | "" =>
  ["achieved", "done", "ok", "closed", "on_track", "resolved"].includes(s)
    ? "ok"
    : ["partial", "at_risk", "late", "under", "doing", "in_progress", "active"].includes(s)
      ? "warn"
      : ["missed", "blocked", "over", "failed", "open"].includes(s)
        ? "crit"
        : ["planned", "collecting", "validated"].includes(s)
          ? "info"
          : "";

export const fmt = (d: string | null | undefined) =>
  d
    ? new Date(d.length === 10 ? `${d}T12:00:00` : d).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" })
    : "—";

export function Status({ value, label }: { value: string; label?: string }) {
  return <Pill tone={toneOf(value)}>{label ?? GOAL_STATUS[value] ?? ACTION_STATUS[value] ?? value}</Pill>;
}

export function Kpi({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: string; tone?: string }) {
  return (
    <div className={`kpi ${tone ?? ""}`}>
      <label>{label}</label>
      <strong>{value}</strong>
      {sub && <small>{sub}</small>}
    </div>
  );
}

type Series = { name: string; values: (number | null)[]; color: string; dashed?: boolean };

/** Courbes (burndown, burnup) : SVG accessible, sans dépendance. */
export function LineChart({
  labels,
  series,
  height = 200,
  unit = "",
}: {
  labels: string[];
  series: Series[];
  height?: number;
  unit?: string;
}) {
  const w = 640;
  const pad = { l: 36, r: 10, t: 10, b: 24 };
  const max = Math.max(1, ...series.flatMap((s) => s.values.filter((v): v is number => v != null)));
  const x = (i: number) => pad.l + (labels.length <= 1 ? 0 : (i / (labels.length - 1)) * (w - pad.l - pad.r));
  const y = (v: number) => pad.t + (1 - v / max) * (height - pad.t - pad.b);
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${w} ${height}`} role="img" aria-label={series.map((s) => s.name).join(", ")}>
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={pad.l} x2={w - pad.r} y1={y(max * f)} y2={y(max * f)} className="grid-l" />
            <text x={pad.l - 6} y={y(max * f) + 4} textAnchor="end" className="axis">
              {Math.round(max * f)}
            </text>
          </g>
        ))}
        {labels.map((l, i) =>
          i % Math.max(1, Math.ceil(labels.length / 8)) === 0 ? (
            <text key={l} x={x(i)} y={height - 6} textAnchor="middle" className="axis">
              {fmt(l)}
            </text>
          ) : null,
        )}
        {series.map((s) => {
          const pts = s.values.map((v, i) => (v == null ? null : `${x(i)},${y(v)}`)).filter(Boolean);
          return (
            <polyline
              key={s.name}
              points={pts.join(" ")}
              fill="none"
              stroke={s.color}
              strokeWidth={2}
              strokeDasharray={s.dashed ? "5 4" : undefined}
            />
          );
        })}
      </svg>
      <figcaption className="legend">
        {series.map((s) => (
          <span key={s.name}>
            <i style={{ background: s.color }} /> {s.name}
            {unit}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

/** Barres groupées (vélocité, capacité par semaine). */
export function BarChart({ labels, series, height = 180 }: { labels: string[]; series: Series[]; height?: number }) {
  const w = 640;
  const pad = { l: 36, r: 10, t: 10, b: 24 };
  const max = Math.max(1, ...series.flatMap((s) => s.values.map((v) => v ?? 0)));
  const band = (w - pad.l - pad.r) / Math.max(labels.length, 1);
  const bw = Math.min(26, (band * 0.75) / series.length);
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${w} ${height}`} role="img" aria-label={series.map((s) => s.name).join(", ")}>
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line
              x1={pad.l}
              x2={w - pad.r}
              y1={pad.t + (1 - f) * (height - pad.t - pad.b)}
              y2={pad.t + (1 - f) * (height - pad.t - pad.b)}
              className="grid-l"
            />
            <text x={pad.l - 6} y={pad.t + (1 - f) * (height - pad.t - pad.b) + 4} textAnchor="end" className="axis">
              {Math.round(max * f)}
            </text>
          </g>
        ))}
        {labels.map((l, i) => (
          <g key={l}>
            {series.map((s, j) => {
              const v = s.values[i] ?? 0;
              const h = (v / max) * (height - pad.t - pad.b);
              return (
                <rect
                  key={s.name}
                  x={pad.l + band * i + (band - bw * series.length) / 2 + j * bw}
                  y={height - pad.b - h}
                  width={bw - 2}
                  height={h}
                  rx={3}
                  fill={s.color}
                >
                  <title>{`${s.name} : ${v}`}</title>
                </rect>
              );
            })}
            <text x={pad.l + band * i + band / 2} y={height - 6} textAnchor="middle" className="axis">
              {l}
            </text>
          </g>
        ))}
      </svg>
      <figcaption className="legend">
        {series.map((s) => (
          <span key={s.name}>
            <i style={{ background: s.color }} /> {s.name}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

export const COLORS = { a: "var(--accent)", b: "var(--info)", c: "var(--warn)", d: "var(--faint)", e: "var(--crit)" };

/** Choix du sprint affiché (actif par défaut). */
export function useSprint(projectId: string) {
  const list = useApi(() => methodologyApi.sprints(projectId), [projectId]);
  const [id, setId] = useState<number | null>(null);
  useEffect(() => {
    if (!list.data || id) return;
    const s = list.data.sprints;
    const pick =
      s.find((x) => x.status === "active") ??
      s.find((x) => ["planned", "preparing"].includes(x.status)) ??
      s[s.length - 1];
    if (pick) setId(pick.id);
  }, [list.data, id]);
  return { list, id, setId, current: list.data?.sprints.find((s) => s.id === id) ?? null };
}

export function SprintPicker({
  sprints,
  value,
  onChange,
}: {
  sprints: SprintRow[];
  value: number | null;
  onChange: (id: number) => void;
}) {
  return (
    <select
      className="inp sprint-pick"
      aria-label="Sprint"
      value={value ?? ""}
      onChange={(e) => onChange(Number(e.target.value))}
    >
      {sprints.map((s) => (
        <option key={s.id} value={s.id}>
          {s.label} · {fmt(s.start)} → {fmt(s.end)} · {s.statusLabel}
        </option>
      ))}
    </select>
  );
}

/** Propositions calculées par des règles : affichées, jamais appliquées automatiquement. */
export function AssistPanel({ projectId, topics }: { projectId: string; topics: [string, string][] }) {
  const [topic, setTopic] = useState<string | null>(null);
  const a = useApi(() => (topic ? methodologyApi.assist(projectId, topic) : Promise.resolve(null)), [topic, projectId]);
  return (
    <div className="assist">
      <div className="assist-h">
        <b>Propositions</b>
        <div className="chips">
          {topics.map(([k, l]) => (
            <button key={k} className={`chip ${topic === k ? "on" : ""}`} onClick={() => setTopic(k)}>
              {l}
            </button>
          ))}
        </div>
      </div>
      {topic && a.error && <ErrorNotice error={a.error} />}
      {topic && a.loading && <Loading />}
      {a.data && (
        <>
          <small className="muted">{a.data.note}</small>
          {a.data.items.length === 0 ? (
            <p className="muted">Rien à signaler.</p>
          ) : (
            <ul className="plain">
              {a.data.items.map((i, n) => (
                <li key={n}>
                  <b>{i.title}</b> {i.reason && <span className="muted">— {i.reason}</span>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

/** Exécute un appel ; affiche la raison d'un refus (409 de contrôle) et propose de confirmer. */
export function useGuarded() {
  const toast = useToast();
  const [pending, setPending] = useState<{ message: string; details: string[]; retry: () => Promise<unknown> } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const run = async <T,>(fn: (confirm: boolean) => Promise<T>, ok?: string): Promise<T | undefined> => {
    setBusy(true);
    try {
      const r = await fn(false);
      if (ok) toast(ok);
      return r;
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.code !== "CONFLICT") {
        const details = (e.details as unknown[]).map((d) =>
          typeof d === "string"
            ? d
            : String(
                (d as { message?: string; explanation?: string; title?: string }).message ??
                  (d as { explanation?: string }).explanation ??
                  JSON.stringify(d),
              ),
        );
        setPending({
          message: e.message,
          details,
          retry: async () => {
            await fn(true);
            if (ok) toast(ok);
          },
        });
      } else if (e instanceof ApiError) toast(e.message, true);
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return { run, busy, pending, setPending };
}

export function GuardDialog({
  guard,
  confirmLabel = "Confirmer malgré tout",
}: {
  guard: ReturnType<typeof useGuarded>;
  confirmLabel?: string;
}) {
  const p = guard.pending;
  if (!p) return null;
  return (
    <div className="scrim" role="dialog" aria-modal="true" aria-label="Vérification">
      <div className="modal">
        <div className="modal-h">
          <h3>Vérification avant enregistrement</h3>
        </div>
        <div className="modal-b">
          <p>
            <b>{p.message}</b>
          </p>
          <ul className="plain">
            {p.details.map((d, i) => (
              <li key={i}>• {d}</li>
            ))}
          </ul>
          <p className="muted">Rien n'a été enregistré. Vous pouvez ajuster, ou confirmer en connaissance de cause.</p>
        </div>
        <div className="modal-f">
          <button className="btn" onClick={() => guard.setPending(null)}>
            Annuler
          </button>
          <button
            className="btn primary"
            onClick={() => {
              const retry = p.retry;
              guard.setPending(null);
              void retry().catch(() => undefined);
            }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
