from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict

import pandas as pd
import plotly.express as px
from dash import Input, Output, State, ctx, dcc, html, no_update

from . import backend
from .config import DEFAULT_WORKSPACE
from .ui.components import card, empty_figure, keyword_chips, section_heading

# Witty messages shown in the progress bar, indexed by (progress_pct // 20) then cycled
_WITTY = [
    # 0–19 %
    ["Convincing LinkedIn to share its secrets…", "Warming up the job-finding engines…",
     "Bribing search algorithms with compliments…", "Whispering to job boards in their native tongue…",
     "Politely knocking on every career portal…"],
    # 20–39 %
    ["LinkedIn is talking — reluctantly…", "Infiltrating job boards like a polite ninja…",
     "Reading job descriptions so you don't have to…", "Asking Indeed very nicely…",
     "The internet is large. We checked most of it."],
    # 40–59 %
    ["Found some gems, hunting for more…", "Your dream job is hiding in here somewhere…",
     "Sifting through the haystack of opportunity…", "More jobs incoming — patience, young padawan…",
     "Glassdoor is whispering salary secrets…"],
    # 60–79 %
    ["Evicting duplicate listings from the results…", "Cutting noise, keeping signal…",
     "Quality control: removing the suspiciously vague ones…", "Nearly there — internet speed not guaranteed…",
     "Polishing the results just for you…"],
    # 80–100 %
    ["AI is reading every posting personally…", "Matching jobs to your profile like a professional matchmaker…",
     "Final countdown — runway cleared for landing…", "Wrapping it all up with a bow…",
     "Almost done — good things take a moment…"],
]

_CHUNK_SIZE = 5
_TIMEOUT_MIN = 60
_REQUEST_DELAY = 0.5
_REQUEST_TIMEOUT = 20
_JOBSPY_SITES = "linkedin,indeed"
_BROAD_CSV = DEFAULT_WORKSPACE / "job_csvs" / "sim_eng" / "sim_eng_jobs.csv"

_SHOW = {}
_HIDE = {"display": "none"}


