import csv
import json
import os
import re
from pathlib import Path
from typing import Optional


ROOT = Path(os.environ.get("SIM_ENG_PROJECT_ROOT", "/Users/nilay/Documents/New project")).expanduser()
ROWS_PATH = ROOT / "outlook_rows_raw.json"
RAW_CANDIDATES_PATH = ROOT / "outlook_companies_raw.txt"
OUTPUT_PATH = ROOT / "outlook_company_master.txt"
REPORT_PATH = ROOT / "outlook_company_report.json"
UNMATCHED_PATH = ROOT / "outlook_unmatched_rows.txt"
REGISTRY_JSON_PATH = ROOT / "company_registry.json"
REGISTRY_CSV_PATH = ROOT / "company_registry.csv"


EXACT_ALIASES = {
    "3ds": "Dassault Systèmes",
    "3m": "3M",
    "altairpd": "Altair",
    "american honda": "Honda",
    "american honda honda": "Honda",
    "applied_materials_hr amat": "Applied Materials",
    "ansys talent acquisition": "Ansys",
    "ametek, inc": "AMETEK",
    "ametek talent acquisition team": "AMETEK",
    "arm": "Arm",
    "amgen amgen inc": "Amgen",
    "apple worldwide recruiting": "Apple",
    "broadcom": "Broadcom",
    "brunswick workday admin": "Brunswick",
    "bosch group": "Bosch",
    "boehringer ingelheim talent acquisition team confidential boehringer ingelheim": "Boehringer Ingelheim",
    "carnegie mellon university": "Carnegie Mellon University",
    "comsol human resources": "COMSOL",
    "cmu": "Carnegie Mellon University",
    "cybercoders": "CyberCoders",
    "ey": "EY",
    "ford careers": "Ford",
    "ford motor company": "Ford",
    "form energy recruiting": "Form Energy",
    "ge": "GE",
    "ge aerospace": "GE Aerospace",
    "ge vernova": "GE Vernova",
    "gkn aerospace recruitment team": "GKN Aerospace",
    "gkn aerospace recruitment team job": "GKN Aerospace",
    "gm": "General Motors",
    "hpe": "Hewlett Packard Enterprise",
    "idaho national laboratory": "Idaho National Laboratory",
    "john deere": "John Deere",
    "john deere recruiting": "John Deere",
    "llnl": "Lawrence Livermore National Laboratory",
    "lam talent acquisition lam research": "Lam Research",
    "millerknoll": "MillerKnoll",
    "meta hi": "Meta",
    "michelin group intouch": "Michelin",
    "maxxis international usa": "Maxxis International",
    "maxxis international - usa": "Maxxis International",
    "moog": "Moog",
    "ornl": "Oak Ridge National Laboratory",
    "ornl careers": "Oak Ridge National Laboratory",
    "panthalassa": "Panthalassa",
    "nvidia": "NVIDIA",
    "owens corning talent center": "Owens Corning",
    "recent siemens": "Siemens Energy",
    "sonoco": "Sonoco",
    "sgh": "Simpson Gumpertz & Heger",
    "simpson gumpertz & heger": "Simpson Gumpertz & Heger",
    "simulIA": "Dassault Systèmes",
    "scion staffing": "Scion",
    "scout motors": "Scout Motors",
    "structural engineer at tait": "TAIT",
    "tait": "TAIT",
    "technia": "TECHNIA",
    "toyota research institute": "Toyota Research Institute",
    "tri": "Toyota Research Institute",
    "universal display corporation": "Universal Display Corporation",
    "vulcan elements": "Vulcan Elements",
    "westinghouse electric company": "Westinghouse",
    "westinghouse": "Westinghouse",
    "wilson sporting goods": "Wilson Sporting Goods",
    "workday no reply broadcom": "Broadcom",
    "wolfspeed wolfspeed": "Wolfspeed",
    "wolfspeed": "Wolfspeed",
    "zoox": "Zoox",
}


EMAIL_CANONICAL = {
    "3ds.com": "Dassault Systèmes",
    "ansys.com": "Ansys",
    "apple.com": "Apple",
    "deere.com": "John Deere",
    "ge.com": "GE",
    "generalmotors.com": "General Motors",
    "hire.lever.co": "Lever",
    "hpe.com": "Hewlett Packard Enterprise",
    "linkedin.com": "LinkedIn",
    "millerknoll.com": "MillerKnoll",
    "myworkday.com": None,
    "nvidia.com": "NVIDIA",
    "openai.com": "OpenAI",
    "panthalassa.com": "Panthalassa",
    "scionstaffing.com": "Scion",
    "scoutmotors.com": "Scout Motors",
    "smartrecruiters.com": None,
    "teamtailor-mail.com": None,
    "us.greenhouse-mail.io": None,
    "westinghouse.com": "Westinghouse",
}


