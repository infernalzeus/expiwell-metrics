"""Multi-page PDF report for an ExpiWell participant/season.

Pages
-----
1. Summary — verdict, overall response rate, per-survey table, review notes.
2. Response calendar — survey x study-day grid (complete / partial / missed /
   not scheduled), which makes drop-off and missed protocol days obvious.
3. Timing — response latency after the prompt window opened (signal-contingent
   surveys) and completion-duration distribution.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

# complete / partial / missed / not-scheduled
_COLORS = {"complete": "#22c55e", "partial": "#f59e0b", "missed": "#ef4444", "na": "#e5e7eb"}
_VERDICT_COLOR = {"PASS": "#15803d", "REVIEW": "#b45309", "FAIL": "#b91c1c", "ERROR": "#6b7280"}


def _fig(title: str):
    fig = plt.figure(figsize=(11.69, 8.27))  # A4 landscape
    fig.suptitle(title, fontsize=14, fontweight="bold", x=0.02, ha="left")
    return fig


def _summary_page(pdf, result: dict[str, Any], participant: str, season: str) -> None:
    s = result["summary"]
    fig = _fig(f"ExpiWell compliance — {participant}" + (f" · {season}" if season else ""))
    ax = fig.add_axes([0.02, 0.06, 0.96, 0.84])
    ax.axis("off")

    verdict = result["verdict"]
    ax.text(0, 1.0, verdict, fontsize=30, fontweight="bold",
            color=_VERDICT_COLOR.get(verdict, "#333"), va="top")
    ax.text(0.16, 1.0,
            f"overall response rate  {s['overall_response_rate_pct']:.1f}%\n"
            f"{s['total_completed']} of {s['total_expected']} scheduled prompts completed"
            f"   ·   {s['total_missed']} missed\n"
            f"study length {s['expected_days']} days   ·   pass mark "
            f"{s['min_response_rate_pct']:.0f}%",
            fontsize=11, va="top")

    rows = []
    for p in result["per_survey"]:
        rate = p.get("response_rate_pct")
        rows.append([
            p.get("survey", "")[:30],
            p.get("type", ""),
            "yes" if p.get("scored") else "—",
            str(p.get("expected") or "—"),
            str(p.get("completed") or 0),
            f"{rate:.0f}%" if rate is not None else "—",
            f"{p['median_latency_min']:.0f}" if p.get("median_latency_min") is not None else "—",
            f"{p['pct_within_window']:.0f}%" if p.get("pct_within_window") is not None else "—",
            f"{p['median_duration_sec']:.0f}" if p.get("median_duration_sec") is not None else "—",
        ])
    if rows:
        tbl = ax.table(
            cellText=rows,
            colLabels=["survey", "type", "scored", "expected", "done", "rate",
                       "median latency (min)", "in window", "median dur (s)"],
            cellLoc="center", loc="upper left", bbox=[0, 0.30, 1, 0.52],
        )
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(8.5)
        for (r, _c), cell in tbl.get_celld().items():
            cell.set_edgecolor("#d1d5db")
            if r == 0:
                cell.set_facecolor("#f3f4f6")
                cell.set_text_props(fontweight="bold")

    notes = result.get("notes") or []
    if notes:
        ax.text(0, 0.24, "Review notes", fontsize=11, fontweight="bold", va="top")
        ax.text(0, 0.20, "\n".join(f"• {n}" for n in notes), fontsize=8.5,
                va="top", wrap=True, color="#7c2d12")
    pdf.savefig(fig)
    plt.close(fig)


def _calendar_page(pdf, result: dict[str, Any]) -> None:
    surveys = [p for p in result["per_survey"] if p.get("per_day")]
    if not surveys:
        return
    max_day = max((d["day"] for p in surveys for d in p["per_day"]), default=0)
    if not max_day:
        return

    fig = _fig("Response calendar — did each scheduled prompt get completed?")
    ax = fig.add_axes([0.20, 0.12, 0.76, 0.76])
    for row, p in enumerate(surveys):
        by_day = {d["day"]: d for d in p["per_day"]}
        for day in range(1, max_day + 1):
            d = by_day.get(day)
            if d is None:
                color = _COLORS["na"]
            elif d["completed"] >= d["expected"] and d["expected"]:
                color = _COLORS["complete"]
            elif d["completed"] > 0:
                color = _COLORS["partial"]
            else:
                color = _COLORS["missed"]
            ax.add_patch(plt.Rectangle((day - 0.5, row - 0.5), 1, 1,
                                       facecolor=color, edgecolor="white", linewidth=1.2))
    ax.set_xlim(0.5, max_day + 0.5)
    ax.set_ylim(-0.5, len(surveys) - 0.5)
    ax.invert_yaxis()
    ax.set_yticks(range(len(surveys)))
    ax.set_yticklabels([f"{p['survey'][:28]}  ({p.get('type','')})" for p in surveys], fontsize=8.5)
    ax.set_xticks(range(1, max_day + 1))
    ax.set_xlabel("Day of study")
    ax.tick_params(length=0)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.legend(
        handles=[Patch(facecolor=_COLORS[k], label=lab) for k, lab in
                 [("complete", "all prompts done"), ("partial", "some done"),
                  ("missed", "none done"), ("na", "not scheduled")]],
        loc="upper center", bbox_to_anchor=(0.5, -0.10), ncol=4, frameon=False, fontsize=9,
    )
    pdf.savefig(fig)
    plt.close(fig)


def _timing_page(pdf, surveys: list, result: dict[str, Any]) -> None:
    by_name = {s.name: s for s in surveys}
    lat_sets, lat_labels, durations = [], [], []
    for p in result["per_survey"]:
        s = by_name.get(p.get("survey"))
        if not s:
            continue
        lats = [r.latency_minutes for r in s.responses
                if r.completed and r.latency_minutes is not None]
        if lats and p.get("type") == "signal":
            lat_sets.append(lats)
            lat_labels.append(p["survey"][:20])
        durations += [r.duration_sec for r in s.responses
                      if r.completed and r.duration_sec is not None]
    if not lat_sets and not durations:
        return

    fig = _fig("Response timing")
    if lat_sets:
        ax1 = fig.add_axes([0.08, 0.55, 0.86, 0.33])
        ax1.boxplot(lat_sets, labels=lat_labels, vert=False, widths=0.6)
        ax1.set_xlabel("minutes after the prompt window opened")
        ax1.set_title("Notification response latency (signal-contingent surveys)",
                      fontsize=10, loc="left")
        ax1.grid(axis="x", alpha=0.3)
    if durations:
        ax2 = fig.add_axes([0.08, 0.10, 0.86, 0.33])
        ax2.hist(durations, bins=min(30, max(5, len(durations) // 2)),
                 color="#4f8cff", edgecolor="white")
        ax2.set_xlabel("completion duration (seconds)")
        ax2.set_ylabel("responses")
        ax2.set_title("How long each response took", fontsize=10, loc="left")
        ax2.grid(axis="y", alpha=0.3)
    pdf.savefig(fig)
    plt.close(fig)


def build_report(out_pdf: Path, result: dict[str, Any], surveys: list,
                 participant: str, season: str = "") -> Path:
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(out_pdf) as pdf:
        _summary_page(pdf, result, participant, season)
        _calendar_page(pdf, result)
        _timing_page(pdf, surveys, result)
    return out_pdf
