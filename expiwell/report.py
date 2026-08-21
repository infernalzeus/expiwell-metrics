"""Multi-page PDF reporting the measures the participant actually reported.

This is a *measures* report, not a compliance report: it shows what was answered
— item means, how each measure moved across the study, and the derived sleep
metrics — rather than how many prompts were completed.

Pages
-----
1. Overview — participant/season, the surveys found, and the sleep summary.
2. Per survey: the item profile (mean +- SD per item, on the item's own scale).
3. Per survey: the time course of each item across the study days.
4. Sleep diary: night-by-night TST / SOL / WASO / SE and a summary table.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

from .measures import clean_text  # noqa: E402

ACCENT = "#0B2C91"
ACCENT2 = "#4f8cff"
GRID = "#dfe3ec"


def _fig(title: str, subtitle: str = ""):
    title, subtitle = clean_text(title), clean_text(subtitle)
    fig = plt.figure(figsize=(11.69, 8.27))  # A4 landscape
    fig.suptitle(title, fontsize=14, fontweight="bold", x=0.02, ha="left")
    if subtitle:
        fig.text(0.02, 0.935, subtitle, fontsize=9.5, color="#555", ha="left")
    return fig


def _table(ax, rows, cols, bbox, fontsize=8.2):
    rows = [[clean_text(str(c)) for c in row] for row in rows]
    cols = [clean_text(str(c)) for c in cols]
    tbl = ax.table(cellText=rows, colLabels=cols, cellLoc="center",
                   loc="upper left", bbox=bbox)
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(fontsize)
    for (r, _c), cell in tbl.get_celld().items():
        cell.set_edgecolor(GRID)
        if r == 0:
            cell.set_facecolor("#eef1f7")
            cell.set_text_props(fontweight="bold")
    return tbl


def _overview_page(pdf, participant, season, surveys, items, sleep_sum):
    fig = _fig(f"ExpiWell measures - {participant}" + (f" · {season}" if season else ""),
               "What was reported, per survey and per item")
    ax = fig.add_axes([0.02, 0.06, 0.96, 0.86]); ax.axis("off")

    by_survey: dict[str, int] = {}
    for it in items:
        by_survey[it["survey"]] = by_survey.get(it["survey"], 0) + 1
    rows = []
    for s in surveys:
        n_resp = len([r for r in s.responses if r.completed])
        rows.append([clean_text(s.name)[:34], str(n_resp), str(len(s.questions)),
                     str(by_survey.get(s.name, 0))])
    if rows:
        _table(ax, rows, ["survey", "responses", "questions", "numeric measures"],
               [0, 0.52, 0.55, 0.42])

    if sleep_sum:
        ax.text(0.60, 0.94, "Sleep diary summary", fontsize=11,
                fontweight="bold", va="top")
        pretty = {
            "nights": "nights recorded",
            "TST_hours_mean": "total sleep time (h)", "SOL_min_mean": "sleep onset latency (min)",
            "WASO_min_mean": "wake after sleep onset (min)", "SE_pct_mean": "sleep efficiency (%)",
            "TIB_min_mean": "time in bed (min)", "n_awakenings_mean": "awakenings per night",
            "quality_mean": "sleep quality", "restedness_mean": "restedness",
        }
        srows = []
        for key, label in pretty.items():
            if key in sleep_sum:
                sd = sleep_sum.get(key.replace("_mean", "_sd"))
                val = sleep_sum[key]
                srows.append([label, f"{val:g}" + (f"  (SD {sd:g})" if sd else "")])
        if srows:
            _table(ax, srows, ["measure", "mean"], [0.60, 0.30, 0.40, 0.58])
    pdf.savefig(fig); plt.close(fig)


def _item_profile_page(pdf, survey_name, rows, participant):
    """Mean +- SD for every numeric item in one survey."""
    rows = sorted(rows, key=lambda r: r["item"])
    labels = [clean_text(r["item"]) for r in rows]
    means = [r["mean"] for r in rows]
    sds = [r["sd"] or 0 for r in rows]
    lo = min((r["scale_min"] for r in rows if isinstance(r["scale_min"], (int, float))), default=None)
    hi = max((r["scale_max"] for r in rows if isinstance(r["scale_max"], (int, float))), default=None)

    height = max(3.2, 0.32 * len(labels) + 1.6)
    survey_name = clean_text(survey_name)
    fig = _fig(f"{survey_name} - item profile",
               f"{participant} · mean response per item, error bars = SD")
    ax = fig.add_axes([0.34, 0.10, 0.62, 0.80])
    y = range(len(labels))
    ax.barh(list(y), means, xerr=sds, color=ACCENT2, edgecolor=ACCENT,
            error_kw={"ecolor": "#8b94a7", "elinewidth": 1}, height=0.62)
    ax.set_yticks(list(y)); ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    if lo is not None and hi is not None:
        ax.set_xlim(lo - 0.2, hi + 0.2)
        ax.set_xlabel(f"response ({lo:g} - {hi:g} scale)")
    else:
        ax.set_xlabel("response")
    ax.grid(axis="x", alpha=0.3)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    pdf.savefig(fig); plt.close(fig)


def _item_timecourse_page(pdf, survey_name, series, participant, max_items=8):
    """How each item moved across the study."""
    by_item: dict[str, list] = {}
    for r in series:
        by_item.setdefault(r["item"], []).append(r)
    # Busiest items first so the page shows the best-covered measures.
    items = sorted(by_item, key=lambda k: -len(by_item[k]))[:max_items]
    if not items:
        return
    fig = _fig(f"{survey_name} - measures over the study",
               f"{participant} · each point is one completed response")
    ax = fig.add_axes([0.08, 0.10, 0.72, 0.80])
    cmap = plt.get_cmap("tab10")
    for i, item in enumerate(items):
        pts = sorted(by_item[item], key=lambda r: (r["day"] or 0, r["occasion"] or 0))
        xs = [p["day"] for p in pts if p["day"] is not None]
        ys = [p["value"] for p in pts if p["day"] is not None]
        if not xs:
            continue
        ax.plot(xs, ys, marker="o", ms=3.5, lw=1.3, color=cmap(i % 10), label=clean_text(item)[:30])
    ax.set_xlabel("day of study"); ax.set_ylabel("response")
    ax.grid(alpha=0.3)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=8, frameon=False)
    pdf.savefig(fig); plt.close(fig)


def _sleep_pages(pdf, sleep_rows, participant):
    if not sleep_rows:
        return
    rows = sorted(sleep_rows, key=lambda r: (r["day"] or 0))
    days = [r["day"] for r in rows]

    fig = _fig("Sleep diary - night by night", f"{participant} · derived from the Consensus Sleep Diary")
    ax1 = fig.add_axes([0.08, 0.56, 0.86, 0.34])
    tst = [r["TST_hours"] for r in rows]
    ax1.plot(days, tst, marker="o", color=ACCENT, lw=1.6)
    ax1.set_ylabel("total sleep time (h)"); ax1.grid(alpha=0.3)
    ax1.set_title("Total sleep time", fontsize=10, loc="left")
    for side in ("top", "right"):
        ax1.spines[side].set_visible(False)

    ax2 = fig.add_axes([0.08, 0.10, 0.86, 0.34])
    width = 0.38
    xs = list(range(len(days)))
    ax2.bar([x - width / 2 for x in xs], [r["SOL_min"] or 0 for r in rows],
            width=width, label="sleep onset latency (min)", color=ACCENT2)
    ax2.bar([x + width / 2 for x in xs], [r["WASO_min"] or 0 for r in rows],
            width=width, label="wake after sleep onset (min)", color="#f59e0b")
    ax2.set_xticks(xs); ax2.set_xticklabels([str(d) for d in days], fontsize=8)
    ax2.set_xlabel("day of study"); ax2.set_ylabel("minutes")
    ax2.legend(frameon=False, fontsize=8.5); ax2.grid(axis="y", alpha=0.3)
    for side in ("top", "right"):
        ax2.spines[side].set_visible(False)
    pdf.savefig(fig); plt.close(fig)

    # Night table
    fig = _fig("Sleep diary - nightly values", participant)
    ax = fig.add_axes([0.02, 0.05, 0.96, 0.86]); ax.axis("off")
    cols = ["day", "into bed", "lights out", "final wake", "out of bed",
            "SOL", "WASO", "wakes", "TST (h)", "SE %"]
    body = [[str(r["day"]), r["into_bed"], r["lights_out"], r["final_wake"],
             r["out_of_bed"],
             "" if r["SOL_min"] is None else f'{r["SOL_min"]:g}',
             "" if r["WASO_min"] is None else f'{r["WASO_min"]:g}',
             "" if r["n_awakenings"] is None else f'{r["n_awakenings"]:g}',
             "" if r["TST_hours"] is None else f'{r["TST_hours"]:g}',
             "" if r["SE_pct"] is None else f'{r["SE_pct"]:g}'] for r in rows]
    _table(ax, body, cols, [0, max(0.05, 0.92 - 0.035 * len(body)), 1, min(0.92, 0.035 * len(body) + 0.05)])
    pdf.savefig(fig); plt.close(fig)


def build_report(out_pdf: Path, surveys: list, items: list, series: list,
                 sleep_rows: list, sleep_sum: dict, participant: str,
                 season: str = "") -> Path:
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    by_survey_items: dict[str, list] = {}
    for r in items:
        by_survey_items.setdefault(r["survey"], []).append(r)
    by_survey_series: dict[str, list] = {}
    for r in series:
        by_survey_series.setdefault(r["survey"], []).append(r)

    with PdfPages(out_pdf) as pdf:
        _overview_page(pdf, participant, season, surveys, items, sleep_sum)
        for name in sorted(by_survey_items):
            _item_profile_page(pdf, name, by_survey_items[name], participant)
            _item_timecourse_page(pdf, name, by_survey_series.get(name, []), participant)
        _sleep_pages(pdf, sleep_rows, participant)
    return out_pdf
