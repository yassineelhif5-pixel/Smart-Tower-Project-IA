// Parcours d'accueil d'un compte créé librement : profil, puis démo (3 jours, 2 projets) ou adhésion à une
// entreprise existante (code secret validé par son administrateur ou le Pilote). À la fin de la démo :
// activation d'une licence ou adhésion à une autre entreprise.
import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { api, ApiError } from "../api/client";
import { signupApi, type OnboardingResponse } from "../api/endpoints";
import { Copyright } from "../components/Copyright";
import { Field } from "../components/ui";
import { PrefsSwitcher } from "../i18n";
import type { Me, Onboarding } from "../types/api";
import { Brand } from "./LoginPage";

const STATUS: Record<string, [string, string]> = {
  pending: ["En attente de validation", "info"],
  approved: ["Acceptée", "ok"],
  rejected: ["Refusée", "warn"],
  cancelled: ["Annulée", ""],
};

function Frame({ me, onLogout, title, sub, children }: { me: Me; onLogout: () => void; title: string; sub: string; children: ReactNode }) {
  return (
    <main className="auth">
      <div className="auth-prefs"><PrefsSwitcher compact /></div>
      <div className="auth-card card onboarding-card">
        <div className="card-b" style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <Brand />
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span className="muted" style={{ fontSize: 13 }}>{me.name || me.email}</span>
              <button type="button" className="btn ghost sm" onClick={onLogout}>Se déconnecter</button>
            </div>
          </div>
          <div>
            <h1 style={{ margin: 0, fontSize: 22 }}>{title}</h1>
            <p className="muted" style={{ margin: "6px 0 0" }}>{sub}</p>
          </div>
          {children}
          <div style={{ textAlign: "center", borderTop: "1px solid var(--line, #e2e8f0)", paddingTop: 10 }}><Copyright /></div>
        </div>
      </div>
    </main>
  );
}

function errText(e: unknown) {
  return e instanceof ApiError ? e.message : "L’opération a échoué. Réessayez.";
}

