import csv
import html
import json
import math
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

import clean_outlook_companies as company_cleaner
from job_scraper import get_keywords


ROOT = Path(os.environ.get("SIM_ENG_PROJECT_ROOT", "/Users/nilay/Documents/New project")).expanduser()
RAW_REGISTRY_PATH = ROOT / "company_registry.json"
CLEAN_REGISTRY_JSON = ROOT / "company_registry_cleaned.json"
CLEAN_REGISTRY_CSV = ROOT / "company_registry_cleaned.csv"
CLEAN_COMPANY_LIST = ROOT / "company_registry_cleaned.txt"
OUTPUT_CSV = ROOT / os.environ.get(
    "SIM_ENG_CAREER_OUTPUT_CSV",
    "job_csvs/sim_eng/sim_eng_company_jobs.csv",
)
CHUNK_DIR = ROOT / os.environ.get(
    "SIM_ENG_CAREER_CHUNK_DIR",
    "job_chunks/sim_eng_company",
)
CHUNK_SIZE = int(os.environ.get("SIM_ENG_CAREER_CHUNK_SIZE", "5"))
SKIPPED_LOG = ROOT / os.environ.get(
    "SIM_ENG_CAREER_SKIPPED_LOG",
    "company_career_skips.txt",
)

REQUEST_TIMEOUT = int(os.environ.get("SIM_ENG_REQUEST_TIMEOUT", "10"))
REQUEST_DELAY = float(os.environ.get("SIM_ENG_REQUEST_DELAY", "0.2"))
DAYS_OLD = int(os.environ.get("SIM_ENG_DAYS_OLD", "30"))
CUTOFF_DATE = datetime.now(timezone.utc) - timedelta(days=DAYS_OLD)
MAX_COMPANIES = int(os.environ.get("SIM_ENG_MAX_COMPANIES", "0"))
ENABLE_SEARCH_FALLBACK = (
    os.environ.get("SIM_ENG_SEARCH_FALLBACK", "true").lower() == "true"
)
PERSONAL_DOMAINS = {
    value.strip().lower()
    for value in os.environ.get("SIM_ENG_PERSONAL_DOMAINS", "psu.edu").split(",")
    if value.strip()
}

KEYWORDS = get_keywords()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

FIELDS = [
    "title",
    "institution",
    "location",
    "url",
    "description",
    "source",
    "date_posted",
    "scraped_at",
    "career_page",
    "ats_platform",
]

NOISE_NAME_PATTERNS = [
    r"\bthank you\b",
    r"\bapplication\b",
    r"\bapplications?\b",
    r"\bposition\b",
    r"\brole\b",
    r"\bjob\b",
    r"\bjobs\b",
    r"\bupdate\b",
    r"\bnotification\b",
    r"\bnotifications\b",
    r"\bsubject\b",
    r"\brecent\b",
    r"\brecruiting\b",
    r"\btalent acquisition\b",
    r"\bhiring team\b",
    r"\bhuman resources\b",
    r"\bcareerconnect\b",
    r"\bworkday\b",
    r"\bresume\b",
    r"\bdear\b",
    r"\bhello\b",
    r"\bnilay\b",
]

SEARCH_RESULT_BLOCKLIST = (
    "linkedin.com",
    "indeed.com",
    "glassdoor.com",
    "ziprecruiter.com",
    "jobspy",
    "greenhouse-mail.io",
)

NON_JOB_TITLE_PATTERNS = [
    r"^careers\b",
    r"^apply now\b",
    r"^find your perfect role\b",
    r"^join us\b",
    r"^posting locations\b",
    r"^total rewards\b",
    r"^prospective employee\b",
    r"^career resources\b",
    r"^living in\b",
    r"^statement of assurance\b",
    r"^temporary employment\b",
    r"^benefits\b",
]

NON_TARGET_TITLE_PATTERNS = [
    r"\b(hr|human resources)\b",
    r"\bsales\b",
    r"\bsourcing\b",
    r"\bsupply chain\b",
    r"\btechnician\b",
    r"\boperator\b",
    r"\bprogram manager\b",
    r"\bdirector\b",
    r"\bchief of staff\b",
    r"\bintern\b",
]

def _load_user_signal_terms():
    """Build relevance signal terms from user keywords at runtime."""
    kw_file = os.environ.get("SIM_ENG_KEYWORDS_FILE", "").strip()
    keywords = []
    if kw_file:
        try:
            import re as _re
            raw = open(kw_file, encoding="utf-8").read()
            for line in raw.splitlines():
                line = line.split("#")[0].strip()
                if line:
                    keywords.append(line.lower())
        except Exception:
            pass
    # Extract individual meaningful words from keywords (2+ chars, non-stopword)
    stopwords = {"a","an","the","and","or","for","of","in","at","to","with","by"}
    tokens = set()
    for kw in keywords:
        for word in kw.split():
            if len(word) > 2 and word not in stopwords:
                tokens.add(word)
    # Full phrases as strong signals, individual words as support/title signals
    strong = keywords[:20] if keywords else []
    support = list(tokens)[:20] if tokens else []
    return strong, support, support

_STRONG, _SUPPORT, _TITLE = _load_user_signal_terms()
STRONG_SIGNAL_TERMS = _STRONG
SUPPORT_SIGNAL_TERMS = _SUPPORT
TITLE_SIGNAL_TERMS = _TITLE

US_STATE_TOKENS = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
    "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
    "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
    "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
    "wi", "wy", "dc",
}

NON_US_COUNTRY_TOKENS = {
    "au", "be", "br", "ca", "ch", "cn", "de", "dk", "es", "fr", "gb", "hk",
    "ie", "il", "in", "it", "jp", "kr", "mx", "my", "nl", "nz", "pl", "se",
    "sg", "th", "tr", "tw", "uk",
}

