"""Renders the AI Engine's chart_configs (see ai/charts.py) as interactive
Plotly figures for the Streamlit UI.

This consumes the exact same chart_configs JSON that ai/render.py renders to
static PNGs with Matplotlib -- one data contract, two renderers for two
different consumers (on-screen interactivity here; static image export
there). Reusing the real, already-computed config rather than re-deriving
thresholds/values in the frontend keeps the UI guaranteed consistent with
what the Analytics/AI Engines actually computed.
"""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

_THRESHOLD_COLORS = {"red": "#d9534f", "yellow": "#f0ad4e", "green": "#5cb85c"}


def _render_gauge(config: dict[str, Any]) -> go.Figure:
    steps = [
        {"range": band_range, "color": _THRESHOLD_COLORS.get(name, "#cccccc")}
        for name, band_range in config["thresholds"].items()
    ]
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=config["data_value"],
            title={"text": config["title"]},
            gauge={
                "axis": {"range": [config["min"], config["max"]]},
                "bar": {"color": "darkblue"},
                "steps": steps,
            },
        )
    )
    fig.update_layout(height=280, margin=dict(t=50, b=10, l=30, r=30))
    return fig


def _render_bar(config: dict[str, Any]) -> go.Figure:
    fig = go.Figure(go.Bar(x=config["categories"], y=config["data"], marker_color="#4a90d9"))
    fig.update_layout(title=config["title"], height=320, margin=dict(t=50, b=10, l=30, r=30))
    return fig


def _render_line(config: dict[str, Any]) -> go.Figure:
    months = [point["month"] for point in config["data"]]
    values = [point["value"] for point in config["data"]]
    fig = go.Figure(go.Scatter(x=months, y=values, mode="lines+markers", line=dict(color="#4a90d9")))
    fig.update_layout(title=config["title"], height=320, margin=dict(t=50, b=10, l=30, r=30))
    return fig


def _render_table(config: dict[str, Any]) -> go.Figure:
    columns = list(zip(*config["rows"])) if config["rows"] else [[] for _ in config["columns"]]
    fig = go.Figure(
        go.Table(
            header=dict(values=config["columns"], fill_color="#4a90d9", font=dict(color="white")),
            cells=dict(values=columns),
        )
    )
    fig.update_layout(title=config["title"], height=120 + 30 * len(config["rows"]), margin=dict(t=50, b=10, l=10, r=10))
    return fig


_RENDERERS = {
    "gauge": _render_gauge,
    "bar": _render_bar,
    "line": _render_line,
    "table": _render_table,
}


def render_chart_config(config: dict[str, Any]) -> go.Figure:
    """Dispatch a single chart config to its Plotly renderer."""
    renderer = _RENDERERS.get(config["type"])
    if renderer is None:
        raise ValueError(f"No Streamlit renderer for chart type: {config['type']}")
    return renderer(config)