export function OnboardingPage({ me, onDone, onLogout }: { me: Me; onDone: (me: Me) => void; onLogout: () => void }) {
  const [state, setState] = useState<{ ob: Onboarding; me: Me }>({ ob: me.onboarding as Onboarding, me });
  const [editProfile, setEditProfile] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const apply = async (p: Promise<OnboardingResponse>) => {
    setBusy(true);
    setError(null);
    try {
      let r = await p;
      if (!r.onboarding?.required && r.me.tenant) {
        r = await signupApi.enter();
        onDone(r.me);
        return r;
      }
      setState({ ob: r.onboarding, me: r.me });
      return r;
    } catch (e) {
      setError(errText(e));
      throw e;
    } finally {
      setBusy(false);
    }
  };
  const refresh = () => void apply(signupApi.state()).catch(() => undefined);
  useEffect(() => {
    const id = window.setInterval(() => {
      if (state.ob.step === "pending") refresh();
    }, 30000);
    return () => window.clearInterval(id);
  });

  const { ob } = state;
  const step = editProfile ? "profile" : ob.step;
  const err = error && <div className="callout warn" role="alert"><b>{error}</b></div>;

  if (step === "profile")
    return (
      <Frame me={state.me} onLogout={onLogout} title="Bienvenue sur Control Tower 👋" sub="Quelques informations pour préparer votre espace.">
        <ProfileForm ob={ob} busy={busy} onSubmit={(body) => void apply(signupApi.profile(body)).then(() => setEditProfile(false), () => undefined)} />
        {err}
      </Frame>
    );

  if (step === "demo_expired")
    return (
      <Frame me={state.me} onLogout={onLogout} title="Votre démo est terminée"
        sub={`La démo « ${ob.demo?.tenant ?? ""} » a pris fin le ${ob.demo ? new Date(ob.demo.until).toLocaleDateString("fr-FR") : ""}. Vos données sont conservées.`}>
        <ActivatePanel ob={ob} busy={busy} apply={apply} />
        <div className="onb-sep"><span>ou</span></div>
        <JoinPanel busy={busy} apply={apply} title="Rejoindre une autre entreprise" />
        <OtherTenants me={state.me} />
        <Requests ob={ob} busy={busy} apply={apply} />
        {err}
      </Frame>
    );

  const pending = ob.joinRequests.filter((r) => r.status === "pending");
  return (
    <Frame me={state.me} onLogout={onLogout}
      title={pending.length ? "Demande envoyée ✓" : "Comment souhaitez-vous commencer ?"}
      sub={pending.length
        ? "L’administrateur de l’entreprise (ou le Pilote) doit valider votre demande. Vous recevrez un e-mail dès qu’elle sera traitée."
        : "Essayez Control Tower avec une démo complète, ou rejoignez l’espace de votre entreprise."}>
      {pending.length > 0 && (
        <div className="callout info" role="status" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span>Cette page se met à jour automatiquement.</span>
          <button type="button" className="btn sm" disabled={busy} onClick={refresh}>Actualiser</button>
        </div>
      )}
      <Requests ob={ob} busy={busy} apply={apply} />
      <div className="onb-choices">
        <section className={`onb-choice${ob.hasHadDemo ? " disabled" : " recommended"}`}>
          {!ob.hasHadDemo && <span className="onb-badge">Recommandé</span>}
          <h3>🚀 Essayer la démo</h3>
          <ul>
            <li>Votre propre espace, dont vous êtes l’administrateur</li>
            <li>Tous les modules disponibles</li>
            <li>Jusqu’à 2 projets, pendant 3 jours</li>
            <li>Ensuite : activez une licence ou rejoignez une entreprise</li>
          </ul>
          <button type="button" className="btn primary" disabled={busy || ob.hasHadDemo}
            onClick={() => void apply(signupApi.demo()).catch(() => undefined)}>
            {ob.hasHadDemo ? "Démo déjà utilisée" : busy ? "Préparation…" : "Lancer ma démo"}
          </button>
        </section>
        <section className="onb-choice">
          <JoinPanel busy={busy} apply={apply} title="🏢 Rejoindre mon entreprise" compact />
        </section>
      </div>
      {err}
      <button type="button" className="auth-link-inline" onClick={() => setEditProfile(true)}>Modifier mon profil</button>
    </Frame>
  );
}