GENERIC_PREFIXES = {
    "application",
    "candidate",
    "careers",
    "hiring",
    "hr",
    "job",
    "jobs",
    "mail",
    "message",
    "no",
    "notifications",
    "noreply",
    "recruiting",
    "talent",
    "team",
    "thank",
    "update",
    "welcome",
}


GENERIC_COMPANIES = {
    "linkedin",
    "workday",
    "greenhouse",
    "icims",
    "smartrecruiters",
    "jobvite",
    "lever",
    "join",
    "applicantstack",
}


ATS_VENDOR_HINTS = {
    "myworkday.com": "workday",
    "greenhouse-mail.io": "greenhouse",
    "hire.lever.co": "lever",
    "jobvite.com": "jobvite",
    "smartrecruiters.com": "smartrecruiters",
    "teamtailor-mail.com": "teamtailor",
    "join.com": "join",
    "msg.join.com": "join",
    "dayforce.com": "dayforce",
    "icims.com": "icims",
    "acquiretm.com": "acquiretm",
    "successfactors": "successfactors",
    "workablemail.com": "workable",
    "workable.com": "workable",
    "ashbyhq.com": "ashby",
    "bamboohr.com": "bamboohr",
    "adp.com": "adp",
}


VENDOR_DOMAINS = {
    "myworkday.com",
    "greenhouse-mail.io",
    "hire.lever.co",
    "jobvite.com",
    "smartrecruiters.com",
    "teamtailor-mail.com",
    "join.com",
    "msg.join.com",
    "dayforce.com",
    "icims.com",
    "acquiretm.com",
    "successfactors.com",
    "workablemail.com",
    "workable.com",
    "ashbyhq.com",
    "bamboohr.com",
    "adp.com",
    "linkedin.com",
}


NAME_CHARS = r"[A-Za-z0-9&.,'’()/ -]"


ROW_PATTERNS = [
    re.compile(rf"your application was sent to ([A-Z0-9]{NAME_CHARS}+?)\s+(?:\d{{4}}-\d{{2}}-\d{{2}}|[A-Z][a-z]{{2}}\s+\d{{2}}-\d{{2}}|\d{{1,2}}:\d{{2}}\s+[AP]M)\b", re.I),
    re.compile(rf"thank you for applying to ([A-Z0-9]{NAME_CHARS}+?)\s+-\s+", re.I),
    re.compile(rf"thank you for applying to ([A-Z0-9]{NAME_CHARS}+?)(?:,?\s+nilay|\s+\d{{4}}-\d{{2}}-\d{{2}}|\s+[A-Z][a-z]{{2}}\s+\d{{2}}-\d{{2}}|\s+\d{{1,2}}:\d{{2}}\s+[AP]M|[!.])", re.I),
    re.compile(rf"thanks? for applying to ([A-Z0-9]{NAME_CHARS}+?)(?:,?\s+nilay|\s+\d{{4}}-\d{{2}}-\d{{2}}|\s+[A-Z][a-z]{{2}}\s+\d{{2}}-\d{{2}}|\s+\d{{1,2}}:\d{{2}}\s+[AP]M|[!.])", re.I),
    re.compile(rf"thank you for applying at ([A-Z0-9]{NAME_CHARS}+?)(?:,?\s+nilay|\s+\d{{4}}-\d{{2}}-\d{{2}}|\s+[A-Z][a-z]{{2}}\s+\d{{2}}-\d{{2}}|\s+\d{{1,2}}:\d{{2}}\s+[AP]M|[!.])", re.I),
    re.compile(rf"thank you for your application to ([A-Z0-9]{NAME_CHARS}+?)\b", re.I),
    re.compile(rf"sign in and continue your application to ([A-Z0-9]{NAME_CHARS}+?)\b", re.I),
    re.compile(rf"information about your application to ([A-Z0-9]{NAME_CHARS}+?)\b", re.I),
    re.compile(rf"an update on your ([A-Z0-9]{NAME_CHARS}+?) application\b", re.I),
    re.compile(rf"update on your application to ([A-Z0-9]{NAME_CHARS}+?)\b", re.I),
    re.compile(rf"your application at ([A-Z0-9]{NAME_CHARS}+?)\b", re.I),
    re.compile(rf"thank you for your interest in ([A-Z0-9]{NAME_CHARS}+?)(?:,?\s+nilay|\s+and for applying|\s+\d{{4}}-\d{{2}}-\d{{2}}|\s+[A-Z][a-z]{{2}}\s+\d{{2}}-\d{{2}}|\s+\d{{1,2}}:\d{{2}}\s+[AP]M)\b", re.I),
    re.compile(rf"thank you for your interest in .*? at ([A-Z0-9]{NAME_CHARS}+?)\b", re.I),
    re.compile(rf"thank you for expressing interest in the .*? role at ([A-Z0-9]{NAME_CHARS}+?)\s*\(", re.I),
    re.compile(rf"thank you for your interest in the .*? position at ([A-Z0-9]{NAME_CHARS}+?)\b", re.I),
    re.compile(rf"thanks? for expressing your interest in .*? at ([A-Z0-9]{NAME_CHARS}+?)\b", re.I),
    re.compile(rf"we have received your application for .*? at ([A-Z0-9]{NAME_CHARS}+?)\b", re.I),
    re.compile(rf"we received your submission for .*? at ([A-Z0-9]{NAME_CHARS}+?)\b", re.I),
    re.compile(rf"thank you for applying for .*? at ([A-Z0-9]{NAME_CHARS}+?)\b", re.I),
    re.compile(rf"thanks for applying to the .*? at ([A-Z0-9]{NAME_CHARS}+?)!", re.I),
    re.compile(rf"thank you for applying to the .*? opening at ([A-Z0-9]{NAME_CHARS}+?)\b", re.I),
    re.compile(rf"thank you for applying to the .*? position at ([A-Z0-9]{NAME_CHARS}+?)\b", re.I),
    re.compile(rf"for the position of .*? at ([A-Z0-9]{NAME_CHARS}+?)\b", re.I),
    re.compile(rf"received your application here at ([A-Z0-9]{NAME_CHARS}+?)\b", re.I),
    re.compile(rf"([A-Z0-9]{NAME_CHARS}+?)\s+@\s+icims\b", re.I),
    re.compile(rf"dear nilay,\s+thank you very much for your recent application to ([A-Z0-9]{NAME_CHARS}+?)\s+for\b", re.I),
    re.compile(rf"application update on .*? at ([A-Z0-9]{NAME_CHARS}+?)\b", re.I),
]


