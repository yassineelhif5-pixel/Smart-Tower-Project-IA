import re


_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_domain(value):
    raw = str(value or "").strip().rstrip(".")
    try:
        domain = raw.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("Nom de domaine invalide.") from exc
    labels = domain.split(".")
    if len(domain) > 253 or len(labels) < 2 or any(not _LABEL.fullmatch(label) for label in labels):
        raise ValueError("Indiquez un domaine complet, sans caractère générique (ex. entreprise.fr).")
    return domain


def email_domain(value):
    email = str(value or "").strip()
    if email.count("@") != 1:
        raise ValueError("Indiquez votre adresse professionnelle.")
    local, raw_domain = email.rsplit("@", 1)
    if not local or len(email) > 254:
        raise ValueError("Indiquez votre adresse professionnelle.")
    return email, normalize_domain(raw_domain)
