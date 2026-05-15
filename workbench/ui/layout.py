from __future__ import annotations

import os

from dash import dcc, html

from .. import backend
from ..config import DEFAULT_WORKSPACE, STARTER_EXACT, saved_keyword_text
from .components import card, empty_figure, results_table, section_heading

_DEFAULT_EMAIL = os.environ.get("DEFAULT_EMAIL", "")

def _detect_default_provider() -> tuple:
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return "openai", os.environ["OPENAI_API_KEY"].strip()
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "anthropic", os.environ["ANTHROPIC_API_KEY"].strip()
    return "gemini", os.environ.get("GEMINI_API_KEY", "").strip()

_DEFAULT_PROVIDER, _DEFAULT_KEY = _detect_default_provider()
_AI_READY = bool(_DEFAULT_KEY)

_PROVIDER_PLACEHOLDERS = {
    "openai":    ("sk-…  (platform.openai.com)", "gpt-4o-mini"),
    "gemini":    ("AIzaSy…  (aistudio.google.com)", "gemini-2.5-flash"),
    "anthropic": ("sk-ant-…  (console.anthropic.com)", "claude-haiku-4-5-20251001"),
    "mistral":   ("…  (console.mistral.ai)", "mistral-small-latest"),
    "cohere":    ("…  (dashboard.cohere.com)", "command-r"),
}


def stores() -> list:
    return [
        dcc.Store(id="results-store", data=None),
        dcc.Store(id="profile-store", data={"text": "", "source": ""}),
        dcc.Download(id="download-csv"),
        dcc.Interval(id="search-interval", interval=1200, n_intervals=0, disabled=True),
    ]


def _header() -> html.Header:
    return html.Header(
        className="app-header",
        children=[
            html.Div(className="header-brand", children=[
                html.Span("✦", className="header-gem"),
                html.H1("Job Search Workbench", className="header-title"),
            ]),
            html.Div(id="status-pills", className="status-pills", children=[
                html.Span(
                    "✓ AI ready" if _AI_READY else "AI: add key below",
                    className="pill good" if _AI_READY else "pill warn",
                ),
            ]),
        ],
    )