ATS_HOST_PATTERNS = {
    "greenhouse": ("boards.greenhouse.io", "job-boards.greenhouse.io"),
    "lever": ("jobs.lever.co",),
    "smartrecruiters": ("jobs.smartrecruiters.com", "api.smartrecruiters.com"),
    "workday": ("myworkdayjobs.com",),
    "icims": ("icims.com",),
    "jobvite": ("jobs.jobvite.com", "jobs-legacy.jobvite.com"),
    "teamtailor": ("teamtailor.com",),
    "ashby": ("jobs.ashbyhq.com",),
    "workable": ("apply.workable.com", "jobs.workable.com"),
    "successfactors": ("successfactors.com", "successfactors.eu", "sapsf.com"),
    "join": ("join.com",),
    "bamboohr": ("bamboohr.com",),
    "adp": ("adp.com",),
}

COMPANY_DOMAIN_OVERRIDES = {
    "Carnegie Mellon University": ["cmu.edu"],
    "Lawrence Livermore National Laboratory": ["llnl.gov"],
    "Oak Ridge National Laboratory": ["ornl.gov"],
    "Toyota Research Institute": ["tri.global"],
    "Zoox": ["zoox.com"],
}

CAREER_URL_OVERRIDES = {
    "Carnegie Mellon University": ["https://cmu.wd5.myworkdayjobs.com/CMU"],
    "Toyota Research Institute": ["https://www.tri.global/careers"],
    "Zoox": ["https://zoox.com/careers"],
}

DIRECT_NAME_FIXES = {
    "a message from altair": "Altair",
    "joining the lam research talent community": "Lam Research",
    "3ds talent acquisition 3ds": "Dassault Systèmes",
    "ansys talent acquisition ansys job": "Ansys",
    "the recruiting team at meta": "Meta",
    "siemens p&o talent acquisition": "Siemens Energy",
    "apple worldwide recruiting": "Apple",
    "actalent actalent": "Actalent",
    "assa abloy candidate": "ASSA ABLOY",
    "lam": "Lam Research",
    "kla": "KLA",
    "lucidmotors": "Lucid Motors",
    "no-reply": "",
    "workable": "",
    "the sr": "",
}

GENERIC_ROLE_NAME_WORDS = {
    "analyst",
    "cae",
    "design",
    "engineer",
    "fea",
    "lead",
    "manager",
    "mechanical",
    "modeling",
    "r",
    "research",
    "simulation",
    "specialist",
    "staff",
    "stress",
    "structural",
}

BLOCKED_COMPANY_NAMES = {
    "applytojob",
    "itsjnj",
    "jobgether",
    "lever",
    "one",
    "stand",
    "stand insurance",
    "",
}