function ProfileForm({ ob, busy, onSubmit }: { ob: Onboarding; busy: boolean; onSubmit: (b: Record<string, string>) => void }) {
  const p = ob.profile;
  const [f, setF] = useState({
    kind: p?.kind || "company", firstName: p?.firstName ?? "", lastName: p?.lastName ?? "", jobTitle: p?.jobTitle ?? "",
    phone: p?.phone ?? "", country: p?.country || "France", companyName: p?.companyName ?? "", companySize: p?.companySize ?? "",
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit(f);
  };
  return (
    <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="onb-kinds" role="radiogroup" aria-label="Vous êtes">
        {([["company", "🏢 Je représente une entreprise", "ESN, cabinet, PME, grand compte…"],
          ["individual", "👤 Je suis particulier / indépendant", "Je travaille en autonomie (standalone)"]] as const).map(([k, l, s]) => (
          <button key={k} type="button" role="radio" aria-checked={f.kind === k} className={`onb-kind${f.kind === k ? " on" : ""}`} onClick={() => setF({ ...f, kind: k })}>
            <b>{l}</b><small className="muted">{s}</small>
          </button>
        ))}
      </div>
      <div className="grid g2" style={{ gap: 10 }}>
        <Field id="ob-first" label="Prénom"><input id="ob-first" className="inp" value={f.firstName} onChange={set("firstName")} required /></Field>
        <Field id="ob-last" label="Nom"><input id="ob-last" className="inp" value={f.lastName} onChange={set("lastName")} required /></Field>
        {f.kind === "company" && (
          <>
            <Field id="ob-company" label="Nom de l’entreprise"><input id="ob-company" className="inp" value={f.companyName} onChange={set("companyName")} required /></Field>
            <Field id="ob-size" label="Taille de l’entreprise">
              <select id="ob-size" className="inp" value={f.companySize} onChange={set("companySize")}>
                <option value="">—</option><option value="1-10">1 à 10</option><option value="11-50">11 à 50</option>
                <option value="51-250">51 à 250</option><option value="251-1000">251 à 1 000</option><option value="1000+">Plus de 1 000</option>
              </select>
            </Field>
          </>
        )}
        <Field id="ob-job" label="Fonction"><input id="ob-job" className="inp" placeholder="Chef de projet, consultant…" value={f.jobTitle} onChange={set("jobTitle")} /></Field>
        <Field id="ob-phone" label="Téléphone (facultatif)"><input id="ob-phone" className="inp" type="tel" value={f.phone} onChange={set("phone")} /></Field>
        <Field id="ob-country" label="Pays"><input id="ob-country" className="inp" value={f.country} onChange={set("country")} /></Field>
      </div>
      <button className="btn primary" type="submit" disabled={busy}>{busy ? "Enregistrement…" : "Continuer"}</button>
    </form>
  );
}

function JoinPanel({ busy, apply, title, compact }: { busy: boolean; apply: (p: Promise<OnboardingResponse>) => Promise<OnboardingResponse>; title: string; compact?: boolean }) {
  const [code, setCode] = useState("");
  const [message, setMessage] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void apply(signupApi.join(code, message)).then(() => { setCode(""); setMessage(""); }, () => undefined);
  };
  return (
    <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <h3 style={{ margin: 0 }}>{title}</h3>
      {compact && <p className="muted" style={{ margin: 0, fontSize: 13 }}>Demandez le code entreprise à votre administrateur. Il validera votre accès et votre profil.</p>}
      <Field id={`join-code-${title}`} label="Code entreprise">
        <input id={`join-code-${title}`} className="inp mono" placeholder="XXXX-XXXX" maxLength={12} value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())} required style={{ letterSpacing: 2 }} />
      </Field>
      <Field id={`join-msg-${title}`} label="Message (projet à rejoindre, contexte…)">
        <textarea id={`join-msg-${title}`} className="inp" rows={2} maxLength={500} value={message} onChange={(e) => setMessage(e.target.value)} />
      </Field>
      <button className="btn" type="submit" disabled={busy || code.replace(/[^A-Z0-9]/g, "").length !== 8}>Envoyer la demande</button>
    </form>
  );
}

function Requests({ ob, busy, apply }: { ob: Onboarding; busy: boolean; apply: (p: Promise<OnboardingResponse>) => Promise<OnboardingResponse> }) {
  if (!ob.joinRequests.length) return null;
  return (
    <div className="onb-requests">
      <b style={{ fontSize: 13 }}>Mes demandes d’adhésion</b>
      {ob.joinRequests.map((r) => (
        <div key={r.id} className="onb-request">
          <div>
            <b>{r.tenant}</b> <span className={`pill ${STATUS[r.status]?.[1] ?? ""}`}>{STATUS[r.status]?.[0] ?? r.status}</span>
            <div className="muted" style={{ fontSize: 12 }}>
              Envoyée le {new Date(r.createdAt).toLocaleString("fr-FR")}
              {r.role ? ` · profil : ${r.role}` : ""}{r.comment ? ` · ${r.comment}` : ""}
            </div>
          </div>
          {r.status === "pending" && (
            <button type="button" className="btn ghost sm" disabled={busy} onClick={() => void apply(signupApi.cancelJoin(r.id)).catch(() => undefined)}>Annuler</button>
          )}
        </div>
      ))}
    </div>
  );
}

