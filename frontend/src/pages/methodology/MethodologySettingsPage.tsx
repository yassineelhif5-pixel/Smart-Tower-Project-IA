import { useState } from "react";

import { methodologyApi } from "../../api/methodology";
import { Card, Field, fmtDate, Switch, useAction } from "../../components/ui";
import { GuardDialog, useGuarded } from "../../features/methodology/shared";
import type { BoardColumn, Feature, Impact, MethodKind } from "../../types/methodology";
import type { PageProps } from "./types";

const KINDS: [MethodKind, string, string][] = [
  ["vcycle", "Cycle en V", "Phases, objectifs hebdomadaires, capacité, rétrospectives à la fréquence choisie."],
  ["scrum", "Scrum", "Product Backlog, sprints, Sprint Goal, Daily, Review, rétrospective à chaque sprint."],
  ["hybrid", "Agile hybride", "Phases et semaines du Cycle en V, avec des sprints pour la réalisation."],
  ["custom", "Personnalisée", "Vous choisissez les fonctionnalités actives."],
];
const FEATURES: [Feature, string][] = [
  ["phases", "Phases"],
  ["weekly", "Semaines et Weekly Goals"],
  ["scrum", "Scrum"],
  ["capacity", "Capacité"],
  ["retro", "Rétrospectives"],
];
const FREQ: [string, string][] = [
  ["sprint", "À chaque fin de sprint"],
  ["weekly", "Hebdomadaire"],
  ["monthly", "Mensuelle"],
  ["phase", "À la fin d'une phase"],
  ["milestone", "À la fin d'un jalon"],
  ["project", "À la fin du projet"],
  ["none", "Aucune automatique"],
];