def load_rows() -> list[str]:
    with ROWS_PATH.open() as f:
        data = json.load(f)
    return [str(item) for item in data if isinstance(item, str)]


def load_raw_candidates() -> list[str]:
    if not RAW_CANDIDATES_PATH.exists():
        return []
    return [line.strip() for line in RAW_CANDIDATES_PATH.read_text().splitlines() if line.strip()]


def squash_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_sender_email(row: str) -> Optional[str]:
    match = re.search(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", row)
    if not match:
        return None
    return match.group(1).lower()


def extract_sender_domain(row: str) -> Optional[str]:
    email = extract_sender_email(row)
    if not email:
        return None
    return email.split("@", 1)[1]


def classify_ats(row: str, sender_domain: Optional[str]) -> set[str]:
    hints: set[str] = set()
    text = row.lower()

    if sender_domain:
        for domain_fragment, ats_name in ATS_VENDOR_HINTS.items():
            if domain_fragment in sender_domain:
                hints.add(ats_name)

    for domain_fragment, ats_name in ATS_VENDOR_HINTS.items():
        if domain_fragment in text:
            hints.add(ats_name)

    for keyword, ats_name in {
        "workday": "workday",
        "greenhouse": "greenhouse",
        "lever": "lever",
        "jobvite": "jobvite",
        "smartrecruiters": "smartrecruiters",
        "teamtailor": "teamtailor",
        "join.com": "join",
        "dayforce": "dayforce",
        "icims": "icims",
        "successfactors": "successfactors",
        "workable": "workable",
        "ashby": "ashby",
        "bamboohr": "bamboohr",
        "adp": "adp",
    }.items():
        if keyword in text:
            hints.add(ats_name)

    return hints


def looks_like_vendor_domain(domain: str) -> bool:
    return any(fragment in domain for fragment in VENDOR_DOMAINS)


def extract_company_domains(row: str) -> set[str]:
    domains: set[str] = set()
    for match in re.finditer(r"\b([a-z0-9.-]+\.[a-z]{2,})(?:/[^\s]*)?\b", row.lower()):
        domain = match.group(1).strip(".")
        if looks_like_vendor_domain(domain):
            continue
        if domain.endswith((".png", ".jpg", ".jpeg", ".svg")):
            continue
        domains.add(domain)
    return domains


def title_word(word: str) -> str:
    if word.lower() in {"llnl", "cmu", "sgh", "tri", "hpe", "gm", "ge", "3m"}:
        return word.upper()
    if word.lower() in {"and", "of", "the", "for", "to", "at", "in"}:
        return word.lower()
    return word[:1].upper() + word[1:]


def canonicalize(name: str) -> Optional[str]:
    value = squash_ws(name).strip(" -:|,.;()[]{}")
    if not value:
        return None

    value = re.sub(r"\b(?:dear|hello|hi)\s+nilay\b.*$", "", value, flags=re.I)
    value = value.strip(" -:|,.;()[]{}")
    if not value:
        return None

    lower = value.lower()
    if "@" in value:
        return None
    if lower in EXACT_ALIASES:
        return EXACT_ALIASES[lower]

    value = re.sub(r"\s+\|\s+.*$", "", value)
    value = re.sub(
        r"\s+(talent acquisition|hiring team|recruiting team|recruitment team|worldwide recruiting|workday notifications)$",
        "",
        value,
        flags=re.I,
    )
    value = re.sub(r"\s+(careers|careerconnect|hr)$", "", value, flags=re.I)
    value = re.sub(r"\s+\(.*?\)$", "", value)
    value = squash_ws(value).strip(" -:|,.;")
    if not value:
        return None

    lower = value.lower()
    if lower in EXACT_ALIASES:
        return EXACT_ALIASES[lower]
    if lower in GENERIC_COMPANIES:
        return None
    if lower in {"the", "our", "this", "employment", "foundation", "form", "lawrence", "x"}:
        return None
    if re.search(
        r"\b(thank you|application|received|response|update|important|subject|nilay|your|dear|hello|hiring|recruiting|workday|reply|status|successfactors)\b",
        lower,
    ):
        return None

    if lower.endswith(" university"):
        return " ".join(title_word(w) for w in value.split())
    if "national laboratory" in lower:
        return " ".join(title_word(w) for w in value.split())

    words = value.split()
    if len(words) == 1:
        token = re.sub(r"[^A-Za-z0-9&+-]", "", words[0])
        if not token or token.lower() in GENERIC_PREFIXES:
            return None
        if token.lower() in EXACT_ALIASES:
            return EXACT_ALIASES[token.lower()]
        if token.isupper() or any(ch.isdigit() for ch in token):
            return token
        return token[:1].upper() + token[1:]

    cleaned = " ".join(title_word(w) for w in words)
    lower_cleaned = cleaned.lower()
    if lower_cleaned in GENERIC_COMPANIES:
        return None
    return cleaned


def extract_sender_company(row: str) -> Optional[str]:
    line = squash_ws(row)

    if "@" in line:
        m = re.search(r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", line)
        if m:
            local = m.group(1).lower()
            domain = m.group(2).lower()
            if domain in EMAIL_CANONICAL and EMAIL_CANONICAL[domain]:
                return EMAIL_CANONICAL[domain]
            if local in EXACT_ALIASES:
                return EXACT_ALIASES[local]
            for part in re.split(r"[._+-]+", local):
                if part in EXACT_ALIASES:
                    return EXACT_ALIASES[part]

    prefix = re.split(
        r"\s+(?:Thank you|Thanks for|Regarding your|Application |Application Update|Status Update|Your application|Your interest|Welcome to|Subject:|ORNL Acknowledge|Sign in and continue|Information about)",
        line,
        maxsplit=1,
        flags=re.I,
    )[0]
    prefix = prefix.split("You don't often get email", 1)[0]
    prefix = prefix.split(" Inbox", 1)[0]
    prefix = prefix.split("|", 1)[0]
    prefix = squash_ws(prefix).strip(" -:|,.;")
    if not prefix or "@" in prefix and " " not in prefix:
        return None

    if " - " in prefix:
        right = canonicalize(prefix.rsplit(" - ", 1)[-1])
        if right:
            return right

    if ":" in prefix:
        left = canonicalize(prefix.split(":", 1)[0])
        if left:
            return left

    prefix = re.sub(
        r"\s+(Talent Acquisition|Recruiting Team|Recruitment Team|Hiring Team|Worldwide Recruiting|Careers|CareerConnect|HR|Workday Notifications)$",
        "",
        prefix,
        flags=re.I,
    )
    prefix = squash_ws(prefix)
    if 1 <= len(prefix.split()) <= 6:
        return canonicalize(prefix)
    return None


def extract_candidates_from_row(row: str) -> list[str]:
    text = squash_ws(row)
    found: list[str] = []

    sender_company = extract_sender_company(text)
    if sender_company:
        found.append(sender_company)

    for pattern in ROW_PATTERNS:
        for match in pattern.finditer(text):
            candidate = canonicalize(match.group(1))
            if candidate:
                found.append(candidate)

    return found


def collect_companies(rows: list[str], raw_candidates: list[str]) -> tuple[dict[str, dict], list[str]]:
    evidence: dict[str, dict] = {}
    unmatched: list[str] = []

    def ensure(name: str) -> dict:
        if name not in evidence:
            evidence[name] = {
                "count": 0,
                "ats_hints": set(),
                "company_domains": set(),
                "examples": [],
                "sender_domains": set(),
                "sender_emails": set(),
                "sources": set(),
            }
        return evidence[name]

    for row in rows:
        sender_email = extract_sender_email(row)
        sender_domain = extract_sender_domain(row)
        ats_hints = classify_ats(row, sender_domain)
        company_domains = extract_company_domains(row)
        if sender_domain and not looks_like_vendor_domain(sender_domain):
            company_domains.add(sender_domain)

        matches = []
        for company in extract_candidates_from_row(row):
            if company and company not in GENERIC_COMPANIES:
                matches.append(company)

        seen = set(matches)
        if not seen:
            unmatched.append(row)
            continue

        for company in seen:
            item = ensure(company)
            item["count"] += 1
            item["ats_hints"].update(ats_hints)
            item["company_domains"].update(company_domains)
            if sender_domain:
                item["sender_domains"].add(sender_domain)
            if sender_email:
                item["sender_emails"].add(sender_email)
            item["sources"].add("rows")
            if len(item["examples"]) < 3:
                item["examples"].append(row[:400])

    return evidence, unmatched


def build_outputs() -> None:
    rows = load_rows()
    raw_candidates = load_raw_candidates()
    evidence, unmatched = collect_companies(rows, raw_candidates)

    ranked = sorted(
        evidence,
        key=lambda name: (-evidence[name]["count"], name.lower()),
    )
    cleaned = sorted(evidence, key=str.lower)

    OUTPUT_PATH.write_text("\n".join(cleaned) + "\n")
    UNMATCHED_PATH.write_text("\n---\n".join(unmatched) + ("\n" if unmatched else ""))

    registry_records = [
        {
            "company": name,
            "count": evidence[name]["count"],
            "ats_hints": sorted(evidence[name]["ats_hints"]),
            "company_domains": sorted(evidence[name]["company_domains"]),
            "sender_domains": sorted(evidence[name]["sender_domains"]),
            "sender_emails": sorted(evidence[name]["sender_emails"]),
            "examples": evidence[name]["examples"],
        }
        for name in cleaned
    ]

    report = {
        "rows_processed": len(rows),
        "raw_candidate_lines": len(raw_candidates),
        "unique_companies": len(cleaned),
        "companies": [
            {
                "name": name,
                "count": evidence[name]["count"],
                "ats_hints": sorted(evidence[name]["ats_hints"]),
                "company_domains": sorted(evidence[name]["company_domains"]),
                "sender_domains": sorted(evidence[name]["sender_domains"]),
                "sender_emails": sorted(evidence[name]["sender_emails"]),
                "sources": sorted(evidence[name]["sources"]),
                "examples": evidence[name]["examples"],
            }
            for name in ranked
        ],
        "unmatched_rows": unmatched[:100],
        "unmatched_count": len(unmatched),
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    REGISTRY_JSON_PATH.write_text(json.dumps(registry_records, indent=2))

    with REGISTRY_CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "company",
                "count",
                "ats_hints",
                "company_domains",
                "sender_domains",
                "sender_emails",
            ],
        )
        writer.writeheader()
        for record in registry_records:
            writer.writerow(
                {
                    "company": record["company"],
                    "count": record["count"],
                    "ats_hints": ";".join(record["ats_hints"]),
                    "company_domains": ";".join(record["company_domains"]),
                    "sender_domains": ";".join(record["sender_domains"]),
                    "sender_emails": ";".join(record["sender_emails"]),
                }
            )

    print(f"Wrote {len(cleaned)} companies to {OUTPUT_PATH}")
    print(f"Wrote report to {REPORT_PATH}")
    print(f"Wrote registry JSON to {REGISTRY_JSON_PATH}")
    print(f"Wrote registry CSV to {REGISTRY_CSV_PATH}")
    print(f"Wrote unmatched rows to {UNMATCHED_PATH}")
    print(f"Unmatched rows: {len(unmatched)}")


if __name__ == "__main__":
    build_outputs()
