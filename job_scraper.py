import csv
import inspect
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterator, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

try:
    from jobspy import scrape_jobs
except ImportError:
    scrape_jobs = None


"""
job_scraper.py
==============
Aggregates job postings across LinkedIn, AcademicJobsOnline, HigherEdJobs,
national lab portals, and more — driven by user-provided keywords.

This version keeps ONLY jobs posted within the past month where date information
is available. JobSpy uses hours_old directly. Other scrapers are filtered using
date_posted when available.

Outputs:
  job_csvs/sim_eng/sim_eng_jobs.csv
  job_chunks/sim_eng/
  empty_desc_urls.txt
"""


# ============================================================
# Configuration
# ============================================================

OUTPUT_CSV = os.environ.get("SIM_ENG_OUTPUT_CSV", "job_csvs/sim_eng/sim_eng_jobs.csv")
CHUNK_DIR = os.environ.get("SIM_ENG_CHUNK_DIR", "job_chunks/sim_eng")
CHUNK_SIZE = int(os.environ.get("SIM_ENG_CHUNK_SIZE", "5"))
EMPTY_LOG = os.environ.get("SIM_ENG_EMPTY_LOG", "empty_desc_urls.txt")

SKIP_EMPTY_DESC = os.environ.get("SIM_ENG_SKIP_EMPTY_DESC", "false").lower() == "true"
REQUEST_DELAY = float(os.environ.get("SIM_ENG_REQUEST_DELAY", "2.0"))
REQUEST_TIMEOUT = int(os.environ.get("SIM_ENG_REQUEST_TIMEOUT", "20"))

DAYS_OLD = int(os.environ.get("SIM_ENG_DAYS_OLD", "30"))
HOURS_OLD = 24 * DAYS_OLD
CUTOFF_DATE = datetime.now(timezone.utc) - timedelta(days=DAYS_OLD)