def register_callbacks(app) -> None:

    # ── Toggle profile panel ──────────────────────────────────────────────────

    @app.callback(
        Output("profile-panel", "style"),
        Input("btn-upload-toggle", "n_clicks"),
        State("profile-panel", "style"),
        prevent_initial_call=True,
    )
    def toggle_profile(n, style):
        return _HIDE if (style or {}).get("display") != "none" else _SHOW

    # ── Clear keywords ────────────────────────────────────────────────────────

    @app.callback(
        Output("exact-keywords", "value"),
        Input("btn-clear-kw", "n_clicks"),
        prevent_initial_call=True,
    )
    def clear_keywords(_):
        return ""

    # ── Keyword preview ───────────────────────────────────────────────────────

    @app.callback(
        Output("keyword-preview", "children"),
        Input("exact-keywords", "value"),
    )
    def keyword_preview(text):
        kws = backend.parse_lines(text)
        if not kws:
            return []
        return keyword_chips(kws)

    # ── Save profile ──────────────────────────────────────────────────────────

    @app.callback(
        Output("profile-store", "data"),
        Output("profile-message", "children"),
        Input("load-profile", "n_clicks"),
        State("profile-upload", "contents"),
        State("profile-upload", "filename"),
        State("profile-text", "value"),
        State("gemini-key", "value"),
        prevent_initial_call=True,
    )
    def save_profile(_, contents, filename, pasted, gemini_key):
        try:
            backend.configure_ai(gemini_key or "")
            if contents and filename:
                text = backend.extract_profile_from_upload(contents, filename)
                src = filename
            else:
                text = backend.extract_profile_from_text(pasted)
                src = "pasted text"
            return {"text": text, "source": src}, f"✓ Profile saved from {src}"
        except Exception as exc:
            return no_update, f"Error: {exc}"

    # ── AI: suggest keywords ──────────────────────────────────────────────────

    @app.callback(
        Output("exact-keywords", "value", allow_duplicate=True),
        Output("kw-ai-msg", "children"),
        Input("ai-suggest-keywords", "n_clicks"),
        State("profile-store", "data"),
        State("exact-keywords", "value"),
        State("gemini-key", "value"),
        prevent_initial_call=True,
    )
    def ai_suggest(_, profile, current_kw, gemini_key):
        profile_text = (profile or {}).get("text", "")
        if not profile_text:
            return no_update, "⚠ Save a profile first (click '📄 From resume')."
        try:
            existing = backend.parse_lines(current_kw)
            suggestions = backend.suggest_keywords(profile_text, existing, gemini_key or "")
            merged = list(dict.fromkeys(existing + suggestions))
            return "\n".join(merged), f"✓ Added {len(suggestions)} AI suggestions."
        except Exception as exc:
            return no_update, f"AI failed: {exc}"

    # ── Start search ──────────────────────────────────────────────────────────

    @app.callback(
        Output("search-interval", "disabled"),
        Output("run-message",     "children"),
        Output("progress-section","style"),
        Output("results-section", "style"),
        Input("run-search",    "n_clicks"),
        State("exact-keywords","value"),
        State("days-old",      "value"),
        State("job-type",      "value"),
        State("run-options",   "value"),
        State("jobspy-sites",  "value"),
        State("notify-email",  "value"),
        State("profile-store", "data"),
        State("gemini-key",    "value"),
        prevent_initial_call=True,
    )
    def start_search(_, kw_text, days_old, job_type, run_options, jobspy_sites, notify_email, profile, gemini_key):
        keywords = backend.parse_lines(kw_text)
        if not keywords:
            return no_update, "⚠ Add at least one keyword first.", _HIDE, no_update
        sites = ",".join(jobspy_sites) if jobspy_sites else _JOBSPY_SITES
        profile_text = (profile or {}).get("text", "")
        opts = run_options or []
        backend.start_broad_search_bg(
            DEFAULT_WORKSPACE, keywords, int(days_old or 30),
            _CHUNK_SIZE, _TIMEOUT_MIN, _REQUEST_DELAY, _REQUEST_TIMEOUT, sites,
            "strict_dates" in opts,
            "skip_empty" in opts,
            profile_text=profile_text,
            gemini_key=gemini_key or "",
            notify_email=notify_email or "",
            is_remote="remote_only" in opts,
            job_type=job_type or "",
        )
        return False, "", _SHOW, _HIDE   # enable interval, show progress, hide old results

    # ── Poll progress ─────────────────────────────────────────────────────────

    @app.callback(
        Output("progress-fill",   "style"),
        Output("progress-msg",    "children"),
        Output("progress-log",    "children"),
        Output("search-interval", "disabled", allow_duplicate=True),
        Output("progress-section","style",    allow_duplicate=True),
        Output("results-section", "style",    allow_duplicate=True),
        Output("results-store",   "data",     allow_duplicate=True),
        Output("status-pills",    "children", allow_duplicate=True),
        Input("search-interval",  "n_intervals"),
        prevent_initial_call=True,
    )
    def poll_progress(n_intervals):
        import time as _time
        state = backend.get_state()
        phase = state["phase"]
        pct   = state["progress"]

        if phase == "running":
            # Witty message — cycles every 3 ticks, stage based on pct
            stage   = min(4, pct // 20)
            msgs    = _WITTY[stage]
            witty   = msgs[(n_intervals // 3) % len(msgs)]

            # Jobs found so far
            jobs_so_far = state.get("jobs_found", 0)
            jobs_txt = f"  ·  {jobs_so_far} jobs found so far" if jobs_so_far else ""

            # Time remaining estimate
            start_t = state.get("start_time")
            time_txt = ""
            if start_t and pct > 8:
                elapsed = _time.time() - start_t
                total_est = elapsed / (pct / 100)
                remaining = max(0, total_est - elapsed)
                if remaining > 60:
                    time_txt = f"  ·  ~{int(remaining / 60)}m {int(remaining % 60)}s remaining"
                else:
                    time_txt = f"  ·  ~{int(remaining)}s remaining"

            msg = html.Span([
                html.Span(witty, className="witty-msg"),
                html.Span(f"{jobs_txt}{time_txt}", className="progress-meta"),
            ])

            return (
                {"width": f"{pct}%"},
                msg,
                state["log"],
                False,
                _SHOW,
                _HIDE,
                no_update,
                [html.Span(f"{pct}%", className="pill blue")],
            )

        if phase == "done":
            result = state.get("result") or {}
            jobs = result.get("jobs", 0)
            ai_scored = any("ai_score" in str(r) for r in result.get("rows", [{}])[:1])
            label = f"✓ {jobs} jobs" + (" · AI scored" if ai_scored else "")
            return (
                {"width": "100%"},
                state["message"],
                state["log"],
                True,
                _HIDE,
                _SHOW,
                result,
                [html.Span(label, className="pill good")],
            )

        return no_update, no_update, no_update, True, _HIDE, _HIDE, no_update, no_update

    # ── Render results ────────────────────────────────────────────────────────

    @app.callback(
        Output("metrics-row",     "children"),
        Output("results-table",   "columns"),
        Output("results-table",   "data"),
        Output("source-chart",    "figure"),
        Output("run-log",         "children"),
        Input("results-store",    "data"),
    )
    def render_results(payload):
        payload = payload or {}
        metrics = [
            card("Jobs",       str(payload.get("jobs", "—"))),
            card("Companies",  str(payload.get("companies", "—"))),
            card("Sources",    str(payload.get("sources", "—"))),
            card("With date",  str(payload.get("with_date", "—"))),
        ]
        rows = payload.get("rows", [])
        columns = payload.get("columns", [])
        # Put ai_score first if present
        if columns:
            ai_cols = [c for c in columns if c["id"] in ("ai_score", "ai_reason")]
            other_cols = [c for c in columns if c["id"] not in ("ai_score", "ai_reason")]
            columns = ai_cols + other_cols

        source_counts = pd.DataFrame(payload.get("source_counts", []))
        fig = empty_figure()
        if not source_counts.empty:
            fig = px.bar(source_counts, x="source", y="count", color="source", text="count")
            fig.update_layout(template="plotly_white", height=240,
                              margin=dict(l=20, r=20, t=20, b=20), showlegend=False)

        log = backend.get_state().get("log", "No run yet.")
        return metrics, columns, rows, fig, log

    # ── Show AI panel when row selected ──────────────────────────────────────

    @app.callback(
        Output("ai-job-panel", "style"),
        Output("ai-job-title", "children"),
        Input("results-table", "selected_rows"),
        State("results-table", "derived_virtual_data"),
        State("results-store", "data"),
        prevent_initial_call=True,
    )
    def show_ai_panel(selected_rows, visible_rows, payload):
        rows = visible_rows or (payload or {}).get("rows", [])
        if not rows or not selected_rows:
            return _HIDE, ""
        job = rows[selected_rows[0]]
        title = f"{job.get('title', '?')} @ {job.get('institution', '?')}"
        score = job.get("ai_score")
        if score:
            title = f"★ {score}/10 · {title}"
        return _SHOW, title

    # ── AI: explain fit / cover letter ────────────────────────────────────────

    @app.callback(
        Output("deep-dive-output", "children"),
        Input("ai-explain-fit",  "n_clicks"),
        Input("ai-cover-letter", "n_clicks"),
        State("results-store",   "data"),
        State("results-table",   "derived_virtual_data"),
        State("results-table",   "selected_rows"),
        State("profile-store",   "data"),
        State("gemini-key",      "value"),
        prevent_initial_call=True,
    )
    def ai_deep_dive(_, __, payload, visible_rows, selected_rows, profile, gemini_key):
        profile_text = (profile or {}).get("text", "")
        if not profile_text:
            return "Save a profile first (go back to Search and click '📄 From resume')."
        rows = visible_rows or (payload or {}).get("rows", [])
        if not rows:
            return "No results yet."
        idx = (selected_rows or [0])[0]
        job = rows[min(idx, len(rows) - 1)]
        try:
            if ctx.triggered_id == "ai-cover-letter":
                return backend.draft_cover_letter(job, profile_text, gemini_key or "")
            return backend.explain_fit(job, profile_text, gemini_key or "")
        except Exception as exc:
            return f"AI error: {exc}"

    # ── Download CSV ──────────────────────────────────────────────────────────

    @app.callback(
        Output("download-csv", "data"),
        Input("download-btn", "n_clicks"),
        State("results-store", "data"),
        prevent_initial_call=True,
    )
    def download_csv(_, payload):
        rows = (payload or {}).get("rows", [])
        if not rows:
            return no_update
        return dcc.send_data_frame(pd.DataFrame(rows).to_csv, "job_results.csv", index=False)

    # ── Company search ────────────────────────────────────────────────────────

    @app.callback(
        Output("company-message", "children"),
        Input("run-company-search", "n_clicks"),
        State("exact-keywords",  "value"),
        State("days-old",        "value"),
        State("company-watchlist","value"),
        State("max-companies",   "value"),
        prevent_initial_call=True,
    )
    def run_company(_, kw_text, days_old, watchlist, max_co):
        keywords = backend.parse_lines(kw_text)
        if not keywords:
            return "Add keywords first."
        if watchlist:
            backend.write_company_registry(DEFAULT_WORKSPACE, watchlist)
        elif not (DEFAULT_WORKSPACE / "company_registry.json").exists():
            return "Add companies to the watchlist first."
        rc, payload = backend.run_company_search(
            DEFAULT_WORKSPACE, keywords, int(days_old or 30),
            _CHUNK_SIZE, _TIMEOUT_MIN, _REQUEST_DELAY, _REQUEST_TIMEOUT, int(max_co or 25),
        )
        return f"Done (exit {rc}) — {payload['jobs']} jobs found."
