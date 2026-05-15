from __future__ import annotations

import pandas as pd
import plotly.express as px
from dash import dash_table, dcc, html


def card(title: str, value: str, subtitle: str = "") -> html.Div:
    return html.Div(
        className="metric-card",
        children=[
            html.Div(title, className="metric-label"),
            html.Div(value, className="metric-value"),
            html.Div(subtitle, className="metric-subtitle") if subtitle else None,
        ],
    )


def empty_figure():
    fig = px.bar(pd.DataFrame({"source": [], "count": []}), x="source", y="count")
    fig.update_layout(template="plotly_white", height=260, margin=dict(l=20, r=20, t=20, b=20))
    return fig


def section_heading(kicker: str, title: str, compact: bool = False) -> html.Div:
    class_name = "section-heading compact" if compact else "section-heading"
    return html.Div(className=class_name, children=[html.Span(kicker), html.H3(title)])


def results_table() -> dash_table.DataTable:
    return dash_table.DataTable(
        id="results-table",
        columns=[],
        data=[],
        row_selectable="single",
        selected_rows=[],
        page_size=12,
        filter_action="native",
        sort_action="native",
        style_as_list_view=True,
        style_table={"overflowX": "auto"},
        style_header={"fontWeight": "700"},
        style_cell={
            "fontFamily": "Inter, system-ui, sans-serif",
            "fontSize": "13px",
            "padding": "10px",
            "maxWidth": "360px",
            "overflow": "hidden",
            "textOverflow": "ellipsis",
        },
    )


def keyword_chips(keywords: list[str]) -> list[html.Div]:
    chips = [html.Span(keyword, className="keyword-chip") for keyword in keywords[:12]]
    if len(keywords) > 12:
        chips.append(html.Span(f"+{len(keywords) - 12} more", className="keyword-chip muted"))
    return [html.Div(f"{len(keywords)} active keywords", className="preview-count"), html.Div(chips, className="chip-wrap")]

