"""Matplotlib rendering for chart configs -- the "Tool call renders charts"
step named in the architecture doc's Layer 3 flow. Renders exactly the four
chart_configs types ai/charts.py produces (gauge, bar, line, table); no
support for pie, since ai/charts.py deliberately never emits one (see its
module docstring for why).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless: this module only saves figures, never shows a GUI window
import matplotlib.pyplot as plt
from matplotlib.figure import Figure


def _render_gauge(config: dict[str, Any]) -> Figure:
    fig, ax = plt.subplots(figsize=(6, 1.6))
    value = config["data_value"]
    lo, hi = config["min"], config["max"]
    thresholds = config["thresholds"]

    band_colors = {"red": "#d9534f", "yellow": "#f0ad4e", "green": "#5cb85c"}
    for band_name, (band_lo, band_hi) in thresholds.items():
        ax.barh(0, band_hi - band_lo, left=band_lo, height=0.6, color=band_colors.get(band_name, "#cccccc"))

    ax.axvline(value, color="black", linewidth=3)
    ax.set_xlim(lo, hi)
    ax.set_ylim(-0.5, 0.5)
    ax.set_yticks([])
    ax.set_title(f"{config['title']}: {value}")
    fig.tight_layout()
    return fig


def _render_bar(config: dict[str, Any]) -> Figure:
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(config["categories"], config["data"], color="#4a90d9")
    ax.set_title(config["title"])
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    return fig


def _render_line(config: dict[str, Any]) -> Figure:
    fig, ax = plt.subplots(figsize=(7, 4))
    months = [point["month"] for point in config["data"]]
    values = [point["value"] for point in config["data"]]
    ax.plot(months, values, marker="o", color="#4a90d9")
    ax.set_title(config["title"])
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    return fig


# matplotlib's default font (DejaVu Sans) has no glyphs for these -- swap to ASCII
# for the rendered PNG only. The underlying chart_configs JSON keeps the emoji
# unchanged, since a web/Streamlit frontend renders Unicode natively.
_EMOJI_TO_ASCII = {"✅": "[OK]", "⚠️": "[!]", "⚠": "[!]"}


def _sanitize_for_matplotlib(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    for emoji, replacement in _EMOJI_TO_ASCII.items():
        text = text.replace(emoji, replacement)
    return text


def _render_table(config: dict[str, Any]) -> Figure:
    fig, ax = plt.subplots(figsize=(7, 0.5 + 0.4 * len(config["rows"])))
    ax.axis("off")
    rows = [[_sanitize_for_matplotlib(cell) for cell in row] for row in config["rows"]]
    table = ax.table(cellText=rows, colLabels=config["columns"], loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.5)
    ax.set_title(config["title"])
    fig.tight_layout()
    return fig


_RENDERERS = {
    "gauge": _render_gauge,
    "bar": _render_bar,
    "line": _render_line,
    "table": _render_table,
}


def render_chart_configs(chart_configs: list[dict[str, Any]], output_dir: str | Path) -> list[Path]:
    """Render each chart config to a PNG in output_dir. Returns the written file paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for index, config in enumerate(chart_configs):
        renderer = _RENDERERS.get(config["type"])
        if renderer is None:
            raise ValueError(f"No renderer for chart type: {config['type']}")

        fig = renderer(config)
        file_path = output_dir / f"{index:02d}_{config['type']}.png"
        fig.savefig(file_path, dpi=120)
        plt.close(fig)
        written.append(file_path)

    return written