def empty_row() -> Dict[str, str]:
    return {field: "" for field in FIELDS}


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def slug_words(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def registrable_domain(domain: str) -> str:
    domain = domain.lower().strip(".")
    parts = domain.split(".")
    if len(parts) <= 2:
        return domain
    if ".".join(parts[-2:]) in {"co.uk", "com.au", "org.au"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def looks_like_personal_domain(domain: str) -> bool:
    return registrable_domain(domain) in PERSONAL_DOMAINS


def valid_company_name(name: str) -> bool:
    lower = name.lower()
    if not name:
        return False
    if re.search(r"\d{4}-\d{2}-\d{2}", name):
        return False
    if any(re.search(pattern, lower) for pattern in NOISE_NAME_PATTERNS):
        return False
    if re.fullmatch(r"(manager|engineer|scientist|analyst|specialist)", lower):
        return False
    if lower.startswith(("our ", "the ")) and " at " not in lower and "laboratory" not in lower:
        return False
    if len(name.split()) > 8:
        return False
    return True


def looks_like_generic_role_name(name: str) -> bool:
    tokens = [token for token in normalize_key(name).split() if token]
    return bool(tokens) and all(token in GENERIC_ROLE_NAME_WORDS for token in tokens)


def clean_candidate_name(value: str) -> Optional[str]:
    value = normalize_space(value).strip(" -:|,.;")
    if not value:
        return None

    if " - " in value:
        left, right = value.split(" - ", 1)
        if re.search(r"\b(engineer|scientist|manager|analyst|specialist|role|opening|position|fea|cae)\b", right, re.I):
            candidate = clean_candidate_name(left)
            if candidate:
                return candidate

    at_match = re.search(r"\bat\s+([A-Za-z0-9&.,'’()/ -]+)$", value, flags=re.I)
    if at_match:
        candidate = clean_candidate_name(at_match.group(1))
        if candidate:
            return candidate

    lower = value.lower()
    if lower in DIRECT_NAME_FIXES:
        return DIRECT_NAME_FIXES[lower]

    value = re.sub(r"^our\s+", "", value, flags=re.I)
    value = re.sub(r"^the\s+", "", value, flags=re.I)
    value = re.sub(r"^a message from\s+", "", value, flags=re.I)
    value = re.sub(r"^joining the\s+", "", value, flags=re.I)
    value = re.sub(r"^the recruiting team at\s+", "", value, flags=re.I)
    value = re.sub(r"^notification for\s+", "", value, flags=re.I)
    value = re.sub(r"^recent\s+", "", value, flags=re.I)
    value = re.sub(r"^human resources\s+", "", value, flags=re.I)
    value = re.sub(r"^workday[_ ]no.?reply\s+", "", value, flags=re.I)
    value = re.sub(r"^workday[_ ]notification[s]?\s+", "", value, flags=re.I)
    value = re.sub(r"\s+talent acquisition.*$", "", value, flags=re.I)
    value = re.sub(r"\s+recruiting team.*$", "", value, flags=re.I)
    value = re.sub(r"\s+hiring team.*$", "", value, flags=re.I)
    value = re.sub(r"\s+worldwide recruiting.*$", "", value, flags=re.I)
    value = re.sub(r"\s+human resources.*$", "", value, flags=re.I)
    value = re.sub(r"\s+careers?.*$", "", value, flags=re.I)
    value = re.sub(r"\s+job$", "", value, flags=re.I)
    value = normalize_space(value).strip(" -:|,.;")
    if not value:
        return None

    lower = value.lower()
    if lower in DIRECT_NAME_FIXES:
        return DIRECT_NAME_FIXES[lower]

    cleaned = company_cleaner.canonicalize(value)
    if cleaned:
        value = cleaned
    if looks_like_generic_role_name(value):
        return None
    return value if valid_company_name(value) else None


def parse_posted_date(value: object) -> Optional[datetime]:
    if value is None:
        return None

    text = str(value).strip().lower()
    if not text or text in {"nan", "none", "null"}:
        return None

    now = datetime.now(timezone.utc)
    if text in {"today", "just posted", "new"}:
        return now
    if text == "yesterday":
        return now - timedelta(days=1)

    match = re.search(r"(\d+)\s*(\+)?\s*(hour|day|week|month)s?\s+ago", text)
    if match:
        amount = int(match.group(1))
        if match.group(2):
            amount += 1
        unit = match.group(3)
        if unit == "hour":
            return now - timedelta(hours=amount)
        if unit == "day":
            return now - timedelta(days=amount)
        if unit == "week":
            return now - timedelta(weeks=amount)
        if unit == "month":
            return now - timedelta(days=30 * amount)

    iso = text.replace("z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%a %m-%d",
        "%a %Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(str(value).strip(), fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


def recent_enough(value: object) -> bool:
    dt = parse_posted_date(value)
    return bool(dt and dt >= CUTOFF_DATE)


def text_from_html(value: str) -> str:
    soup = BeautifulSoup(value or "", "html.parser")
    return normalize_space(soup.get_text(" ", strip=True))


def keyword_match(title: str, description: str) -> bool:
    title_key = normalize_key(title)
    description_key = normalize_key(description)
    haystack = normalize_key(f"{title} {description}")

    if any(normalize_key(keyword) in haystack for keyword in KEYWORDS):
        return True
    strong_hits = sum(1 for term in STRONG_SIGNAL_TERMS if normalize_key(term) in haystack)
    if strong_hits >= 1:
        return True

    title_hits = sum(1 for term in TITLE_SIGNAL_TERMS if normalize_key(term) in title_key)
    description_support_hits = sum(
        1 for term in SUPPORT_SIGNAL_TERMS if normalize_key(term) in description_key
    )
    return title_hits >= 1 and description_support_hits >= 2


def looks_like_job_title(title: str) -> bool:
    cleaned = normalize_space(title)
    if not cleaned:
        return False
    lower = cleaned.lower()
    if any(re.search(pattern, lower) for pattern in NON_JOB_TITLE_PATTERNS):
        return False
    if any(re.search(pattern, lower) for pattern in NON_TARGET_TITLE_PATTERNS):
        return False
    if not any(
        token in lower
        for token in ("engineer", "scientist", "researcher", "developer", "analyst", "manager", "specialist")
    ):
        return False
    return True


def location_allowed(location: str) -> bool:
    cleaned = normalize_key(location)
    if not cleaned:
        return True
    if "remote" in cleaned:
        return True
    tokens = cleaned.split()
    if "united states" in cleaned or (tokens and tokens[-1] in {"us", "usa"}):
        return True
    if tokens and tokens[-1] in NON_US_COUNTRY_TOKENS:
        return False
    if "," in location and tokens and tokens[-1] in US_STATE_TOKENS:
        return True
    return len(tokens) >= 2 and tokens[-1] in US_STATE_TOKENS and tokens[-2] not in NON_US_COUNTRY_TOKENS


def sender_local_tokens(email: str) -> List[str]:
    local = email.split("@", 1)[0].lower()
    tokens = []
    for part in re.split(r"[._+-]+", local):
        part = part.strip()
        if not part or part in {"no", "reply", "noreply", "email", "autoreply", "notification", "notifications"}:
            continue
        if re.fullmatch(r"[a-z]\d+", part):
            continue
        tokens.append(part)
    return tokens


def company_candidates_from_record(record: dict) -> Counter:
    counter: Counter = Counter()

    original = clean_candidate_name(record["company"])
    if original:
        counter[original] += 2

    for example in record.get("examples", []):
        for candidate in company_cleaner.extract_candidates_from_row(example):
            candidate = clean_candidate_name(candidate)
            if candidate:
                counter[candidate] += 5

    for email in record.get("sender_emails", []):
        local, _, domain = email.partition("@")
        root = registrable_domain(domain)
        if looks_like_personal_domain(root):
            continue
        if company_cleaner.looks_like_vendor_domain(root):
            for token in sender_local_tokens(email):
                local_candidate = clean_candidate_name(token)
                if local_candidate:
                    counter[local_candidate] += 3
        else:
            domain_candidate = clean_candidate_name(root.split(".")[0])
            if domain_candidate:
                counter[domain_candidate] += 3

    for domain in record.get("company_domains", []):
        root = registrable_domain(domain)
        if looks_like_personal_domain(root):
            continue
        if company_cleaner.looks_like_vendor_domain(root):
            continue
        domain_candidate = clean_candidate_name(root.split(".")[0])
        if domain_candidate:
            counter[domain_candidate] += 3

    return counter


def cleaned_domains(record: dict) -> List[str]:
    domains: Set[str] = set()

    for domain in record.get("company_domains", []):
        root = registrable_domain(domain)
        if root.endswith((".pdf", ".png", ".jpg", ".jpeg", ".svg")):
            continue
        if looks_like_personal_domain(root):
            continue
        if not company_cleaner.looks_like_vendor_domain(root):
            domains.add(root)

    for email in record.get("sender_emails", []):
        _, _, domain = email.partition("@")
        root = registrable_domain(domain)
        if looks_like_personal_domain(root):
            continue
        if not company_cleaner.looks_like_vendor_domain(root):
            domains.add(root)

    return sorted(domains)


def cleaned_ats_hints(record: dict) -> List[str]:
    return sorted(set(record.get("ats_hints", [])))


def merge_registry(raw_registry: Sequence[dict]) -> List[dict]:
    merged: dict[str, dict] = {}

    for record in raw_registry:
        candidates = company_candidates_from_record(record)
        if candidates:
            company = sorted(
                candidates.items(),
                key=lambda item: (-item[1], len(item[0]), item[0].lower()),
            )[0][0]
        else:
            company = clean_candidate_name(record["company"])

        if not company or not valid_company_name(company) or looks_like_generic_role_name(company):
            continue

        if company not in merged:
            merged[company] = {
                "company": company,
                "aliases": set(),
                "ats_hints": set(),
                "company_domains": set(),
                "sender_domains": set(),
                "sender_emails": set(),
                "examples": [],
                "count": 0,
            }

        item = merged[company]
        item["count"] += int(record.get("count", 0))
        item["aliases"].add(record["company"])
        item["ats_hints"].update(record.get("ats_hints", []))
        item["company_domains"].update(cleaned_domains(record))
        item["sender_domains"].update(
            registrable_domain(domain)
            for domain in record.get("sender_domains", [])
            if domain
        )
        item["sender_emails"].update(record.get("sender_emails", []))
        for example in record.get("examples", []):
            if example not in item["examples"] and len(item["examples"]) < 5:
                item["examples"].append(example)

    for company, domains in COMPANY_DOMAIN_OVERRIDES.items():
        if company in merged:
            merged[company]["company_domains"].update(domains)

    clean_records = []
    for company in sorted(merged, key=str.lower):
        item = merged[company]
        clean_records.append(
            {
                "company": company,
                "count": item["count"],
                "aliases": sorted(item["aliases"]),
                "ats_hints": sorted(item["ats_hints"]),
                "company_domains": sorted(item["company_domains"]),
                "sender_domains": sorted(item["sender_domains"]),
                "sender_emails": sorted(item["sender_emails"]),
                "examples": item["examples"],
            }
        )

    return clean_records


def write_clean_registry(records: Sequence[dict]) -> None:
    CLEAN_REGISTRY_JSON.write_text(json.dumps(records, indent=2))
    CLEAN_COMPANY_LIST.write_text("\n".join(record["company"] for record in records) + "\n")

    with CLEAN_REGISTRY_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "company",
                "count",
                "ats_hints",
                "company_domains",
                "sender_domains",
                "sender_emails",
                "aliases",
            ],
        )
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "company": record["company"],
                    "count": record["count"],
                    "ats_hints": ";".join(record["ats_hints"]),
                    "company_domains": ";".join(record["company_domains"]),
                    "sender_domains": ";".join(record["sender_domains"]),
                    "sender_emails": ";".join(record["sender_emails"]),
                    "aliases": ";".join(record["aliases"]),
                }
            )