function ActivatePanel({ ob, busy, apply }: { ob: Onboarding; busy: boolean; apply: (p: Promise<OnboardingResponse>) => Promise<OnboardingResponse> }) {
  const offers = ob.offers ?? [];
  const [version, setVersion] = useState<number | "">(offers[0]?.id ?? "");
  const [why, setWhy] = useState("");
  const [voucher, setVoucher] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const lr = ob.licenseRequest;
  const open = lr && ["SUBMITTED", "UNDER_REVIEW", "ADDITIONAL_INFORMATION_REQUIRED"].includes(lr.status);
  if (!ob.isDemoAdmin)
    return <div className="callout info">L’administrateur de la démo peut activer une licence. Vous pouvez aussi rejoindre une autre entreprise ci-dessous.</div>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <h3 style={{ margin: 0 }}>🔑 Activer une licence pour « {ob.demo?.tenant} »</h3>
      {open ? (
        <div className="callout info"><b>Demande n° {lr.id} — {lr.statusLabel}</b><div>Offre demandée : {lr.offer}. Le Pilote vous répondra par e-mail ; l’accès reprend dès l’activation.</div></div>
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); if (version !== "") void apply(signupApi.activate({ mode: "request", versionId: version, justification: why })).then(() => setDone("Demande envoyée au Pilote."), () => undefined); }}
          style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {offers.length ? (
            <div className="onb-offers">
              {offers.map((o) => (
                <label key={o.id} className={`onb-offer${version === o.id ? " on" : ""}`}>
                  <input type="radio" name="offer" checked={version === o.id} onChange={() => setVersion(o.id)} />
                  <span><b>{o.offer}</b>{o.price !== null && <> · {Number(o.price).toLocaleString("fr-FR")} {o.currency} / {o.period.toLowerCase()}</>}
                    {o.maxUsers ? <> · {o.maxUsers} utilisateurs</> : null}
                    {o.description && <small className="muted" style={{ display: "block" }}>{o.description}</small>}</span>
                </label>
              ))}
            </div>
          ) : <p className="muted" style={{ margin: 0 }}>Aucune offre publiée pour l’instant : décrivez votre besoin au Pilote.</p>}
          <Field id="act-why" label="Votre besoin (facultatif)">
            <textarea id="act-why" className="inp" rows={2} value={why} onChange={(e) => setWhy(e.target.value)} placeholder="Nombre d’utilisateurs, modules, date de démarrage…" />
          </Field>
          <button className="btn primary" type="submit" disabled={busy || version === ""}>Demander l’activation au Pilote</button>
        </form>
      )}
      <form onSubmit={(e) => { e.preventDefault(); void apply(signupApi.activate({ mode: "voucher", code: voucher })).then(() => setDone("Licence activée."), () => undefined); }}
        style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <Field id="act-voucher" label="Vous avez un voucher ?">
            <input id="act-voucher" className="inp mono" placeholder="Code voucher" value={voucher} onChange={(e) => setVoucher(e.target.value)} />
          </Field>
        </div>
        <button className="btn" type="submit" disabled={busy || voucher.replace(/[^A-Za-z0-9]/g, "").length < 32}>Activer</button>
      </form>
      {done && <div className="callout ok" role="status">{done}</div>}
    </div>
  );
}

function OtherTenants({ me }: { me: Me }) {
  const others = (me.tenants ?? []).filter((t) => !t.current && t.active);
  if (!others.length) return null;
  return (
    <div className="onb-requests">
      <b style={{ fontSize: 13 }}>Vos autres entreprises</b>
      {others.map((t) => (
        <div key={t.id} className="onb-request">
          <div><b>{t.name}</b>{t.role && <span className="muted"> · {t.role}</span>}</div>
          <button type="button" className="btn sm" onClick={() => void api.post("/auth/tenants", { tenant: t.id }).then(() => window.location.reload(), () => undefined)}>Ouvrir</button>
        </div>
      ))}
    </div>
  );
}

export function DemoBanner({ me }: { me: Me }) {
  const d = me.onboarding?.demo;
  if (!d || d.expired) return null;
  return (
    <div className="demo-banner" role="status">
      <b>Démo</b> · {d.daysLeft <= 1 ? "dernier jour" : `${d.daysLeft} jours restants`} (jusqu’au {new Date(d.until).toLocaleDateString("fr-FR")})
      · projets : {d.projects}/{d.maxProjects}
      <span className="muted"> — à la fin de la démo, activez une licence ou rejoignez une entreprise.</span>
    </div>
  );
}