# True  = drop jobs where posting date cannot be parsed.
# False = keep jobs with unknown dates.
STRICT_POSTED_DATE_FILTER = (
    os.environ.get("SIM_ENG_STRICT_POSTED_DATE_FILTER", "true").lower() == "true"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

JOBSPY_SITES = [
    site.strip()
    for site in os.environ.get("SIM_ENG_JOBSPY_SITES", "linkedin").split(",")
    if site.strip()
]

IS_REMOTE_ONLY = os.environ.get("SIM_ENG_IS_REMOTE", "").strip().lower()  # "true"/"false"/""
JOB_TYPE = os.environ.get("SIM_ENG_JOB_TYPE", "").strip().lower()  # fulltime/parttime/contract/internship/""


# ============================================================
# Keywords — loaded from user-provided custom keywords
# ============================================================

# No hardcoded defaults — users must provide keywords via the app.
# Fallback to empty list if no custom keywords are set.
JOB_KEYWORDS: List[str] = []
TEST_KEYWORDS: List[str] = []


def parse_keyword_text(value: str) -> List[str]:
    keywords: List[str] = []
    seen = set()
    for raw_line in re.split(r"[\n,]", value or ""):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        key = line.lower()
        if key not in seen:
            keywords.append(line)
            seen.add(key)
    return keywords


def load_custom_keywords() -> List[str]:
    values: List[str] = []
    keywords_file = os.environ.get("SIM_ENG_KEYWORDS_FILE", "").strip()
    if keywords_file:
        try:
            with open(os.path.expanduser(keywords_file), encoding="utf-8") as f:
                values.extend(parse_keyword_text(f.read()))
        except OSError as exc:
            tqdm.write(f"  [keywords WARN] Could not read {keywords_file}: {exc}")

    values.extend(parse_keyword_text(os.environ.get("SIM_ENG_KEYWORDS_TEXT", "")))

    deduped: List[str] = []
    seen = set()
    for value in values:
        key = value.lower()
        if key not in seen:
            deduped.append(value)
            seen.add(key)
    return deduped


# ============================================================
# Normalized schema
# ============================================================

FIELDS = [
    "title",
    "institution",
    "location",
    "url",
    "description",
    "source",
    "date_posted",
    "scraped_at",
    "min_amount",
    "max_amount",
    "currency",
    "salary_interval",
    "job_type",
    "is_remote",
]


def empty_row() -> Dict[str, str]:
    return {f: "" for f in FIELDS}


# ============================================================
# 1. JobSpy
# ============================================================

def build_jobspy_kwargs(search_term: str, site_name: object) -> Dict[str, object]:
    """
    Pass only the kwargs supported by the installed JobSpy version.
    """

    if scrape_jobs is None:
        return {}

    desired_kwargs: Dict[str, object] = {
        "site_name": site_name,
        "search_term": search_term,
        "location": "USA",
        "results_wanted": 40,
        "hours_old": HOURS_OLD,
        "country_indeed": "USA",
        "linkedin_fetch_description": True,
        "enforce_annual_salary": True,
    }

    if IS_REMOTE_ONLY == "true":
        desired_kwargs["is_remote"] = True
    elif IS_REMOTE_ONLY == "false":
        desired_kwargs["is_remote"] = False

    if JOB_TYPE:
        desired_kwargs["job_type"] = JOB_TYPE

    signature = inspect.signature(scrape_jobs)

    if any(
        param.kind == inspect.Parameter.VAR_KEYWORD
        for param in signature.parameters.values()
    ):
        return desired_kwargs

    return {
        name: value
        for name, value in desired_kwargs.items()
        if name in signature.parameters
    }

def scrape_jobspy(keywords: List[str]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []

    if scrape_jobs is None:
        tqdm.write("  [jobspy SKIP] python-jobspy is not installed.")
        return rows

    pbar = tqdm(keywords, desc="jobspy", unit="kw", colour="cyan")

    for kw in pbar:
        pbar.set_postfix_str(kw[:45])

        for site in JOBSPY_SITES:
            try:
                jobs = scrape_jobs(**build_jobspy_kwargs(kw, [site]))

                if jobs is None or jobs.empty:
                    continue

                for _, r in jobs.iterrows():
                    desc = r.get("description", "")

                    if desc is None or (isinstance(desc, float) and math.isnan(desc)):
                        desc = ""

                    row = empty_row()
                    row["title"] = str(r.get("title", "") or "")
                    row["institution"] = str(r.get("company", "") or "")
                    row["location"] = str(r.get("location", "") or "")
                    row["description"] = str(desc)
                    row["url"] = str(r.get("job_url") or r.get("job_url_direct") or "")
                    row["source"] = f"jobspy/{site}"
                    row["date_posted"] = str(r.get("date_posted", "") or "")
                    row["scraped_at"] = datetime.now(timezone.utc).isoformat()
                    # Salary and job-type fields (only populated by JobSpy)
                    row["min_amount"] = str(r.get("min_amount", "") or "")
                    row["max_amount"] = str(r.get("max_amount", "") or "")
                    row["currency"] = str(r.get("currency", "") or "")
                    row["salary_interval"] = str(r.get("interval", "") or r.get("salary_interval", "") or "")
                    row["job_type"] = str(r.get("job_type", "") or "")
                    row["is_remote"] = str(r.get("is_remote", "") or "")

                    rows.append(row)

            except Exception as e:
                tqdm.write(f"  [jobspy WARN] {kw} | {site}: {e}")

        pbar.set_postfix_str(f"{kw[:30]} | total: {len(rows)}")

        time.sleep(REQUEST_DELAY)

    return rows


# ============================================================
# 2. AcademicJobsOnline
# ============================================================

def scrape_ajo(keywords: List[str]) -> List[Dict[str, str]]:
    ajo_keywords = [
        kw
        for kw in keywords
        if any(
            t in kw
            for t in [
                "research scientist",
                "staff scientist",
                "computational",
                "machine learning",
                "scientific",
                "mechanics",
            ]
        )
    ]

    rows: List[Dict[str, str]] = []
    seen: set = set()

    pbar = tqdm(ajo_keywords, desc="AcademicJobsOnline", unit="kw", colour="green")

    for kw in pbar:
        pbar.set_postfix_str(kw[:45])

        try:
            resp = requests.get(
                "https://academicjobsonline.org/ajo/jobs",
                params={"q": kw, "type": "r"},
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")

            for tr in soup.select("tr.jobtablerow, tr[class*='job']"):
                a_tag = tr.select_one("a[href*='/ajo/jobs/']")

                if not a_tag:
                    continue

                href = a_tag.get("href", "")

                if not href.startswith("http"):
                    href = "https://academicjobsonline.org" + href

                if href in seen:
                    continue

                seen.add(href)

                title = a_tag.get_text(strip=True)
                cells = tr.find_all("td")

                inst = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                loc = cells[2].get_text(strip=True) if len(cells) > 2 else ""

                row = empty_row()
                row["title"] = title
                row["institution"] = inst
                row["location"] = loc
                row["url"] = href
                row["source"] = "academicjobsonline"
                row["date_posted"] = ""
                row["scraped_at"] = datetime.now(timezone.utc).isoformat()

                rows.append(row)

        except Exception as e:
            tqdm.write(f"  [AJO ERROR] {kw}: {e}")

        time.sleep(REQUEST_DELAY)

    return rows


# ============================================================
# 3. HigherEdJobs
# ============================================================

def scrape_higheredjobs(keywords: List[str]) -> List[Dict[str, str]]:
    hej_keywords = [
        kw
        for kw in keywords
        if any(
            t in kw
            for t in [
                "research scientist",
                "computational",
                "machine learning",
                "scientific",
                "mechanics",
            ]
        )
    ]

    rows: List[Dict[str, str]] = []
    seen: set = set()

    pbar = tqdm(hej_keywords, desc="HigherEdJobs", unit="kw", colour="yellow")

    for kw in pbar:
        pbar.set_postfix_str(kw[:45])

        try:
            resp = requests.get(
                "https://www.higheredjobs.com/search/advanced_action.cfm",
                params={"PosType": "2", "Keyword": kw, "NumJobs": "50"},
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")

            for item in soup.select(".record-row, tr.row-striped"):
                a_tag = (
                    item.select_one("a[href*='/faculty/']")
                    or item.select_one("a[href*='/research/']")
                    or item.select_one("a[href*='/jobs/']")
                )

                if not a_tag:
                    continue

                href = a_tag.get("href", "")

                if not href.startswith("http"):
                    href = "https://www.higheredjobs.com" + href

                if href in seen:
                    continue

                seen.add(href)

                inst_tag = item.select_one(".col-inst, .institution")
                loc_tag = item.select_one(".col-location, .location")
                date_tag = item.select_one(".col-date, .date, .posted")

                row = empty_row()
                row["title"] = a_tag.get_text(strip=True)
                row["institution"] = inst_tag.get_text(strip=True) if inst_tag else ""
                row["location"] = loc_tag.get_text(strip=True) if loc_tag else ""
                row["url"] = href
                row["source"] = "higheredjobs"
                row["date_posted"] = date_tag.get_text(strip=True) if date_tag else ""
                row["scraped_at"] = datetime.now(timezone.utc).isoformat()

                rows.append(row)

        except Exception as e:
            tqdm.write(f"  [HigherEdJobs ERROR] {kw}: {e}")

        time.sleep(REQUEST_DELAY)

    return rows


# ============================================================
# 4. Workday national lab portals
# ============================================================

WORKDAY_LABS = [
    ("ORNL", "ornl.wd1.myworkdayjobs.com", "ORNL/OakRidge_Careers"),
    ("LBNL", "lbl.wd1.myworkdayjobs.com", "LBL/LBNL_Career"),
    ("NREL", "nrel.wd5.myworkdayjobs.com", "NREL/NREL"),
    ("ANL", "anl.wd1.myworkdayjobs.com", "ANL/argonne"),
    ("SLAC", "slac.wd1.myworkdayjobs.com", "SLAC/SLAC"),
    ("Sandia", "sandia.wd1.myworkdayjobs.com", "Sandia/Sandia_Careers"),
    ("BNL", "bnl.wd1.myworkdayjobs.com", "BNL/BNL_Careers"),
]


def scrape_workday_lab(display_name: str, host: str, site_path: str, queries: List[str] = None) -> List[Dict[str, str]]:
    if not queries:
        return []
    rows: List[Dict[str, str]] = []
    seen: set = set()

    api_url = f"https://{host}/wday/cxs/{site_path}/jobs"
    portal_url = f"https://{host}"

    # Establish a session with cookies first — Workday's CXS API requires
    # a valid session cookie and CSRF token set by the initial page load.
    session = requests.Session()
    try:
        session.get(portal_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    except Exception:
        pass  # proceed anyway; some labs don't need it

    post_headers = {
        **HEADERS,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": portal_url,
        "Referer": portal_url + "/",
    }

    for q in tqdm(
        queries,
        desc=f"  {display_name}",
        unit="q",
        leave=False,
        colour="magenta",
    ):
        try:
            resp = session.post(
                api_url,
                json={
                    "appliedFacets": {},
                    "limit": 20,
                    "offset": 0,
                    "searchText": q,
                },
                headers=post_headers,
                timeout=REQUEST_TIMEOUT,
            )

            resp.raise_for_status()
            data = resp.json()

            for j in data.get("jobPostings", []):
                ext_path = j.get("externalPath", "")
                full_url = f"https://{host}{ext_path}" if ext_path else ""

                if full_url in seen:
                    continue

                seen.add(full_url)

                row = empty_row()
                row["title"] = j.get("title", "")
                row["institution"] = display_name
                row["location"] = j.get("locationsText", "") or j.get("primaryLocation", "")
                row["description"] = j.get("briefDesc", "")
                row["url"] = full_url
                row["source"] = f"workday/{display_name.lower()}"
                row["date_posted"] = str(
                    j.get("postedOn", "")
                    or j.get("startDate", "")
                    or j.get("postedDate", "")
                    or j.get("externalPostedDate", "")
                    or ""
                )
                row["scraped_at"] = datetime.now(timezone.utc).isoformat()

                rows.append(row)

        except Exception as e:
            tqdm.write(f"  [Workday/{display_name} ERROR] {q}: {e}")

        time.sleep(REQUEST_DELAY)

    return rows


def scrape_all_workday_labs(queries: List[str] = None) -> List[Dict[str, str]]:
    if not queries:
        return []
    rows: List[Dict[str, str]] = []

    for display_name, host, site_path in tqdm(
        WORKDAY_LABS,
        desc="Workday labs",
        unit="lab",
        colour="magenta",
    ):
        result = scrape_workday_lab(display_name, host, site_path, queries=queries)
        rows.extend(result)
        tqdm.write(f"  {display_name}: {len(result)} jobs")

    return rows


# ============================================================
# 5. PNNL
# ============================================================

def scrape_pnnl(queries: List[str] = None) -> List[Dict[str, str]]:
    if not queries:
        return []
    rows: List[Dict[str, str]] = []

    for q in tqdm(queries, desc="PNNL", unit="q", colour="blue"):
        try:
            resp = requests.get(
                "https://jobs.pnnl.gov/jobs/search",
                params={"q": q},
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")

            for a in soup.select("a.job-listing-title, .job-title a, h2 a"):
                href = a.get("href", "")

                if not href.startswith("http"):
                    href = "https://jobs.pnnl.gov" + href

                row = empty_row()
                row["title"] = a.get_text(strip=True)
                row["institution"] = "PNNL"
                row["url"] = href
                row["source"] = "pnnl"
                row["date_posted"] = ""
                row["scraped_at"] = datetime.now(timezone.utc).isoformat()

                rows.append(row)

        except Exception as e:
            tqdm.write(f"  [PNNL ERROR] {q}: {e}")

        time.sleep(REQUEST_DELAY)

    return rows


# ============================================================
# 6. LANL
# ============================================================

def scrape_lanl(queries: List[str] = None) -> List[Dict[str, str]]:
    """LANL careers via lanl.jobs (iCIMS-based search)."""
    if not queries:
        return []
    rows: List[Dict[str, str]] = []
    seen: set = set()

    for q in tqdm(queries, desc="LANL", unit="q", colour="blue", leave=False):
        try:
            resp = requests.get(
                "https://lanl.jobs/search-jobs/",
                params={"q": q},
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for a in soup.select("a[data-job-id], .job-title a, h2 a, .title a"):
                href = a.get("href", "")
                if not href:
                    continue
                if not href.startswith("http"):
                    href = "https://lanl.jobs" + href
                if href in seen:
                    continue
                seen.add(href)
                row = empty_row()
                row["title"] = a.get_text(strip=True)
                row["institution"] = "LANL"
                row["url"] = href
                row["source"] = "lanl"
                row["scraped_at"] = datetime.now(timezone.utc).isoformat()
                rows.append(row)

        except Exception as e:
            tqdm.write(f"  [LANL ERROR] {q}: {e}")
        time.sleep(REQUEST_DELAY)

    return rows


# ============================================================
# 7. Fermilab
# ============================================================

def scrape_fermilab(queries: List[str] = None) -> List[Dict[str, str]]:
    """Fermilab careers via fermilab.jobs (iCIMS-based search)."""
    if not queries:
        return []
    rows: List[Dict[str, str]] = []
    seen: set = set()

    for q in tqdm(queries, desc="Fermilab", unit="q", colour="blue", leave=False):
        try:
            resp = requests.get(
                "https://fermilab.jobs/search-jobs/",
                params={"q": q},
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for a in soup.select("a[data-job-id], .job-title a, h2 a, .title a"):
                href = a.get("href", "")
                if not href:
                    continue
                if not href.startswith("http"):
                    href = "https://fermilab.jobs" + href
                if href in seen:
                    continue
                seen.add(href)
                row = empty_row()
                row["title"] = a.get_text(strip=True)
                row["institution"] = "Fermilab"
                row["url"] = href
                row["source"] = "fermilab"
                row["scraped_at"] = datetime.now(timezone.utc).isoformat()
                rows.append(row)

        except Exception as e:
            tqdm.write(f"  [Fermilab ERROR] {q}: {e}")
        time.sleep(REQUEST_DELAY)

    return rows


# ============================================================
# Utilities
# ============================================================

def normalize_url(url: str) -> str:
    text = str(url).strip()

    if not text:
        return ""

    parts = urlsplit(text)
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in {"ref", "referer", "source"}
    ]

    normalized = urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            urlencode(filtered_query, doseq=True),
            "",
        )
    )

    return normalized.lower()


def normalize_text(value: str) -> str:
    text = str(value).lower().strip()
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def make_identity_key(row: Dict[str, str]) -> str:
    return "|".join(
        [
            normalize_text(row.get("title", "")),
            normalize_text(row.get("institution", "")),
            normalize_text(row.get("location", "")),
        ]
    )


def row_quality(row: Dict[str, str]) -> Tuple[int, int, int]:
    return (
        1 if row.get("description", "").strip() else 0,
        1 if row.get("date_posted", "").strip() else 0,
        len(row.get("url", "").strip()),
    )


def merge_rows(existing: Dict[str, str], incoming: Dict[str, str]) -> Dict[str, str]:
    merged = dict(existing)

    for field in FIELDS:
        if not merged.get(field, "").strip() and incoming.get(field, "").strip():
            merged[field] = incoming[field]

    if row_quality(incoming) > row_quality(existing):
        for field in ["description", "date_posted", "url", "source", "scraped_at"]:
            if incoming.get(field, "").strip():
                merged[field] = incoming[field]

    return merged


def deduplicate(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    url_index: Dict[str, int] = {}
    identity_index: Dict[str, int] = {}
    unique: List[Dict[str, str]] = []

    for r in rows:
        url_key = normalize_url(r.get("url", ""))
        identity_key = make_identity_key(r)

        existing_idx = None

        if url_key and url_key in url_index:
            existing_idx = url_index[url_key]
        elif identity_key and identity_key in identity_index:
            existing_idx = identity_index[identity_key]

        if existing_idx is None:
            unique.append(r)
            new_idx = len(unique) - 1

            if url_key:
                url_index[url_key] = new_idx
            if identity_key:
                identity_index[identity_key] = new_idx
            continue

        merged = merge_rows(unique[existing_idx], r)
        unique[existing_idx] = merged

        merged_url_key = normalize_url(merged.get("url", ""))
        merged_identity_key = make_identity_key(merged)

        if merged_url_key:
            url_index[merged_url_key] = existing_idx
        if merged_identity_key:
            identity_index[merged_identity_key] = existing_idx

    return unique


def parse_posted_date(value: object) -> Optional[datetime]:
    """
    Parse common posting-date formats into a timezone-aware datetime.
    Handles:
      - actual dates
      - today / yesterday
      - 3 days ago / 2 weeks ago / 1 month ago
    """

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

    m = re.search(r"(\d+)\s*\+?\s*(hour|day|week|month)s?\s+ago", text)

    if m:
        n = int(m.group(1))
        unit = m.group(2)

        if unit == "hour":
            return now - timedelta(hours=n)
        if unit == "day":
            return now - timedelta(days=n)
        if unit == "week":
            return now - timedelta(weeks=n)
        if unit == "month":
            return now - timedelta(days=30 * n)

    try:
        dt = pd.to_datetime(value, errors="coerce", utc=True)

        if pd.isna(dt):
            return None

        return dt.to_pydatetime()
    except Exception:
        return None


def filter_recent(rows: List[Dict[str, str]]) -> Tuple[List[Dict[str, str]], int]:
    recent = []

    for r in rows:
        dt = parse_posted_date(r.get("date_posted", ""))

        if dt is None:
            if not STRICT_POSTED_DATE_FILTER:
                recent.append(r)
            continue

        if dt >= CUTOFF_DATE:
            recent.append(r)

    return recent, len(rows) - len(recent)


# ============================================================
# Visa / clearance filter
# ============================================================

EXCLUSION_PHRASES: List[str] = [
    "us citizen",
    "u.s. citizen",
    "united states citizen",
    "must be a citizen",
    "citizenship required",
    "citizenship is required",
    "only us citizens",
    "only u.s. citizens",
    "american citizen",
    "security clearance",
    "secret clearance",
    "top secret",
    "ts/sci",
    "ts sci",
    "dod clearance",
    "dod secret",
    "government clearance",
    "active clearance",
    "clearance required",
    "clearance eligible",
    "obtain a clearance",
    "hold a clearance",
    "itar",
    "itar restricted",
    "itar compliant",
    "itar requirements",
    "export control",
    "export controlled",
    "ear controlled",
    "permanent resident",
    "green card",
    "lawful permanent",
    "u.s. permanent",
]


def is_restricted(row: Dict[str, str]) -> bool:
    haystack = " ".join([row.get("title", ""), row.get("description", "")]).lower()
    return any(phrase in haystack for phrase in EXCLUSION_PHRASES)


def filter_restricted(rows: List[Dict[str, str]]) -> Tuple[List[Dict[str, str]], int]:
    clean = [r for r in rows if not is_restricted(r)]
    return clean, len(rows) - len(clean)


def chunked(items: List[Dict[str, str]], size: int) -> Iterator[List[Dict[str, str]]]:
    chunk: List[Dict[str, str]] = []

    for item in items:
        chunk.append(item)

        if len(chunk) == size:
            yield chunk
            chunk = []

    if chunk:
        yield chunk


def write_chunk(path: str, rows: List[Dict[str, str]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for i, row in enumerate(rows, 1):
            f.write(f"Job {i}\n")
            f.write(f"Title:       {row.get('title', '')}\n")
            f.write(f"Institution: {row.get('institution', '')}\n")
            f.write(f"Location:    {row.get('location', '')}\n")
            f.write(f"Source:      {row.get('source', '')}\n")
            f.write(f"Posted:      {row.get('date_posted', '')}\n")
            f.write(f"URL:         {row.get('url', '')}\n")
            f.write("Description:\n")
            f.write(row.get("description", "") or "(fetch from URL)")
            f.write("\n\n" + ("-" * 80) + "\n\n")


def save_results(rows: List[Dict[str, str]], empty_urls: List[str]) -> None:
    if SKIP_EMPTY_DESC:
        filtered = []

        for r in rows:
            if not r.get("description", "").strip():
                u = r.get("url", "")
                if u:
                    empty_urls.append(u)
            else:
                filtered.append(r)

        rows = filtered

    df = pd.DataFrame(rows, columns=FIELDS)

    output_dir = os.path.dirname(OUTPUT_CSV)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    df.to_csv(
        OUTPUT_CSV,
        quoting=csv.QUOTE_NONNUMERIC,
        escapechar="\\",
        index=False,
    )

    tqdm.write(f"\nSaved {len(rows)} jobs -> {OUTPUT_CSV}")

    os.makedirs(CHUNK_DIR, exist_ok=True)

    for name in os.listdir(CHUNK_DIR):
        if name.startswith("jobs_") and name.endswith(".txt"):
            os.remove(os.path.join(CHUNK_DIR, name))

    for idx, chunk in enumerate(chunked(rows, CHUNK_SIZE), 1):
        write_chunk(os.path.join(CHUNK_DIR, f"jobs_{idx:04d}.txt"), chunk)

    n_chunks = math.ceil(len(rows) / CHUNK_SIZE) if rows else 0
    tqdm.write(f"Text chunks -> {CHUNK_DIR}/  ({n_chunks} files)")


def print_source_summary(rows: List[Dict[str, str]]) -> None:
    counts: Dict[str, int] = {}

    for r in rows:
        src = r.get("source", "unknown")
        counts[src] = counts.get(src, 0) + 1

    tqdm.write("\nSource breakdown:")

    for src, n in sorted(counts.items(), key=lambda x: -x[1]):
        tqdm.write(f"  {src:<35} {n}")


def get_keywords(default_mode: str = "custom") -> List[str]:
    mode = os.environ.get("SIM_ENG_KEYWORDS", default_mode).lower()
    custom_keywords = load_custom_keywords()
    if custom_keywords:
        return custom_keywords
    if mode == "test":
        return TEST_KEYWORDS
    if JOB_KEYWORDS:
        return JOB_KEYWORDS
    tqdm.write("  [keywords WARN] No keywords found. Add keywords in the app before running a search.")
    return []


# ============================================================
# Main
# ============================================================

def main() -> None:
    all_rows: List[Dict[str, str]] = []
    empty_urls: List[str] = []
    keywords = get_keywords()

    # Use first 10 keywords as search queries for secondary scrapers
    queries = keywords[:10] if keywords else []

    sources = [
        (
            "jobspy  (LinkedIn / Indeed / Glassdoor / ZipRecruiter)",
            lambda: scrape_jobspy(keywords),
        ),
        (
            "AcademicJobsOnline",
            lambda: scrape_ajo(keywords),
        ),
        (
            "HigherEdJobs",
            lambda: scrape_higheredjobs(keywords),
        ),
        ("Workday portals", lambda: scrape_all_workday_labs(queries)),
        ("PNNL", lambda: scrape_pnnl(queries)),
        ("LANL", lambda: scrape_lanl(queries)),
        ("Fermilab", lambda: scrape_fermilab(queries)),
    ]

    overall = tqdm(sources, desc="Overall", unit="source", colour="white")

    for label, fn in overall:
        overall.set_postfix_str(label[:50])
        tqdm.write(f"\n{'=' * 60}\n{label}\n{'=' * 60}")

        result = fn()
        all_rows.extend(result)

        tqdm.write(f"  -> {len(result)} jobs collected; running total: {len(all_rows)}")

    tqdm.write(f"\nRaw total before dedup: {len(all_rows)}")

    all_rows = deduplicate(all_rows)
    tqdm.write(f"After dedup:            {len(all_rows)}")

    all_rows, n_old = filter_recent(all_rows)
    tqdm.write(
        f"After date filter:      {len(all_rows)}  "
        f"({n_old} older/unknown-date removed; cutoff={CUTOFF_DATE.date()})"
    )

    all_rows, n_filtered = filter_restricted(all_rows)
    tqdm.write(f"After clearance filter: {len(all_rows)}  ({n_filtered} removed)")

    print_source_summary(all_rows)
    save_results(all_rows, empty_urls)

    if empty_urls:
        with open(EMPTY_LOG, "w", encoding="utf-8") as f:
            for u in empty_urls:
                f.write(u + "\n")

        tqdm.write(f"\nEmpty-desc URLs -> {EMPTY_LOG}  ({len(empty_urls)} entries)")

    tqdm.write("\nDone.")


if __name__ == "__main__":
    main()