def record_priority(record: dict) -> int:
    score = int(record.get("count", 0))
    if record.get("ats_hints"):
        score += 3
    if record.get("company_domains"):
        score += 2
    for example in record.get("examples", []):
        if keyword_match(record["company"], example):
            score += 5
    return score


def load_clean_registry() -> List[dict]:
    raw_registry = json.loads(RAW_REGISTRY_PATH.read_text())
    records = [
        record
        for record in merge_registry(raw_registry)
        if normalize_key(record["company"]) not in BLOCKED_COMPANY_NAMES
    ]
    write_clean_registry(records)
    if MAX_COMPANIES > 0:
        return sorted(records, key=lambda item: (-record_priority(item), item["company"].lower()))[:MAX_COMPANIES]
    return records


def candidate_domain_guesses(record: dict) -> List[str]:
    guesses: Set[str] = set(record.get("company_domains", []))
    guesses.update(COMPANY_DOMAIN_OVERRIDES.get(record["company"], []))

    for email in record.get("sender_emails", []):
        local, _, domain = email.partition("@")
        if domain.endswith("myworkday.com"):
            manual = {
                "cmu": "cmu.edu",
                "llnl": "llnl.gov",
                "ornl": "ornl.gov",
                "lbl": "lbl.gov",
            }.get(local)
            if manual:
                guesses.add(manual)
            elif re.fullmatch(r"[a-z0-9-]{3,}", local):
                guesses.add(f"{local}.com")

    company_slug = slug_words(record["company"])
    joined_slug = slugify(record["company"])
    if company_slug:
        guesses.add(f"{company_slug}.com")
    if joined_slug and joined_slug != company_slug.replace("-", ""):
        guesses.add(f"{joined_slug}.com")

    return sorted(guesses)


def candidate_board_urls(record: dict) -> List[str]:
    urls: Set[str] = set(CAREER_URL_OVERRIDES.get(record["company"], []))
    domains = candidate_domain_guesses(record)

    for domain in domains:
        urls.add(f"https://{domain}/careers")
        urls.add(f"https://{domain}/jobs")
        urls.add(f"https://{domain}")

    slug_variants = {
        slug_words(record["company"]),
        slugify(record["company"]),
    }
    for alias in record.get("aliases", []):
        slug_variants.add(slug_words(alias))
        slug_variants.add(slugify(alias))
    for email in record.get("sender_emails", []):
        local = email.split("@", 1)[0]
        slug_variants.add(local.lower())

    slugs = sorted(slug for slug in slug_variants if slug)

    for ats_hint in record.get("ats_hints", []):
        for slug in slugs:
            if ats_hint == "greenhouse":
                urls.add(f"https://boards.greenhouse.io/{slug}")
                urls.add(f"https://job-boards.greenhouse.io/{slug}")
            elif ats_hint == "lever":
                urls.add(f"https://jobs.lever.co/{slug}")
            elif ats_hint == "smartrecruiters":
                urls.add(f"https://jobs.smartrecruiters.com/{slug}")
            elif ats_hint == "icims":
                urls.add(f"https://jobs-{slug}.icims.com/jobs/search?ss=1")
                urls.add(f"https://careers-{slug}.icims.com/jobs/search?ss=1")
            elif ats_hint == "jobvite":
                urls.add(f"https://jobs.jobvite.com/{slug}")
            elif ats_hint == "teamtailor":
                urls.add(f"https://{slug}.teamtailor.com/jobs")
            elif ats_hint == "ashby":
                urls.add(f"https://jobs.ashbyhq.com/{slug}")
            elif ats_hint == "workable":
                urls.add(f"https://apply.workable.com/{slug}")

    return [url for url in sorted(urls) if url]


