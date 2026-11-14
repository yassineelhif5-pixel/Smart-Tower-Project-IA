import { useEffect, useState } from "react";

import { platformApi } from "../../api/endpoints";
import { Card, Field, useAction } from "../../components/ui";
import type { TenantDetail } from "../../types/api";

type Profile = Pick<TenantDetail, "industry" | "website" | "phone" | "address" | "city" | "country" | "contactName" | "contactEmail" | "contactPhone" | "description">;
export function TenantProfileEditor({ tenant, onSaved }: { tenant: TenantDetail; onSaved: () => void }) {
  const { run, busy } = useAction();
  const [form, setForm] = useState<Profile>({ industry: "", website: "", phone: "", address: "", city: "", country: "", contactName: "", contactEmail: "", contactPhone: "", description: "" });
  useEffect(() => setForm({ industry: tenant.industry, website: tenant.website, phone: tenant.phone, address: tenant.address,
    city: tenant.city, country: tenant.country, contactName: tenant.contactName, contactEmail: tenant.contactEmail,
    contactPhone: tenant.contactPhone, description: tenant.description }), [tenant]);
  const input = (key: keyof Profile, label: string, type = "text") => <Field key={key} id={`pilot-${key}`} label={label}>
    <input id={`pilot-${key}`} className="inp" type={type} value={form[key]} onChange={(e) => setForm((old) => ({ ...old, [key]: e.target.value }))} />
  </Field>;
  return <Card title="Informations de l’entreprise" sub="Fiche visible et modifiable par l’administrateur du client et le Pilote.">
    <div className="frow">{input("industry", "Domaine d’activité")}{input("website", "Site web", "url")}{input("phone", "Téléphone")}</div>
    <div className="frow">{input("contactName", "Contact principal")}{input("contactEmail", "E-mail du contact", "email")}{input("contactPhone", "Téléphone du contact")}</div>
    <div className="frow">{input("address", "Adresse")}{input("city", "Ville")}{input("country", "Pays")}</div>
    <Field id="pilot-description" label="Présentation"><textarea id="pilot-description" className="inp" rows={3} value={form.description} onChange={(e) => setForm((old) => ({ ...old, description: e.target.value }))} /></Field>
    <button className="btn primary" disabled={busy} onClick={() => run(() => platformApi.updateTenant(tenant.id, form), "Fiche entreprise enregistrée").then(onSaved, () => undefined)}>Enregistrer la fiche</button>
  </Card>;
}