def _setup_section() -> html.Div:
    return html.Div(
        id="setup-section",
        className="page-section",
        children=[
            # ── Keywords ──────────────────────────────────────────────────
            html.Div(className="search-card panel", children=[
                html.Div(className="search-card-label",
                         children="What roles are you looking for?"),
                dcc.Textarea(
                    id="exact-keywords",
                    value=saved_keyword_text(),
                    placeholder=(
                        "One search phrase per line:\n"
                        "  software engineer python\n"
                        "  data scientist remote\n"
                        "  machine learning researcher"
                    ),
                    className="textarea keywords-box",
                ),
                html.Div(className="keyword-actions", children=[
                    html.Button("📄  From resume",  id="btn-upload-toggle",    n_clicks=0, className="chip-btn"),
                    html.Button("✨  AI suggest",   id="ai-suggest-keywords",  n_clicks=0, className="chip-btn accent"),
                    html.Button("⟳  Clear",         id="btn-clear-kw",         n_clicks=0, className="chip-btn muted"),
                ]),
                html.Div(id="kw-ai-msg", className="inline-msg"),
                html.Div(id="keyword-preview", className="keyword-preview"),
            ]),

            # ── Profile panel (toggleable) ────────────────────────────────
            html.Div(id="profile-panel", className="panel profile-inner",
                     style={"display": "none"}, children=[
                html.Div(className="profile-header", children=[
                    html.Span("Your profile", className="profile-title"),
                    html.Span(
                        "Used for AI keyword suggestions & automatic job scoring after search",
                        className="profile-hint",
                    ),
                ]),
                html.Div(className="profile-grid", children=[
                    dcc.Upload(
                        id="profile-upload",
                        className="upload-box",
                        children=html.Div(["Drop resume / CV here or ", html.Span("browse")]),
                        multiple=False,
                    ),
                    dcc.Textarea(
                        id="profile-text",
                        className="textarea",
                        placeholder="Or paste resume text, LinkedIn bio, portfolio notes… or a URL (https://yourportfolio.com)",
                        style={"minHeight": "110px"},
                    ),
                ]),
                html.Button("Save profile →", id="load-profile", n_clicks=0,
                            className="secondary-button save-btn"),
                html.Div(id="profile-message", className="inline-msg"),
            ]),

            # ── AI config bar ─────────────────────────────────────────────
            html.Div(className="panel key-panel", children=[
                html.Span("🤖  AI", className="key-label"),
                dcc.Dropdown(
                    id="ai-provider",
                    value=_DEFAULT_PROVIDER,
                    clearable=False,
                    className="run-dropdown",
                    style={"minWidth": "130px"},
                    options=[
                        {"label": "OpenAI",    "value": "openai"},
                        {"label": "Gemini",    "value": "gemini"},
                        {"label": "Anthropic", "value": "anthropic"},
                        {"label": "Mistral",   "value": "mistral"},
                        {"label": "Cohere",    "value": "cohere"},
                    ],
                ),
                dcc.Input(
                    id="ai-model",
                    value="",
                    type="text",
                    placeholder=_PROVIDER_PLACEHOLDERS[_DEFAULT_PROVIDER][1],
                    className="input",
                    style={"flex": "1", "minWidth": "160px"},
                ),
                dcc.Input(
                    id="ai-key",
                    value=_DEFAULT_KEY,
                    type="password",
                    placeholder=_PROVIDER_PLACEHOLDERS[_DEFAULT_PROVIDER][0],
                    className="input",
                    style={"flex": "2"},
                ),
            ]),

            # ── Run bar ───────────────────────────────────────────────────
            html.Div(className="run-bar panel", children=[
                html.Div(className="run-controls", children=[
                    html.Div(className="run-field", children=[
                        html.Label("Job boards"),
                        dcc.Checklist(
                            id="jobspy-sites",
                            options=[
                                {"label": "LinkedIn",     "value": "linkedin"},
                                {"label": "Indeed",       "value": "indeed"},
                                {"label": "Glassdoor",    "value": "glassdoor"},
                                {"label": "ZipRecruiter", "value": "zip_recruiter"},
                                {"label": "Google Jobs",  "value": "google"},
                            ],
                            value=["linkedin", "indeed"],
                            inline=True,
                            className="run-checklist",
                        ),
                    ]),
                    html.Div(className="run-field", children=[
                        html.Label("Posted within"),
                        dcc.Dropdown(
                            id="days-old", value=30, clearable=False,
                            className="run-dropdown",
                            options=[
                                {"label": "Past week",    "value": 7},
                                {"label": "Past month",   "value": 30},
                                {"label": "Past 60 days", "value": 60},
                                {"label": "Past 90 days", "value": 90},
                            ],
                        ),
                    ]),
                    html.Div(className="run-field", children=[
                        html.Label("Job type"),
                        dcc.Dropdown(
                            id="job-type", value="", clearable=False,
                            className="run-dropdown",
                            options=[
                                {"label": "Any type",    "value": ""},
                                {"label": "Full-time",   "value": "fulltime"},
                                {"label": "Part-time",   "value": "parttime"},
                                {"label": "Contract",    "value": "contract"},
                                {"label": "Internship",  "value": "internship"},
                            ],
                        ),
                    ]),
                    html.Div(className="run-field grow", children=[
                        dcc.Checklist(
                            id="run-options", inline=True, className="run-checklist",
                            value=["strict_dates"],
                            options=[
                                {"label": "Require posting date",   "value": "strict_dates"},
                                {"label": "Skip empty descriptions", "value": "skip_empty"},
                                {"label": "Remote only",            "value": "remote_only"},
                            ],
                        ),
                    ]),
                    html.Div(className="run-field", children=[
                        html.Label("Email results to"),
                        dcc.Input(
                            id="notify-email", value=_DEFAULT_EMAIL, type="email",
                            placeholder="you@example.com", className="input",
                        ),
                    ]),
                    html.Button("Find Jobs →", id="run-search", n_clicks=0,
                                className="primary-button run-btn"),
                ]),
                html.Div(id="run-message", className="inline-msg"),
            ]),

            # ── Advanced ──────────────────────────────────────────────────
            html.Details(className="advanced-panel panel", children=[
                html.Summary("Company-page search (advanced)"),
                html.Div(className="advanced-grid", children=[
                    html.Div([
                        html.Label("Watchlist (one company per line)"),
                        dcc.Textarea(
                            id="company-watchlist",
                            placeholder="Anthropic\nOpenAI\nMeta",
                            className="textarea",
                            style={"minHeight": "100px"},
                        ),
                    ]),
                    html.Div([
                        html.Label("Max companies"),
                        dcc.Input(id="max-companies", value=25, type="number",
                                  min=1, max=10000, className="input"),
                        html.Button("Run company search", id="run-company-search",
                                    n_clicks=0, className="secondary-button",
                                    style={"marginTop": "10px", "width": "100%"}),
                    ]),
                ]),
                html.Div(id="company-message", className="inline-msg"),
            ]),
        ],
    )


