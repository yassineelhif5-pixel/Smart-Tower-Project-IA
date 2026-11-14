import { useEffect, useState } from "react";

import { adminApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Loading, useAction } from "../../components/ui";
import type { TenantRow } from "../../types/api";

type Profile = Pick<TenantRow, "industry" | "website" | "phone" | "address" | "city" | "country" | "contactName" | "contactEmail" | "contactPhone" | "description">;
const EMPTY: Profile = { industry: "", website: "", phone: "", address: "", city: "", country: "", contactName: "", contactEmail: "", contactPhone: "", description: "" };

export function CompanyProfileTab() {
  const data = useApi(adminApi.companyProfile);
  const { run, busy } = useAction();
  const [form, setForm] = useState<Profile>(EMPTY);
  useEffect(() => { if (data.data) setForm(Object.fromEntries(Object.keys(EMPTY).map((key) => [key, data.data![key as keyof Profile] ?? ""])) as Profile); }, [data.data]);
  if (data.error) return <ErrorNotice error={data.error} onRetry={data.reload} />;
  if (!data.data) return <Loading />;
  const field = (key: keyof Profile, label: string, type = "text") => <Field key={key} id={`company-${key}`} label={label}>
    <input id={`company-${key}`} className="inp" type={type} value={form[key]} onChange={(e) => setForm((old) => ({ ...old, [key]: e.target.value }))} />
  </Field>;
  return <Card title={`Fiche entreprise · ${data.data.name}`} sub="Ces coordonnées sont visibles uniquement par les administrateurs de votre entreprise et le Pilote.">
    <div className="frow">{field("industry", "Domaine d’activité")}{field("website", "Site web", "url")}{field("phone", "Téléphone")}</div>
    <div className="frow">{field("contactName", "Nom du contact principal")}{field("contactEmail", "E-mail du contact", "email")}{field("contactPhone", "Téléphone du contact")}</div>
    <div className="frow">{field("address", "Adresse")}{field("city", "Ville")}{field("country", "Pays")}</div>
    <Field id="company-description" label="Présentation de l’entreprise"><textarea id="company-description" className="inp" rows={4} value={form.description} onChange={(e) => setForm((old) => ({ ...old, description: e.target.value }))} /></Field>
    <button className="btn primary" disabled={busy} onClick={() => run(() => adminApi.updateCompanyProfile(form), "Fiche entreprise enregistrée").then((result) => { if (result) data.setData(result); }, () => undefined)}>Enregistrer les informations</button>
  </Card>;
}
