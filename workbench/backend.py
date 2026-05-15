import base64
import io
import json
import os
import re
import requests
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

import sim_eng_ai as ai

# ── AI provider state ─────────────────────────────────────────────────────────
_PROVIDER: str = "gemini"
_AI_MODEL: str = ""
_AI_KEY: str = ""

_PROVIDER_MODEL_FALLBACKS: Dict[str, List[str]] = {
    "openai": ["gpt-4o-mini", "gpt-4o"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash"],
    "anthropic": ["claude-haiku-4-5-20251001", "claude-sonnet-4-5-20250929"],
    "mistral": ["mistral-small-latest", "mistral-medium-latest", "mistral-large-latest"],
    "cohere": ["command-r", "command-r-plus"],
}

_OPENAI_NON_TEXT_TERMS = (
    "audio", "dall", "embedding", "image", "moderation", "realtime",
    "search", "speech", "tts", "transcribe", "translation", "whisper",
)

# ── Live search state (single-user local app) ─────────────────────────────────
_STATE: dict = {
    "phase": "idle", "progress": 0, "message": "Ready",
    "log": "", "result": None, "jobs_found": 0, "start_time": None,
}
_LOCK = threading.Lock()


def get_state() -> dict:
    with _LOCK:
        return dict(_STATE)


def _model_options(model_ids: List[str]) -> List[dict]:
    seen = []
    for model_id in model_ids:
        if model_id and model_id not in seen:
            seen.append(model_id)
    return [{"label": model_id, "value": model_id} for model_id in seen]


def default_ai_model_options(provider: str = "") -> List[dict]:
    return _model_options(_PROVIDER_MODEL_FALLBACKS.get(provider or "gemini", []))


def _is_openai_text_model(model_id: str) -> bool:
    low = model_id.lower()
    if any(term in low for term in _OPENAI_NON_TEXT_TERMS):
        return False
    return low.startswith(("gpt-", "o1", "o3", "o4", "o5"))


def list_ai_models(provider: str = "", api_key: str = "") -> List[dict]:
    provider = (provider or _PROVIDER or "gemini").lower()
    if provider != "openai":
        return default_ai_model_options(provider)
    key = (api_key or _AI_KEY or "").strip()
    if not key:
        raise ValueError("Enter an OpenAI API key first.")
    response = requests.get(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=30,
    )
    if response.status_code == 401:
        raise ValueError("OpenAI rejected this API key.")
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message")
        except Exception:
            detail = response.text[:300]
        raise ValueError(detail or f"OpenAI returned HTTP {response.status_code}.")
    models = sorted(
        response.json().get("data", []),
        key=lambda item: int(item.get("created") or 0),
        reverse=True,
    )
    model_ids = [item.get("id", "") for item in models]
    text_models = [model_id for model_id in model_ids if _is_openai_text_model(model_id)]
    return _model_options(text_models[:10] or _PROVIDER_MODEL_FALLBACKS["openai"])


def _parse_progress(line: str, n: int) -> tuple:
    low = line.lower()
    # track running job count from jobspy "total: N" lines
    m_total = re.search(r"total:\s*(\d+)", low)
    if m_total:
        with _LOCK:
            _STATE["jobs_found"] = max(_STATE.get("jobs_found", 0), int(m_total.group(1)))
    if "linkedin" in low and ("search" in low or "scrape" in low or "finished" in low):
        return max(10, min(30, n)), "Searching LinkedIn…"
    if "indeed" in low:
        return max(30, min(45, n)), "Searching Indeed…"
    if "glassdoor" in low:
        return max(45, min(57, n)), "Searching Glassdoor…"
    if "ziprecruiter" in low or "zip_recruiter" in low:
        return max(57, min(65, n)), "Searching ZipRecruiter…"
    if "google" in low:
        return max(65, min(72, n)), "Searching Google Jobs…"
    if "dedup" in low or "duplicate" in low:
        return 80, "Removing duplicates…"
    if "saving" in low or "writing" in low or ".csv" in low:
        return 90, "Saving results…"
    if "scoring" in low or "ai" in low:
        return 95, "Scoring with AI…"
    return min(72, 8 + n // 3), f"Searching… ({n} steps)"


def _bg_run(script: Path, env: dict, timeout_min: int, broad_output: Path,
            profile_text: str, notify_email: str) -> None:
    proc = subprocess.Popen(
        [sys.executable, str(script)],
        cwd=str(APP_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines: list = []
    deadline = time.time() + timeout_min * 60
    for raw in proc.stdout:
        if time.time() > deadline:
            proc.kill()
            break
        line = raw.rstrip()
        if line:
            lines.append(line)
            pct, msg = _parse_progress(line, len(lines))
            with _LOCK:
                _STATE["progress"] = pct
                _STATE["message"] = msg
                _STATE["log"] = "\n".join(lines[-80:])
    proc.wait()
    log_text = "\n".join(lines)

    payload = result_payload(broad_output)

    # Auto-score jobs if profile and AI key are loaded
    if profile_text and _AI_KEY:
        try:
            df = pd.DataFrame(payload.get("rows", []))
            if not df.empty:
                with _LOCK:
                    _STATE["message"] = f"Scoring {min(40, len(df))} jobs with AI…"
                    _STATE["progress"] = 95
                scored = ai.score_jobs(df, profile_text, max_jobs=40)
                payload = dataframe_payload(scored)
        except Exception:
            pass

    # Send email with actual job data
    if notify_email and notify_email.strip():
        try:
            result_df = pd.DataFrame(payload.get("rows", []))
            send_results_email(notify_email.strip(), broad_output, df=result_df)
        except Exception:
            pass

    with _LOCK:
        _STATE.update({
            "phase": "done",
            "progress": 100,
            "message": f"Done! Found {payload['jobs']} jobs.",
            "log": log_text,
            "result": payload,
        })


def start_broad_search_bg(
    workspace: Path, keywords: List[str], days_old: int,
    chunk_size: int, timeout_min: int, request_delay: float,
    request_timeout: int, jobspy_sites: str,
    strict_dates: bool, skip_empty: bool,
    profile_text: str = "",
    notify_email: str = "",
    is_remote: bool = False,
    job_type: str = "",
) -> None:
    ensure_workspace(workspace)
    keyword_file = save_keywords(workspace, keywords)
    broad_output = workspace / "job_csvs" / "sim_eng" / "sim_eng_jobs.csv"
    broad_chunks = workspace / "job_chunks" / "sim_eng"
    env = {
        **base_env(workspace, keyword_file, days_old, chunk_size, request_delay, request_timeout),
        "SIM_ENG_OUTPUT_CSV": str(broad_output),
        "SIM_ENG_CHUNK_DIR": str(broad_chunks),
        "SIM_ENG_EMPTY_LOG": str(workspace / "empty_desc_urls.txt"),
        "SIM_ENG_STRICT_POSTED_DATE_FILTER": str(strict_dates).lower(),
        "SIM_ENG_SKIP_EMPTY_DESC": str(skip_empty).lower(),
        "SIM_ENG_JOBSPY_SITES": jobspy_sites or "linkedin",
        "SIM_ENG_IS_REMOTE": "true" if is_remote else "",
        "SIM_ENG_JOB_TYPE": job_type or "",
        "PYTHONUNBUFFERED": "1",
        "PATH": os.environ.get("PATH", ""),
        "SIM_ENG_AI_PROVIDER": _PROVIDER,
        "SIM_ENG_AI_MODEL": _AI_MODEL,
        "SIM_ENG_AI_KEY": _AI_KEY,
    }
    with _LOCK:
        _STATE.update({
            "phase": "running", "progress": 3, "message": "Starting search…",
            "log": "", "result": None, "jobs_found": 0, "start_time": time.time(),
        })
    t = threading.Thread(
        target=_bg_run,
        args=(JOB_SCRIPT, env, timeout_min, broad_output, profile_text, notify_email),
        daemon=True,
    )
    t.start()


APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = APP_DIR / "workspace"
JOB_SCRIPT = APP_DIR / "job_scraper.py"
COMPANY_SCRIPT = APP_DIR / "company_career_scraper.py"


class UploadFile:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def read(self) -> bytes:
        return self._data


def ensure_workspace(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "job_csvs" / "sim_eng").mkdir(parents=True, exist_ok=True)
    (path / "job_chunks" / "sim_eng").mkdir(parents=True, exist_ok=True)
    (path / "job_chunks" / "sim_eng_company").mkdir(parents=True, exist_ok=True)


def parse_lines(value: str) -> List[str]:
    values: List[str] = []
    seen = set()
    for raw_line in (value or "").replace(",", "\n").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        key = line.lower()
        if key not in seen:
            values.append(line)
            seen.add(key)
    return values


def build_keywords(exact: str, titles: str, skills: str) -> List[str]:
    values = parse_lines(exact)
    for title in parse_lines(titles):
        for skill in parse_lines(skills):
            values.append(f"{title} {skill}")

    deduped: List[str] = []
    seen = set()
    for value in values:
        key = value.lower()
        if key not in seen:
            deduped.append(value)
            seen.add(key)
    return deduped


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def dataframe_payload(df: pd.DataFrame) -> Dict[str, object]:
    if df.empty:
        return {
            "jobs": 0,
            "companies": 0,
            "sources": 0,
            "with_date": 0,
            "columns": [],
            "rows": [],
            "source_counts": [],
        }

    source_counts = []
    if "source" in df:
        source_counts = (
            df["source"]
            .fillna("unknown")
            .astype(str)
            .value_counts()
            .rename_axis("source")
            .reset_index(name="count")
            .to_dict("records")
        )

    with_date = 0
    if "date_posted" in df:
        with_date = int(df["date_posted"].fillna("").astype(str).str.len().gt(0).sum())

    rows = df.fillna("").head(1000).to_dict("records")
    return {
        "jobs": int(len(df)),
        "companies": int(df["institution"].nunique()) if "institution" in df else 0,
        "sources": int(df["source"].nunique()) if "source" in df else 0,
        "with_date": with_date,
        "columns": [{"name": col.replace("_", " ").title(), "id": col} for col in df.columns],
        "rows": rows,
        "source_counts": source_counts,
    }


def result_payload(csv_path: Path) -> Dict[str, object]:
    return dataframe_payload(read_csv(csv_path))


def run_script(script: Path, env_updates: Dict[str, str], timeout_minutes: int) -> Tuple[int, str]:
    env = os.environ.copy()
    env.update(env_updates)
    env["PYTHONUNBUFFERED"] = "1"
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(APP_DIR),
            env=env,
            text=True,
            capture_output=True,
            timeout=max(1, timeout_minutes) * 60,
            check=False,
        )
        output = "\n".join(part for part in [proc.stdout, proc.stderr] if part.strip())
        return proc.returncode, output or "(no output)"
    except subprocess.TimeoutExpired:
        return 124, "The run timed out."


def save_keywords(workspace: Path, keywords: List[str]) -> Path:
    ensure_workspace(workspace)
    keyword_file = workspace / "custom_keywords.txt"
    keyword_file.write_text("\n".join(keywords) + ("\n" if keywords else ""), encoding="utf-8")
    return keyword_file


def base_env(
    workspace: Path,
    keyword_file: Path,
    days_old: int,
    chunk_size: int,
    request_delay: float,
    request_timeout: int,
) -> Dict[str, str]:
    return {
        "SIM_ENG_PROJECT_ROOT": str(workspace),
        "SIM_ENG_KEYWORDS": "custom",
        "SIM_ENG_KEYWORDS_FILE": str(keyword_file),
        "SIM_ENG_DAYS_OLD": str(days_old),
        "SIM_ENG_CHUNK_SIZE": str(chunk_size),
        "SIM_ENG_CAREER_CHUNK_SIZE": str(chunk_size),
        "SIM_ENG_REQUEST_DELAY": str(request_delay),
        "SIM_ENG_REQUEST_TIMEOUT": str(request_timeout),
    }


def run_broad_search(
    workspace: Path,
    keywords: List[str],
    days_old: int,
    chunk_size: int,
    timeout_min: int,
    request_delay: float,
    request_timeout: int,
    jobspy_sites: str,
    strict_dates: bool,
    skip_empty: bool,
) -> Tuple[int, str, Dict[str, object]]:
    keyword_file = save_keywords(workspace, keywords)
    broad_output = workspace / "job_csvs" / "sim_eng" / "sim_eng_jobs.csv"
    broad_chunks = workspace / "job_chunks" / "sim_eng"
    env = {
        **base_env(workspace, keyword_file, days_old, chunk_size, request_delay, request_timeout),
        "SIM_ENG_OUTPUT_CSV": str(broad_output),
        "SIM_ENG_CHUNK_DIR": str(broad_chunks),
        "SIM_ENG_EMPTY_LOG": str(workspace / "empty_desc_urls.txt"),
        "SIM_ENG_STRICT_POSTED_DATE_FILTER": str(strict_dates).lower(),
        "SIM_ENG_SKIP_EMPTY_DESC": str(skip_empty).lower(),
        "SIM_ENG_JOBSPY_SITES": jobspy_sites or "linkedin",
    }
    return_code, log = run_script(JOB_SCRIPT, env, timeout_min)
    return return_code, log, result_payload(broad_output)


def write_company_registry(workspace: Path, watchlist: str) -> None:
    records = [
        {
            "company": name,
            "count": 1,
            "ats_hints": [],
            "company_domains": [],
            "sender_domains": [],
            "sender_emails": [],
            "examples": [],
        }
        for name in parse_lines(watchlist)
    ]
    ensure_workspace(workspace)
    (workspace / "company_registry.json").write_text(json.dumps(records, indent=2), encoding="utf-8")


def run_company_search(
    workspace: Path,
    keywords: List[str],
    days_old: int,
    chunk_size: int,
    timeout_min: int,
    request_delay: float,
    request_timeout: int,
    max_companies: int,
) -> Tuple[int, Dict[str, object]]:
    keyword_file = save_keywords(workspace, keywords)
    company_output = workspace / "job_csvs" / "sim_eng" / "sim_eng_company_jobs.csv"
    company_chunks = workspace / "job_chunks" / "sim_eng_company"
    env = {
        **base_env(workspace, keyword_file, days_old, chunk_size, request_delay, request_timeout),
        "SIM_ENG_MAX_COMPANIES": str(max_companies or 25),
        "SIM_ENG_SEARCH_FALLBACK": "true",
        "SIM_ENG_CAREER_OUTPUT_CSV": str(company_output.relative_to(workspace)),
        "SIM_ENG_CAREER_CHUNK_DIR": str(company_chunks.relative_to(workspace)),
        "SIM_ENG_CAREER_SKIPPED_LOG": "company_career_skips.txt",
    }
    return_code, _ = run_script(COMPANY_SCRIPT, env, timeout_min)
    return return_code, result_payload(company_output)


def send_results_email(to_email: str, csv_path: Path, df: "pd.DataFrame | None" = None) -> str:
    import smtplib
    from email import encoders
    from email.mime.base import MIMEBase
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    if not (smtp_host and smtp_user and smtp_pass):
        return "Email not configured — set SMTP_HOST, SMTP_USER, SMTP_PASS in .env"

    # Load results from CSV if dataframe not provided
    if df is None or df.empty:
        df = read_csv(csv_path)

    n_jobs = len(df)
    has_csv = csv_path.exists() and csv_path.stat().st_size > 0

    # Build plain-text summary of top jobs
    preview_rows = []
    preview_df = df.head(30)
    has_score = "ai_score" in preview_df.columns
    if has_score:
        preview_df = preview_df.sort_values("ai_score", ascending=False)

    for _, row in preview_df.iterrows():
        title   = str(row.get("title", "Unknown title"))
        company = str(row.get("institution", row.get("company", "?")))
        source  = str(row.get("source", ""))
        date    = str(row.get("date_posted", ""))
        url     = str(row.get("job_url", row.get("url", "")))
        score   = f"[AI score: {int(row['ai_score'])}/10] " if has_score and pd.notna(row.get("ai_score")) else ""
        reason  = f"\n   → {row['ai_reason']}" if has_score and pd.notna(row.get("ai_reason")) else ""
        line = f"{score}{title} @ {company}"
        if date:
            line += f"  |  {date}"
        if source:
            line += f"  |  {source}"
        if url and url != "nan":
            line += f"\n   {url}"
        line += reason
        preview_rows.append(line)

    preview_text = "\n\n".join(f"{i+1}. {r}" for i, r in enumerate(preview_rows))
    subject_score = " (AI scored)" if has_score else ""

    plain = (
        f"Your job search is complete{subject_score}.\n"
        f"Found {n_jobs} jobs total. Full results are attached as a CSV.\n"
        f"{'Top ' if n_jobs > 30 else ''}{min(n_jobs, 30)} jobs shown below.\n"
        f"\n{'─' * 60}\n\n"
        f"{preview_text}\n"
        f"\n{'─' * 60}\n"
        f"Full data: {csv_path.name} attached ({csv_path.stat().st_size // 1024 if has_csv else 0} KB)"
    )

    msg = MIMEMultipart()
    msg["Subject"] = f"[Job Search] {n_jobs} jobs found{subject_score}"
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg.attach(MIMEText(plain, "plain"))

    if has_csv:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(csv_path.read_bytes())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{csv_path.name}"')
        msg.attach(part)

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return f"Results emailed to {to_email}."
    except Exception as exc:
        return f"Email failed: {exc}"


def configure_ai(provider: str = "", model: str = "", api_key: str = "", raise_errors: bool = False) -> bool:
    global _PROVIDER, _AI_MODEL, _AI_KEY
    if provider:
        _PROVIDER = provider
    if model is not None:
        _AI_MODEL = model
    if api_key:
        _AI_KEY = api_key.strip()
    try:
        ai.configure_ai(_PROVIDER, _AI_MODEL, _AI_KEY)
        return bool(_AI_KEY)
    except Exception:
        if raise_errors:
            raise
        return False


def test_ai_connection(provider: str = "", model: str = "", api_key: str = "") -> str:
    if not (api_key or _AI_KEY):
        raise ValueError("Enter an API key first.")
    configure_ai(provider or _PROVIDER, model or _AI_MODEL, api_key or _AI_KEY, raise_errors=True)
    reply = ai.test_connection()
    return reply or "AI connection OK"


def extract_profile_from_upload(contents: str, filename: str) -> str:
    if not contents:
        raise ValueError("No upload provided.")
    _, encoded = contents.split(",", 1)
    data = base64.b64decode(encoded)
    return ai.extract_text_from_upload(UploadFile(filename, data))


def extract_profile_from_text(value: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError("Paste profile text, a URL, or upload a file.")
    if re.match(r"https?://", text):
        return fetch_profile_from_url(text)
    return text


def fetch_profile_from_url(url: str) -> str:
    return ai.fetch_url_text(url)


def suggest_keywords(profile_text: str, existing: List[str]) -> List[str]:
    return ai.suggest_keywords(profile_text, existing)


def review_keywords(keywords: List[str], profile_text: str) -> dict:
    return ai.review_keywords(keywords, profile_text)


def score_jobs(payload: Dict[str, object], profile_text: str, max_jobs: int = 30) -> Dict[str, object]:
    df = pd.DataFrame(payload.get("rows", []))
    scored = ai.score_jobs(df, profile_text, max_jobs=max_jobs)
    return dataframe_payload(scored)


def draft_cover_letter(job: dict, profile_text: str) -> str:
    return ai.draft_cover_letter(job, profile_text)


def explain_fit(job: dict, profile_text: str) -> str:
    return ai.explain_fit(job, profile_text)