def _progress_section() -> html.Div:
    return html.Div(
        id="progress-section",
        className="page-section",
        style={"display": "none"},  # shown by callback when running
        children=[
            html.Div(className="progress-card panel", children=[
                html.Div(id="progress-title", className="progress-title",
                         children="Searching…"),
                html.Div(className="progress-track", children=[
                    html.Div(id="progress-fill", className="progress-fill",
                             style={"width": "3%"}),
                ]),
                html.Div(id="progress-msg", className="progress-msg",
                         children="Starting up…"),
                html.Details(className="log-details", children=[
                    html.Summary("View details"),
                    html.Pre(id="progress-log", className="run-log"),
                ]),
            ]),
        ],
    )


def _results_section() -> html.Div:
    return html.Div(
        id="results-section",
        className="page-section",
        style={"display": "none"},  # shown by callback when done
        children=[
            html.Div(className="results-topbar", children=[
                html.Div(id="metrics-row", className="metrics-row", children=[
                    card("Jobs", "—"), card("Companies", "—"),
                    card("Sources", "—"), card("With date", "—"),
                ]),
                html.Div(className="results-actions", children=[
                    html.Button("📥 Download CSV", id="download-btn", n_clicks=0,
                                className="secondary-button small-btn"),
                ]),
            ]),
            # AI panel — shown when a row is selected
            html.Div(id="ai-job-panel", className="panel ai-job-panel",
                     style={"display": "none"}, children=[
                html.Div(className="ai-job-header", children=[
                    html.Div(id="ai-job-title", className="ai-job-title"),
                    html.Div(className="ai-button-grid", children=[
                        html.Button("Explain fit", id="ai-explain-fit", n_clicks=0,
                                    className="secondary-button"),
                        html.Button("Draft cover letter", id="ai-cover-letter", n_clicks=0,
                                    className="secondary-button"),
                    ]),
                ]),
                dcc.Loading(type="dot", color="#2563eb",
                            children=html.Pre(id="deep-dive-output", className="ai-pre")),
            ]),
            html.Div(className="results-grid", children=[
                html.Div(className="panel table-panel", children=[
                    dcc.Loading(type="dot", color="#2563eb", children=results_table()),
                ]),
                html.Div(className="panel chart-panel", children=[
                    section_heading("View", "Source mix", compact=True),
                    dcc.Graph(id="source-chart", figure=empty_figure(),
                              config={"displayModeBar": False}),
                    html.Details(className="log-details", children=[
                        html.Summary("Run log"),
                        html.Pre(id="run-log", className="run-log"),
                    ]),
                ]),
            ]),
        ],
    )


def create_layout() -> html.Div:
    return html.Div(
        className="app-shell",
        children=[
            *stores(),
            _header(),
            html.Main(className="main-content", children=[
                _setup_section(),
                _progress_section(),
                _results_section(),
            ]),
        ],
    )