def board_type_for_url(url: str) -> Optional[str]:
    host = urlparse(url).netloc.lower()
    for board_type, patterns in ATS_HOST_PATTERNS.items():
        if any(pattern in host for pattern in patterns):
            return board_type
    return None


def clean_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(fragment="", query="").geturl().rstrip("/")


def is_asset_url(url: str) -> bool:
    lower = url.lower()
    return lower.endswith((".pdf", ".png", ".jpg", ".jpeg", ".svg", ".mp4", ".webm", ".gif"))


def useful_generic_url(url: str) -> bool:
    if is_asset_url(url):
        return False

    path = urlparse(url).path.lower()
    if "/details/" in path:
        return True
    if "/search" in path or "/jobs" in path or "/job/" in path or "/position" in path or "/opening" in path:
        return True
    if path.rstrip("/") in {"/career", "/careers", "/careers/us", "/careers/us/index"}:
        return True
    return False


def looks_like_job_detail_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(
        token in path
        for token in ("/job/", "/jobs/", "/details/", "/opening/", "/position/")
    )


def session_get(session: requests.Session, url: str, **kwargs) -> Optional[requests.Response]:
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True, **kwargs)
        resp.raise_for_status()
        return resp
    except Exception:
        return None


def session_post(session: requests.Session, url: str, **kwargs) -> Optional[requests.Response]:
    try:
        resp = session.post(url, timeout=REQUEST_TIMEOUT, allow_redirects=True, **kwargs)
        resp.raise_for_status()
        return resp
    except Exception:
        return None


def discover_links_from_page(session: requests.Session, url: str) -> Set[str]:
    resp = session_get(session, url, headers=HEADERS)
    if not resp:
        return set()

    soup = BeautifulSoup(resp.text, "html.parser")
    found: Set[str] = set()

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        if not href or href.startswith(("mailto:", "javascript:", "#")):
            continue
        absolute = urljoin(resp.url, href)
        absolute = clean_url(absolute)
        lower = absolute.lower()
        if any(pattern in lower for pattern in SEARCH_RESULT_BLOCKLIST):
            continue
        if is_asset_url(absolute):
            continue
        if board_type_for_url(absolute):
            found.add(absolute)
            continue
        text = normalize_space(anchor.get_text(" ", strip=True)).lower()
        if useful_generic_url(absolute):
            found.add(absolute)
        elif useful_generic_url(absolute) and any(
            token in text for token in ("careers", "career", "jobs", "job openings")
        ):
            found.add(absolute)

    return found


def search_queries_for_record(record: dict) -> List[str]:
    company = record["company"]
    queries = [f"\"{company}\" careers jobs"]

    for domain in candidate_domain_guesses(record)[:2]:
        queries.append(f"site:{domain} {company} careers")

    ats_queries = {
        "workday": f"site:myworkdayjobs.com \"{company}\"",
        "greenhouse": f"site:greenhouse.io \"{company}\" jobs",
        "lever": f"site:lever.co \"{company}\" jobs",
        "smartrecruiters": f"site:smartrecruiters.com \"{company}\" jobs",
        "icims": f"site:icims.com \"{company}\" jobs",
        "jobvite": f"site:jobvite.com \"{company}\" jobs",
        "teamtailor": f"site:teamtailor.com \"{company}\" jobs",
        "ashby": f"site:ashbyhq.com \"{company}\" jobs",
        "workable": f"site:workable.com \"{company}\" jobs",
        "successfactors": f"site:successfactors.com \"{company}\" jobs",
        "join": f"site:join.com \"{company}\" jobs",
        "bamboohr": f"site:bamboohr.com \"{company}\" jobs",
        "adp": f"site:adp.com \"{company}\" jobs",
    }

    for ats_hint in record.get("ats_hints", []):
        query = ats_queries.get(ats_hint)
        if query:
            queries.append(query)

    return list(dict.fromkeys(queries))


def search_career_urls(session: requests.Session, record: dict) -> Set[str]:
    if not ENABLE_SEARCH_FALLBACK:
        return set()

    found: Set[str] = set()

    for query in search_queries_for_record(record):
        resp = session_get(
            session,
            "https://duckduckgo.com/html/",
            params={"q": query},
            headers=HEADERS,
        )
        if not resp:
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        for anchor in soup.select("a[href]"):
            href = anchor.get("href", "").strip()
            if not href:
                continue

            if "/l/?" in href:
                parsed = urlparse(href)
                qs = parse_qs(parsed.query)
                if "uddg" in qs:
                    href = unquote(qs["uddg"][0])

            if not href.startswith("http"):
                continue
            lower = href.lower()
            if any(blocked in lower for blocked in SEARCH_RESULT_BLOCKLIST):
                continue
            if any(token in lower for token in ("/careers", "/career", "/jobs", "/job", "/details/")) or board_type_for_url(href):
                found.add(clean_url(href))
            if len(found) >= 10:
                break
        if len(found) >= 10:
            break

    return found


def company_discovery_urls(session: requests.Session, record: dict) -> List[str]:
    found: Set[str] = set(candidate_board_urls(record))
    known_domains = {registrable_domain(domain) for domain in candidate_domain_guesses(record)}

    crawl_budget = 0
    for seed in list(found):
        if board_type_for_url(seed):
            continue
        if crawl_budget >= 3:
            break
        found.update(discover_links_from_page(session, seed))
        crawl_budget += 1
        time.sleep(REQUEST_DELAY)

    if record.get("ats_hints") or not any(board_type_for_url(url) for url in found):
        found.update(search_career_urls(session, record))

    filtered = set()
    for url in found:
        board_type = board_type_for_url(url)
        root = registrable_domain(urlparse(url).netloc)
        if board_type:
            filtered.add(url)
        elif useful_generic_url(url) and (not known_domains or root in known_domains):
            filtered.add(url)

    return sorted(filtered)


