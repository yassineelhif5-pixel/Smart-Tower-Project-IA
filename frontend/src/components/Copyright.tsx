// Mention de propriété du SaaS : conçu et édité par ZirconAI.
export function Copyright({ compact = false }: { compact?: boolean }) {
  const year = new Date().getFullYear();
  return (
    <span className="copyright" style={{ fontSize: compact ? 11 : 12, opacity: 0.8 }}>
      © {year} <a href="https://zirconai.fr/" target="_blank" rel="noopener noreferrer" style={{ color: "inherit", fontWeight: 600 }}>ZirconAI</a>
      {compact ? "" : " — Project Control Tower, conçu et édité par ZirconAI. Tous droits réservés."}
    </span>
  );
}
