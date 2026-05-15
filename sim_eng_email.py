import json
import os
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


def send_job_notification(script_key: str, returncode: int, log_file: str) -> None:
    smtp_host = os.environ.get("SIM_ENG_SMTP_HOST", "")
    smtp_port = int(os.environ.get("SIM_ENG_SMTP_PORT", "587"))
    smtp_user = os.environ.get("SIM_ENG_SMTP_USER", "")
    smtp_pass = os.environ.get("SIM_ENG_SMTP_PASS", "")
    email_to  = os.environ.get("SIM_ENG_EMAIL_TO", "")

    if not (smtp_host and smtp_user and smtp_pass and email_to):
        return

    status_label = "completed successfully" if returncode == 0 else f"FAILED (exit {returncode})"

    log_tail = ""
    try:
        text = Path(log_file).read_text(encoding="utf-8", errors="replace")
        log_tail = "\n".join(text.splitlines()[-30:])
    except Exception:
        log_tail = "(log unavailable)"

    # Locate the CSV output (log lives in workspace/job_logs/, CSV in workspace/job_csvs/)
    workspace = Path(log_file).parent.parent
    csv_map = {
        "broad":   workspace / "job_csvs" / "sim_eng" / "sim_eng_jobs.csv",
        "company": workspace / "job_csvs" / "sim_eng" / "sim_eng_company_jobs.csv",
    }
    csv_path = csv_map.get(script_key)
    has_csv  = bool(csv_path and csv_path.exists() and csv_path.stat().st_size > 0)

    body = (
        f"Your job search '{script_key}' {status_label}.\n\n"
        + (f"Results attached: {csv_path.name} "
           f"({csv_path.stat().st_size // 1024} KB)\n\n" if has_csv else "")
        + f"--- Last 30 log lines ---\n{log_tail}"
    )

    msg = MIMEMultipart()
    msg["Subject"] = f"[Job Search] {script_key} {status_label}"
    msg["From"]    = smtp_user
    msg["To"]      = email_to
    msg.attach(MIMEText(body, "plain"))

    if has_csv:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(csv_path.read_bytes())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{csv_path.name}"')
        msg.attach(part)

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)


def notify_waitlist(waitlist_file: str) -> None:
    """Email everyone on the waitlist that a slot is now free, then clear the list."""
    wf = Path(waitlist_file)
    if not wf.exists():
        return
    try:
        waitlist = json.loads(wf.read_text())
    except Exception:
        return
    if not waitlist:
        return

    smtp_host = os.environ.get("SIM_ENG_SMTP_HOST", "")
    smtp_port = int(os.environ.get("SIM_ENG_SMTP_PORT", "587"))
    smtp_user = os.environ.get("SIM_ENG_SMTP_USER", "")
    smtp_pass = os.environ.get("SIM_ENG_SMTP_PASS", "")
    if not (smtp_host and smtp_user and smtp_pass):
        return

    app_url = os.environ.get("APP_URL", "your Job Search Workbench app")

    for email in waitlist:
        try:
            msg = MIMEMultipart()
            msg["Subject"] = "[Job Search] A slot just opened up — come run your search!"
            msg["From"]    = smtp_user
            msg["To"]      = email
            body = (
                "Good news — a job search slot is now available.\n\n"
                f"Head back to {app_url} to run your search.\n\n"
                "Slots fill up quickly, so don't wait too long!"
            )
            msg.attach(MIMEText(body, "plain"))
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        except Exception:
            pass

    wf.write_text(json.dumps([]))  # clear waitlist after notifying