def build_row(
    company: str,
    title: str,
    location: str,
    url: str,
    description: str,
    source: str,
    date_posted: object,
    career_page: str,
    ats_platform: str,
) -> Dict[str, str]:
    row = empty_row()
    row["title"] = normalize_space(title)
    row["institution"] = company
    row["location"] = normalize_space(location)
    row["url"] = clean_url(url)
    row["description"] = normalize_space(description)
    row["source"] = source
    row["date_posted"] = str(date_posted or "")
    row["scraped_at"] = datetime.now(timezone.utc).isoformat()
    row["career_page"] = career_page
    row["ats_platform"] = ats_platform
    return row


def scrape_greenhouse(session: requests.Session, company: str, board_url: str) -> List[Dict[str, str]]:
    match = re.search(r"greenhouse\.io/([^/?#]+)", board_url)
    if not match:
        return []
    token = match.group(1)
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    resp = session_get(session, api_url, headers=HEADERS)
    if not resp:
        return []
    data = resp.json()
    rows = []
    for job in data.get("jobs", []):
        description = text_from_html(job.get("content", ""))
        row = build_row(
            company=company,
            title=job.get("title", ""),
            location=(job.get("location") or {}).get("name", ""),
            url=job.get("absolute_url", board_url),
            description=description,
            source="career/greenhouse",
            date_posted=job.get("updated_at") or job.get("created_at"),
            career_page=board_url,
            ats_platform="greenhouse",
        )
        rows.append(row)
    return rows


def scrape_lever(session: requests.Session, company: str, board_url: str) -> List[Dict[str, str]]:
    match = re.search(r"jobs\.lever\.co/([^/?#]+)", board_url)
    if not match:
        return []
    token = match.group(1)
    api_url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    resp = session_get(session, api_url, headers=HEADERS)
    if not resp:
        return []
    data = resp.json()
    rows = []
    for job in data:
        desc_parts = [
            job.get("descriptionPlain", ""),
            job.get("additionalPlain", ""),
            job.get("lists", ""),
        ]
        description = normalize_space(" ".join(part for part in desc_parts if part))
        created = job.get("createdAt")
        if created:
            created = datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat()
        row = build_row(
            company=company,
            title=job.get("text", ""),
            location=((job.get("categories") or {}).get("location", "")),
            url=job.get("hostedUrl", board_url),
            description=description,
            source="career/lever",
            date_posted=created,
            career_page=board_url,
            ats_platform="lever",
        )
        rows.append(row)
    return rows


def scrape_smartrecruiters(session: requests.Session, company: str, board_url: str) -> List[Dict[str, str]]:
    match = re.search(r"smartrecruiters\.com/([^/?#]+)", board_url)
    if not match:
        return []
    token = match.group(1)
    api_url = f"https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100&offset=0"
    resp = session_get(session, api_url, headers=HEADERS)
    if not resp:
        return []
    data = resp.json()
    rows = []
    for job in data.get("content", []):
        detail_url = f"https://api.smartrecruiters.com/v1/companies/{token}/postings/{job['id']}"
        detail_resp = session_get(session, detail_url, headers=HEADERS)
        description = ""
        if detail_resp:
            detail = detail_resp.json()
            sections = ((detail.get("jobAd") or {}).get("sections") or {})
            description = normalize_space(
                " ".join(text_from_html(section.get("text", "")) for section in sections.values())
            )
        row = build_row(
            company=company,
            title=job.get("name", ""),
            location=normalize_space(
                " ".join(
                    part
                    for part in [
                        ((job.get("location") or {}).get("city") or ""),
                        ((job.get("location") or {}).get("region") or ""),
                        ((job.get("location") or {}).get("country") or ""),
                    ]
                    if part
                )
            ),
            url=job.get("ref", board_url),
            description=description,
            source="career/smartrecruiters",
            date_posted=job.get("releasedDate"),
            career_page=board_url,
            ats_platform="smartrecruiters",
        )
        rows.append(row)
    return rows


def workday_api_urls(board_url: str) -> List[str]:
    parsed = urlparse(board_url)
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return []

    candidates = []
    if "job" in parts:
        job_index = parts.index("job")
        prefixes = [parts[:job_index]]
    else:
        prefixes = [parts]

    locale_pattern = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")
    expanded = []
    for prefix in prefixes:
        expanded.append(prefix)
        if prefix and locale_pattern.match(prefix[0]):
            expanded.append(prefix[1:])

    for prefix in expanded:
        if not prefix:
            continue
        site_path = "/".join(prefix)
        candidates.append(f"{parsed.scheme}://{parsed.netloc}/wday/cxs/{site_path}/jobs")

    return sorted(set(candidates))


def scrape_workday(session: requests.Session, company: str, board_url: str) -> List[Dict[str, str]]:
    rows = []
    for api_url in workday_api_urls(board_url):
        offset = 0
        seen_urls: Set[str] = set()
        while True:
            resp = session_post(
                session,
                api_url,
                headers={**HEADERS, "Content-Type": "application/json", "Accept": "application/json"},
                json={
                    "appliedFacets": {},
                    "limit": 20,
                    "offset": offset,
                    "searchText": "",
                },
            )
            if not resp:
                break
            data = resp.json()
            postings = data.get("jobPostings", [])
            if not postings:
                break
            for job in postings:
                ext_path = job.get("externalPath", "")
                job_url = urljoin(board_url, ext_path) if ext_path else board_url
                if job_url in seen_urls:
                    continue
                seen_urls.add(job_url)
                row = build_row(
                    company=company,
                    title=job.get("title", ""),
                    location=job.get("locationsText", "") or job.get("primaryLocation", ""),
                    url=job_url,
                    description=job.get("briefDesc", ""),
                    source="career/workday",
                    date_posted=(
                        job.get("postedOn")
                        or job.get("startDate")
                        or job.get("postedDate")
                        or job.get("externalPostedDate")
                    ),
                    career_page=board_url,
                    ats_platform="workday",
                )
                rows.append(row)
            offset += 20
    return rows