/** Méthodologie du projet (changement contrôlé par analyse d'impact) et paramètres. */
export function MethodologySettingsPage({ info, reload }: PageProps) {
  const [kind, setKind] = useState<MethodKind>(info.kind);
  const [features, setFeatures] = useState<Feature[]>(info.customFeatures.length ? info.customFeatures : info.features);
  const [impact, setImpact] = useState<Impact | null>(null);
  const [s, setS] = useState(info.settings);
  const guard = useGuarded();
  const { run, busy } = useAction();
  const id = info.project.id;

  const analyse = async () =>
    setImpact(await methodologyApi.impact(id, kind, kind === "custom" ? features : undefined));
  const apply = () =>
    void guard.run(
      (confirm) =>
        methodologyApi.save(id, { kind, features: kind === "custom" ? features : undefined, confirm }).then(reload),
      "Méthodologie modifiée",
    );
  const setCol = (i: number, patch: Partial<BoardColumn>) =>
    setS({ ...s, boardColumns: s.boardColumns.map((c, j) => (i === j ? { ...c, ...patch } : c)) });

  return (
    <div className="grid g2">
      <Card title="Méthodologie du projet" sub="Elle active les écrans, indicateurs et processus correspondants.">
        <fieldset className="method-kinds" disabled={!info.can.approve}>
          {KINDS.map(([k, l, d]) => (
            <label key={k} className={kind === k ? "on" : ""}>
              <input type="radio" name="kind" checked={kind === k} onChange={() => (setKind(k), setImpact(null))} />
              <span>
                <b>{l}</b>
                <small>{d}</small>
              </span>
            </label>
          ))}
        </fieldset>
        {kind === "custom" && (
          <div className="chips" style={{ marginTop: 10 }}>
            {FEATURES.map(([f, l]) => (
              <button
                key={f}
                className={`chip ${features.includes(f) ? "on" : ""}`}
                aria-pressed={features.includes(f)}
                onClick={() => setFeatures(features.includes(f) ? features.filter((x) => x !== f) : [...features, f])}
              >
                {l}
              </button>
            ))}
          </div>
        )}
        {info.can.approve && (kind !== info.kind || kind === "custom") && (
          <div className="btns" style={{ marginTop: 12 }}>
            <button className="btn" onClick={() => void analyse()}>
              Analyser l'impact
            </button>
            <button className="btn primary" disabled={!impact} onClick={apply}>
              Appliquer le changement
            </button>
          </div>
        )}
        {impact && (
          <div className="callout info" style={{ marginTop: 12 }}>
            <div>
              <b>Analyse d'impact</b>
              <div>
                Activé : {impact.enabled.join(", ") || "—"} · Désactivé : {impact.disabled.join(", ") || "—"}
              </div>
              {impact.warnings.map((w) => (
                <div key={w} className="t-warn">
                  {w}
                </div>
              ))}
              <div className="muted">Aucune donnée n'est supprimée : ce qui est désactivé est seulement masqué.</div>
            </div>
          </div>
        )}
        {!info.can.approve && <p className="muted">Changement réservé au droit « Méthodologie · Valider ».</p>}
        {info.history.length > 0 && (
          <>
            <h4 className="ev-sec">Historique</h4>
            <ul className="plain">
              {info.history.map((h) => (
                <li key={h.at} className="muted">
                  {fmtDate(h.at)} · {h.by} : {h.from} → {h.to}
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>
      <Card title="Paramètres" sub="Propres à ce projet et à son équipe.">
        <div className="ev-form">
          <div className="grid g2">
            <Field
              id="m-ratio"
              label={`Capacité productive : ${Math.round(s.productiveRatio * 100)} %`}
              hint="Part du temps disponible réellement consacrée aux tâches (hors échanges, support…)."
            >
              <input
                id="m-ratio"
                type="range"
                min={0.3}
                max={1}
                step={0.05}
                value={s.productiveRatio}
                onChange={(e) => setS({ ...s, productiveRatio: Number(e.target.value) })}
              />
            </Field>
            <Field id="m-tz" label="Fuseau horaire des cérémonies">
              <input
                id="m-tz"
                className="inp"
                value={s.timezone}
                onChange={(e) => setS({ ...s, timezone: e.target.value })}
              />
            </Field>
            {info.features.includes("scrum") && (
              <Field id="m-weeks" label="Durée des sprints">
                <select
                  id="m-weeks"
                  className="inp"
                  value={s.sprintWeeks}
                  onChange={(e) => setS({ ...s, sprintWeeks: Number(e.target.value) })}
                >
                  {[1, 2, 3, 4].map((w) => (
                    <option key={w} value={w}>
                      {w} semaine{w > 1 ? "s" : ""}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            <Field id="m-freq" label="Rétrospectives">
              <select
                id="m-freq"
                className="inp"
                value={s.retroFrequency}
                onChange={(e) => setS({ ...s, retroFrequency: e.target.value })}
              >
                {FREQ.map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
            <Field id="m-rem" label="Rappels de rétrospective (heures avant)" hint="Ex. 48, 24, 0 (0 = le jour même).">
              <input
                id="m-rem"
                className="inp"
                value={s.reminderHours.join(", ")}
                onChange={(e) =>
                  setS({
                    ...s,
                    reminderHours: e.target.value
                      .split(",")
                      .map((x) => Number(x.trim()))
                      .filter((x) => !Number.isNaN(x)),
                  })
                }
              />
            </Field>
            {info.features.includes("scrum") && (
              <Field id="m-daily" label="Daily Scrum">
                <div className="dep-row">
                  <input
                    id="m-daily"
                    className="inp"
                    type="time"
                    value={s.dailyTime}
                    onChange={(e) => setS({ ...s, dailyTime: e.target.value })}
                  />
                  <input
                    className="inp"
                    type="number"
                    min={5}
                    max={60}
                    aria-label="Durée du Daily (min)"
                    value={s.dailyMinutes}
                    onChange={(e) => setS({ ...s, dailyMinutes: Number(e.target.value) })}
                  />
                  <label className="switch-row">
                    <Switch
                      label="Daily dans le calendrier"
                      checked={s.dailyInCalendar}
                      onChange={(v) => setS({ ...s, dailyInCalendar: v })}
                    />{" "}
                    calendrier
                  </label>
                </div>
              </Field>
            )}
            {info.features.includes("weekly") && (
              <Field id="m-week" label="Réunion hebdomadaire">
                <div className="dep-row">
                  <select
                    id="m-week"
                    className="inp"
                    value={s.weeklyPlanningDay}
                    onChange={(e) => setS({ ...s, weeklyPlanningDay: Number(e.target.value) })}
                  >
                    {["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"].map((d, i) => (
                      <option key={d} value={i}>
                        {d}
                      </option>
                    ))}
                  </select>
                  <input
                    className="inp"
                    type="time"
                    aria-label="Heure"
                    value={s.weeklyPlanningTime}
                    onChange={(e) => setS({ ...s, weeklyPlanningTime: e.target.value })}
                  />
                </div>
              </Field>
            )}
          </div>
          {info.features.includes("scrum") && (
            <>
              <h4 className="ev-sec">Colonnes du Sprint Board</h4>
              {s.boardColumns.map((c, i) => (
                <div key={i} className="dep-row">
                  <input
                    className="inp mono"
                    aria-label="Clé"
                    value={c.key}
                    onChange={(e) => setCol(i, { key: e.target.value })}
                    style={{ maxWidth: 120 }}
                  />
                  <input
                    className="inp"
                    aria-label="Libellé"
                    value={c.label}
                    onChange={(e) => setCol(i, { label: e.target.value })}
                  />
                  <label className="cal-check">
                    <input type="checkbox" checked={c.done} onChange={(e) => setCol(i, { done: e.target.checked })} />{" "}
                    terminé
                  </label>
                  <button
                    className="icon-btn"
                    aria-label="Retirer la colonne"
                    onClick={() => setS({ ...s, boardColumns: s.boardColumns.filter((_, j) => j !== i) })}
                  >
                    ×
                  </button>
                </div>
              ))}
              <button
                className="btn sm ghost"
                onClick={() =>
                  setS({
                    ...s,
                    boardColumns: [
                      ...s.boardColumns,
                      { key: `col${s.boardColumns.length + 1}`, label: "Nouvelle", done: false },
                    ],
                  })
                }
              >
                + Colonne
              </button>
            </>
          )}
          <div className="btns">
            <button
              className="btn primary"
              disabled={busy || !info.can.edit}
              onClick={() =>
                void run(() => methodologyApi.save(id, { settings: s }), "Paramètres enregistrés").then(
                  reload,
                  () => undefined,
                )
              }
            >
              Enregistrer
            </button>
          </div>
        </div>
      </Card>
      <GuardDialog guard={guard} confirmLabel="Changer de méthodologie" />
    </div>
  );
}