def extract_jobposting_jsonld(soup: BeautifulSoup) -> List[dict]:
    postings = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            raw = script.string or script.get_text()
            data = json.loads(raw)
        except Exception:
            continue

        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("@type") == "JobPosting":
                postings.append(item)
            elif isinstance(item.get("@graph"), list):
                for graph_item in item["@graph"]:
                    if isinstance(graph_item, dict) and graph_item.get("@type") == "JobPosting":
                        postings.append(graph_item)
    return postings


def extract_visible_posted_date(text: str) -> str:
    normalized = normalize_space(text)
    patterns = [
        r"posted on\s+(posted\s+\d+\+?\s+(?:hours?|days?|weeks?|months?)\s+ago)",
        r"posted\s+(\d+\+?\s+(?:hours?|days?|weeks?|months?)\s+ago)",
        r"date posted\s+([A-Z][a-z]+ \d{1,2}, \d{4})",
        r"posted on\s+([A-Z][a-z]+ \d{1,2}, \d{4})",
        r"posted on\s+(\d{4}-\d{2}-\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, re.I)
        if match:
            return match.group(1)
    return ""


def scrape_generic_job_page(session: requests.Session, company: str, job_url: str, career_page: str) -> Optional[Dict[str, str]]:
    resp = session_get(session, job_url, headers=HEADERS)
    if not resp:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    jsonld = extract_jobposting_jsonld(soup)
    if jsonld:
        job = jsonld[0]
        location = ""
        job_location = job.get("jobLocation")
        if isinstance(job_location, dict):
            address = job_location.get("address") or {}
            location = normalize_space(
                " ".join(
                    str(address.get(key, ""))
                    for key in ("addressLocality", "addressRegion", "addressCountry")
                    if address.get(key)
                )
            )
        description = text_from_html(job.get("description", ""))
        return build_row(
            company=company,
            title=job.get("title", ""),
            location=location,
            url=job_url,
            description=description,
            source="career/generic",
            date_posted=job.get("datePosted", ""),
            career_page=career_page,
            ats_platform=board_type_for_url(job_url) or "generic",
        )

    title = ""
    if soup.find("h1"):
        title = normalize_space(soup.find("h1").get_text(" ", strip=True))
    main_node = soup.find("main") or soup.body or soup
    description = text_from_html(str(main_node))
    page_text = normalize_space(main_node.get_text(" ", strip=True))
    date_posted = ""
    meta = soup.find("meta", attrs={"property": "article:published_time"}) or soup.find(
        "meta", attrs={"name": "date"}
    )
    if meta and meta.get("content"):
        date_posted = meta["content"]
    if not date_posted:
        date_posted = extract_visible_posted_date(page_text)
    if not title:
        title = normalize_space(soup.title.get_text(" ", strip=True) if soup.title else "")
    if not title:
        return None
    return build_row(
        company=company,
        title=title,
        location="",
        url=job_url,
        description=description,
        source="career/generic",
        date_posted=date_posted,
        career_page=career_page,
        ats_platform=board_type_for_url(job_url) or "generic",
    )


def scrape_generic_board(session: requests.Session, company: str, board_url: str) -> List[Dict[str, str]]:
    resp = session_get(session, board_url, headers=HEADERS)
    if not resp:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    rows = []

    jsonld = extract_jobposting_jsonld(soup)
    if jsonld:
        for job in jsonld:
            description = text_from_html(job.get("description", ""))
            location = ""
            job_location = job.get("jobLocation")
            if isinstance(job_location, dict):
                address = job_location.get("address") or {}
                location = normalize_space(
                    " ".join(
                        str(address.get(key, ""))
                        for key in ("addressLocality", "addressRegion", "addressCountry")
                        if address.get(key)
                    )
                )
            rows.append(
                build_row(
                    company=company,
                    title=job.get("title", ""),
                    location=location,
                    url=job.get("url", board_url),
                    description=description,
                    source="career/generic",
                    date_posted=job.get("datePosted", ""),
                    career_page=board_url,
                    ats_platform=board_type_for_url(board_url) or "generic",
                )
            )
        return rows

    job_links: Set[str] = set()
    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        text = normalize_space(anchor.get_text(" ", strip=True))
        if not href or len(text) < 4:
            continue
        absolute = clean_url(urljoin(resp.url, href))
        lower = absolute.lower()
        if lower == clean_url(board_url):
            continue
        if useful_generic_url(absolute):
            if not keyword_match(text, text) and len(text.split()) > 8:
                continue
            job_links.add(absolute)

    for job_url in sorted(job_links)[:10]:
        row = scrape_generic_job_page(session, company, job_url, board_url)
        if row:
            rows.append(row)
        time.sleep(REQUEST_DELAY)

    return rows


def scrape_company(session: requests.Session, record: dict) -> Tuple[List[Dict[str, str]], List[str]]:
    rows: List[Dict[str, str]] = []
    skips: List[str] = []
    seen_boards: Set[str] = set()

    for url in company_discovery_urls(session, record):
        board_url = clean_url(url)
        if board_url in seen_boards:
            continue
        seen_boards.add(board_url)

        board_type = board_type_for_url(board_url)
        try:
            if board_type == "greenhouse":
                rows.extend(scrape_greenhouse(session, record["company"], board_url))
            elif board_type == "lever":
                rows.extend(scrape_lever(session, record["company"], board_url))
            elif board_type == "smartrecruiters":
                rows.extend(scrape_smartrecruiters(session, record["company"], board_url))
            elif board_type == "workday":
                scraped = scrape_workday(session, record["company"], board_url)
                if scraped:
                    rows.extend(scraped)
                elif looks_like_job_detail_url(board_url):
                    row = scrape_generic_job_page(session, record["company"], board_url, board_url)
                    if row:
                        rows.append(row)
            elif board_type in {
                "icims",
                "jobvite",
                "teamtailor",
                "ashby",
                "workable",
                "successfactors",
                "join",
                "bamboohr",
                "adp",
            }:
                if looks_like_job_detail_url(board_url):
                    row = scrape_generic_job_page(session, record["company"], board_url, board_url)
                    if row:
                        rows.append(row)
                    else:
                        rows.extend(scrape_generic_board(session, record["company"], board_url))
                else:
                    rows.extend(scrape_generic_board(session, record["company"], board_url))
            elif looks_like_job_detail_url(board_url):
                row = scrape_generic_job_page(session, record["company"], board_url, board_url)
                if row:
                    rows.append(row)
            else:
                rows.extend(scrape_generic_board(session, record["company"], board_url))
        except Exception as exc:
            skips.append(f"{record['company']}\t{board_url}\t{exc}")

        time.sleep(REQUEST_DELAY)

    if not rows and not skips:
        skips.append(f"{record['company']}\tNO_RESULTS")
    return rows, skips


def score_row(row: Dict[str, str]) -> Tuple[int, int, int]:
    description_len = len(row.get("description", ""))
    has_date = 1 if row.get("date_posted") else 0
    has_url = 1 if row.get("url") else 0
    return (description_len, has_date, has_url)


def dedupe_rows(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    best_by_key: Dict[Tuple[str, str, str, str], Dict[str, str]] = {}

    for row in rows:
        url_key = clean_url(row.get("url", "")) if row.get("url") else ""
        key = (
            normalize_key(row.get("title", "")),
            normalize_key(row.get("institution", "")),
            normalize_key(row.get("location", "")),
            url_key,
        )

        if key not in best_by_key or score_row(row) > score_row(best_by_key[key]):
            best_by_key[key] = row

    second_pass: Dict[Tuple[str, str, str], Dict[str, str]] = {}
    for row in best_by_key.values():
        key = (
            normalize_key(row.get("title", "")),
            normalize_key(row.get("institution", "")),
            normalize_key(row.get("location", "")),
        )
        if key not in second_pass or score_row(row) > score_row(second_pass[key]):
            second_pass[key] = row

    return sorted(
        second_pass.values(),
        key=lambda row: (
            row.get("institution", "").lower(),
            row.get("title", "").lower(),
            row.get("location", "").lower(),
        ),
    )


def filter_rows(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    filtered = []
    for row in rows:
        if not looks_like_job_title(row.get("title", "")):
            continue
        if not location_allowed(row.get("location", "")):
            continue
        if not keyword_match(row.get("title", ""), row.get("description", "")):
            continue
        if not recent_enough(row.get("date_posted", "")):
            continue
        filtered.append(row)
    return filtered


def chunked(items: Sequence[Dict[str, str]], size: int) -> Iterable[List[Dict[str, str]]]:
    chunk: List[Dict[str, str]] = []
    for item in items:
        chunk.append(item)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def write_chunk(path: Path, rows: Sequence[Dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for index, row in enumerate(rows, start=1):
            f.write(f"Job {index}\n")
            f.write(f"Title:       {row.get('title', '')}\n")
            f.write(f"Institution: {row.get('institution', '')}\n")
            f.write(f"Location:    {row.get('location', '')}\n")
            f.write(f"Source:      {row.get('source', '')}\n")
            f.write(f"Posted:      {row.get('date_posted', '')}\n")
            f.write(f"Career Page: {row.get('career_page', '')}\n")
            f.write(f"ATS:         {row.get('ats_platform', '')}\n")
            f.write(f"URL:         {row.get('url', '')}\n")
            f.write("Description:\n")
            f.write(row.get("description", "") or "(no description)")
            f.write("\n\n" + ("-" * 80) + "\n\n")


def save_results(rows: Sequence[Dict[str, str]], skips: Sequence[str]) -> None:
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    CHUNK_DIR.mkdir(parents=True, exist_ok=True)

    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, quoting=csv.QUOTE_NONNUMERIC)
        writer.writeheader()
        writer.writerows(rows)

    for name in CHUNK_DIR.iterdir():
        if name.name.startswith("jobs_") and name.suffix == ".txt":
            name.unlink()

    for index, chunk in enumerate(chunked(rows, CHUNK_SIZE), start=1):
        write_chunk(CHUNK_DIR / f"jobs_{index:04d}.txt", chunk)

    SKIPPED_LOG.write_text("\n".join(skips) + ("\n" if skips else ""))


def main() -> None:
    records = load_clean_registry()
    session = requests.Session()
    session.headers.update(HEADERS)

    all_rows: List[Dict[str, str]] = []
    all_skips: List[str] = []

    progress = tqdm(records, desc="Companies", unit="company", colour="cyan")
    for record in progress:
        progress.set_postfix_str(record["company"][:40])
        rows, skips = scrape_company(session, record)
        all_rows.extend(rows)
        all_skips.extend(skips)

    filtered = filter_rows(all_rows)
    deduped = dedupe_rows(filtered)
    save_results(deduped, all_skips)

    tqdm.write(f"Clean registry:        {len(records)} companies")
    tqdm.write(f"Raw scraped jobs:      {len(all_rows)}")
    tqdm.write(f"Keyword + date filter: {len(filtered)}")
    tqdm.write(f"After dedupe:          {len(deduped)}")
    tqdm.write(f"CSV -> {OUTPUT_CSV}")
    tqdm.write(f"Chunks -> {CHUNK_DIR}")
    tqdm.write(f"Skips -> {SKIPPED_LOG}")


if __name__ == "__main__":
    main()
