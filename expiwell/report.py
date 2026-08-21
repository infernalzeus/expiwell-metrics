"""Question-per-page PDF report.

Every page answers one plain question about the participant — *How was their
mood? How well did they sleep? How compliant were they?* — rather than dumping
metric tables. The chart on the page is chosen to answer that question and
nothing else.

Charting rules followed throughout:

* one measure per axis — never two y-scales on one plot; two measures of
  different units become two charts;
* axes are bounded by the item's own response scale (1-7, 1-9 ...), so a flat
  series reads as flat rather than being stretched to fill the panel;
* when many series would overlap into a hairball, the page becomes **small
  multiples** — one mini-panel per item, shared axes;
* a categorical palette validated for colour-vision deficiency, with a legend
  whenever more than one series is drawn.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

from .measures import clean_text, item_valences, short_item  # noqa: E402

# Categorical palette, validated for CVD separation on a light surface.
C_BLUE, C_ORANGE, C_AQUA = "#2a78d6", "#eb6834", "#1baf7a"
C_YELLOW, C_MAGENTA, C_GREEN = "#eda100", "#e87ba4", "#008300"
SERIES = [C_BLUE, C_ORANGE, C_AQUA, C_YELLOW, C_MAGENTA, C_GREEN]
INK, INK2, GRIDC = "#0b0b0b", "#52514e", "#dfe3ec"
GOOD, WARN, BAD = "#1baf7a", "#eda100", "#d1495b"


def _page(question: str, answer: str = ""):
    """A page titled with the question it answers."""
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.suptitle(clean_text(question), fontsize=15, fontweight="bold",
                 x=0.035, ha="left", color=INK)
    if answer:
        fig.text(0.035, 0.925, clean_text(answer), fontsize=10.5, color=INK2, ha="left")
    return fig


def _tidy(ax, xlabel="", ylabel="", ylim=None):
    ax.set_xlabel(xlabel, fontsize=9.5, color=INK2)
    ax.set_ylabel(ylabel, fontsize=9.5, color=INK2)
    if ylim:
        ax.set_ylim(*ylim)
    ax.grid(axis="y", color=GRIDC, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRIDC)
    ax.tick_params(labelsize=9, colors=INK2, length=0)


def _series_for(series_rows, survey_key: str, item_key: str):
    """(days, values) for one item, ordered by day/occasion."""
    pts = [r for r in series_rows
           if survey_key in r["survey"].casefold()
           and item_key in r["item"].casefold() and r["day"] is not None]
    pts.sort(key=lambda r: (r["day"], r["occasion"] or 0))
    return [p["day"] for p in pts], [p["value"] for p in pts]


# ---------------------------------------------------------------------------
# How compliant were they?
# ---------------------------------------------------------------------------
def _compliance_page(pdf, compliance):
    per = [p for p in (compliance or {}).get("per_survey", []) if p.get("expected")]
    if not per:
        return
    s = compliance.get("summary", {})
    rate = s.get("overall_response_rate_pct")
    fig = _page("How compliant were they?",
                f"{s.get('total_completed', 0)} of {s.get('total_expected', 0)} scheduled "
                f"prompts completed - {rate:.0f}% overall" if rate is not None else "")
    ax = fig.add_axes([0.30, 0.12, 0.64, 0.74])
    per = sorted(per, key=lambda p: p.get("response_rate_pct") or 0)
    names = [clean_text(p["survey"])[:30] for p in per]
    vals = [p.get("response_rate_pct") or 0 for p in per]
    colors = [GOOD if v >= 80 else WARN if v >= 60 else BAD for v in vals]
    y = range(len(names))
    ax.barh(list(y), vals, color=colors, height=0.62)
    for i, (v, p) in enumerate(zip(vals, per)):
        ax.text(min(v + 1.5, 101), i, f"{v:.0f}%  ({p['completed']}/{p['expected']})",
                va="center", fontsize=9, color=INK2)
    ax.set_yticks(list(y)); ax.set_yticklabels(names, fontsize=9, color=INK)
    ax.set_xlim(0, 118)
    ax.set_xticks([0, 25, 50, 75, 100])
    _tidy(ax, "prompts completed (%)")
    ax.grid(axis="x", color=GRIDC, lw=0.8); ax.grid(axis="y", lw=0)
    pdf.savefig(fig); plt.close(fig)


# ---------------------------------------------------------------------------
# How was their mood?
# ---------------------------------------------------------------------------
def _mood_page(pdf, affect_rows):
    if not affect_rows:
        return
    rows = sorted([r for r in affect_rows if r["day"] is not None],
                  key=lambda r: (r["day"], r["occasion"] or 0))
    x = list(range(len(rows)))
    days = [r["day"] for r in rows]
    pa = [r["positive_affect"] for r in rows]
    na = [r["negative_affect"] for r in rows]
    pa_m = [v for v in pa if v is not None]
    na_m = [v for v in na if v is not None]
    verdict = ""
    if pa_m and na_m:
        verdict = (f"positive affect averaged {sum(pa_m)/len(pa_m):.1f} / 7 and "
                   f"negative affect {sum(na_m)/len(na_m):.1f} / 7")
    fig = _page("How was their mood across the study?", verdict)
    ax = fig.add_axes([0.08, 0.12, 0.88, 0.74])
    ax.plot(x, pa, marker="o", ms=5, lw=2, color=C_BLUE, label="Positive affect")
    ax.plot(x, na, marker="s", ms=5, lw=2, color=C_ORANGE, label="Negative affect")
    # Label every day once, not every prompt, so the axis stays readable.
    ticks, seen = [], set()
    for i, d in enumerate(days):
        if d not in seen:
            ticks.append((i, d)); seen.add(d)
    ax.set_xticks([t[0] for t in ticks])
    ax.set_xticklabels([str(t[1]) for t in ticks])
    _tidy(ax, "day of study", "mean rating (1 = not at all, 7 = very much)", (0.8, 7.2))
    ax.set_yticks(range(1, 8))
    ax.legend(frameon=False, fontsize=10, loc="upper right")
    pdf.savefig(fig); plt.close(fig)


def _mood_profile_page(pdf, items):
    rows = [r for r in items
            if "affect" in r["survey"].casefold() and "test" not in r["survey"].casefold()
            and r.get("scale_max") in (7, "7")]
    if not rows:
        return
    vals = item_valences(rows)
    rows = [r for r in rows if vals.get(r["item"])]
    if not rows:
        return
    rows.sort(key=lambda r: r["mean"])
    labels = [clean_text(r["item"])[:26] for r in rows]
    means = [r["mean"] for r in rows]
    sds = [r["sd"] or 0 for r in rows]
    colors = [C_BLUE if vals[r["item"]] == "positive" else C_ORANGE for r in rows]

    top = rows[-1]["item"]
    fig = _page("Which feelings were strongest?",
                f"highest-rated item was “{clean_text(top)}”; "
                "blue = pleasant feelings, orange = unpleasant")
    ax = fig.add_axes([0.30, 0.10, 0.64, 0.76])
    y = list(range(len(labels)))
    ax.barh(y, means, xerr=sds, color=colors, height=0.64,
            error_kw={"ecolor": "#9aa0ad", "elinewidth": 1.1, "capsize": 2})
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=9, color=INK)
    ax.set_xlim(1, 7.4); ax.set_xticks(range(1, 8))
    _tidy(ax, "mean rating (1-7), bars show SD")
    ax.grid(axis="x", color=GRIDC, lw=0.8); ax.grid(axis="y", lw=0)
    pdf.savefig(fig); plt.close(fig)


def _mood_small_multiples(pdf, series):
    """One mini-panel per feeling — avoids 13 coinciding lines on one axis."""
    rows = [r for r in series
            if "affect" in r["survey"].casefold() and "test" not in r["survey"].casefold()]
    by_item: dict[str, list] = {}
    for r in rows:
        if r["day"] is not None:
            by_item.setdefault(clean_text(r["item"]), []).append(r)
    vals = {k: None for k in by_item}
    from .measures import _valence  # local: valence of each label
    items = [k for k in by_item if _valence(k)]
    if not items:
        return
    items.sort(key=lambda k: (_valence(k) != "positive", k))
    ncol, nrow = 4, (len(items) + 3) // 4
    fig = _page("How did each feeling change day to day?",
                "same 1-7 axis on every panel, so panels can be compared directly")
    for i, item in enumerate(items):
        ax = fig.add_subplot(nrow, ncol, i + 1)
        pts = sorted(by_item[item], key=lambda r: (r["day"], r["occasion"] or 0))
        ax.plot([p["day"] for p in pts], [p["value"] for p in pts],
                lw=1.6, color=C_BLUE if _valence(item) == "positive" else C_ORANGE)
        ax.set_ylim(0.8, 7.2); ax.set_yticks([1, 4, 7])
        ax.set_title(item[:22], fontsize=8.5, color=INK, loc="left")
        ax.tick_params(labelsize=7, colors=INK2, length=0)
        ax.grid(axis="y", color=GRIDC, lw=0.7); ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(GRIDC)
    fig.subplots_adjust(left=0.06, right=0.97, top=0.86, bottom=0.08,
                        hspace=0.62, wspace=0.28)
    pdf.savefig(fig); plt.close(fig)


# ---------------------------------------------------------------------------
# How sleepy / how well did they sleep?
# ---------------------------------------------------------------------------
def _sleepiness_page(pdf, series):
    days, vals = _series_for(series, "cognitron", "choose the number")
    if not days:
        days, vals = _series_for(series, "affect", "choose the number")
    if not days:
        return
    mean = sum(vals) / len(vals)
    fig = _page("How sleepy were they during the day?",
                f"Karolinska Sleepiness Scale, mean {mean:.1f} / 9 "
                "(1 = extremely alert, 9 = very sleepy)")
    ax = fig.add_axes([0.08, 0.12, 0.88, 0.74])
    ax.plot(days, vals, marker="o", ms=6, lw=2, color=C_AQUA)
    ax.axhline(7, color=WARN, lw=1.2, ls="--")
    ax.text(max(days), 7.15, "sleepy (7+)", ha="right", fontsize=8.5, color=WARN)
    _tidy(ax, "day of study", "sleepiness (1-9)", (0.8, 9.4))
    ax.set_yticks(range(1, 10))
    pdf.savefig(fig); plt.close(fig)


def _sleep_duration_page(pdf, sleep_rows):
    rows = sorted([r for r in sleep_rows if r.get("TST_hours") is not None],
                  key=lambda r: r["day"] or 0)
    if not rows:
        return
    days = [r["day"] for r in rows]
    tst = [r["TST_hours"] for r in rows]
    mean = sum(tst) / len(tst)
    short = sum(1 for v in tst if v < 7)
    fig = _page("How much did they sleep each night?",
                f"mean {mean:.1f} h; {short} of {len(tst)} nights under 7 h")
    ax = fig.add_axes([0.08, 0.12, 0.88, 0.74])
    ax.bar(days, tst, color=[C_BLUE if v >= 7 else C_ORANGE for v in tst], width=0.62)
    ax.axhline(7, color=INK2, lw=1.1, ls="--")
    ax.text(days[-1], 7.1, "7 h guideline", ha="right", fontsize=8.5, color=INK2)
    _tidy(ax, "day of study", "total sleep time (hours)",
          (0, max(max(tst) + 1.2, 9)))
    pdf.savefig(fig); plt.close(fig)


def _sleep_efficiency_page(pdf, sleep_rows):
    rows = sorted([r for r in sleep_rows if r.get("SE_pct") is not None],
                  key=lambda r: r["day"] or 0)
    if not rows:
        return
    days = [r["day"] for r in rows]
    se = [r["SE_pct"] for r in rows]
    mean = sum(se) / len(se)
    fig = _page("How efficient was their sleep?",
                f"mean {mean:.0f}% of time in bed asleep "
                "(85% and above is typically considered good)")
    ax = fig.add_axes([0.08, 0.12, 0.88, 0.74])
    ax.bar(days, se, color=[GOOD if v >= 85 else WARN if v >= 75 else BAD for v in se],
           width=0.62)
    ax.axhline(85, color=INK2, lw=1.1, ls="--")
    ax.text(days[-1], 86, "85% threshold", ha="right", fontsize=8.5, color=INK2)
    _tidy(ax, "day of study", "sleep efficiency (%)", (0, 105))
    pdf.savefig(fig); plt.close(fig)


def _sleep_disruption_page(pdf, sleep_rows):
    rows = sorted([r for r in sleep_rows if r["day"] is not None], key=lambda r: r["day"])
    if not rows:
        return
    days = [r["day"] for r in rows]
    sol = [r.get("SOL_min") or 0 for r in rows]
    waso = [r.get("WASO_min") or 0 for r in rows]
    xs = list(range(len(days)))
    w = 0.38
    fig = _page("How long did it take to fall asleep, and how long were they awake?",
                f"mean {sum(sol)/len(sol):.0f} min to fall asleep, "
                f"{sum(waso)/len(waso):.0f} min awake during the night")
    ax = fig.add_axes([0.08, 0.12, 0.88, 0.74])
    ax.bar([x - w / 2 for x in xs], sol, width=w, color=C_BLUE,
           label="time to fall asleep")
    ax.bar([x + w / 2 for x in xs], waso, width=w, color=C_ORANGE,
           label="awake during the night")
    ax.axhline(30, color=INK2, lw=1.1, ls="--")
    ax.text(xs[-1], 31, "30 min", ha="right", fontsize=8.5, color=INK2)
    ax.set_xticks(xs); ax.set_xticklabels([str(d) for d in days])
    _tidy(ax, "day of study", "minutes")
    ax.legend(frameon=False, fontsize=10)
    pdf.savefig(fig); plt.close(fig)


def _sleep_timing_page(pdf, sleep_rows):
    """When did they sleep — bed and wake clock times per night."""
    def _mins(hhmm):
        if not hhmm or ":" not in hhmm:
            return None
        h, m = hhmm.split(":")[:2]
        v = int(h) * 60 + int(m)
        return v - 1440 if v > 1080 else v   # evening times plot below midnight

    rows = sorted([r for r in sleep_rows if r["day"] is not None], key=lambda r: r["day"])
    beds = [(r["day"], _mins(r.get("lights_out"))) for r in rows]
    wakes = [(r["day"], _mins(r.get("final_wake"))) for r in rows]
    beds = [(d, v) for d, v in beds if v is not None]
    wakes = [(d, v) for d, v in wakes if v is not None]
    if not beds and not wakes:
        return
    fig = _page("When did they go to sleep and wake up?",
                "clock time each night; a flat line means a regular schedule")
    ax = fig.add_axes([0.08, 0.12, 0.88, 0.74])
    if beds:
        ax.plot([d for d, _ in beds], [v for _, v in beds], marker="o", ms=5, lw=2,
                color=C_BLUE, label="tried to sleep")
    if wakes:
        ax.plot([d for d, _ in wakes], [v for _, v in wakes], marker="s", ms=5, lw=2,
                color=C_AQUA, label="final wake")
    lo = min([v for _, v in beds + wakes]) - 40
    hi = max([v for _, v in beds + wakes]) + 40
    ticks = list(range(int(lo // 60) * 60, int(hi) + 60, 60))
    ax.set_yticks(ticks)
    ax.set_yticklabels([f"{((t // 60) % 24):02d}:{abs(t) % 60:02d}" for t in ticks])
    _tidy(ax, "day of study", "clock time", (lo, hi))
    ax.legend(frameon=False, fontsize=10)
    pdf.savefig(fig); plt.close(fig)


# ---------------------------------------------------------------------------
def build_report(out_pdf: Path, surveys: list, items: list, series: list,
                 sleep_rows: list, sleep_sum: dict, affect_rows: list,
                 compliance: Optional[dict], participant: str,
                 season: str = "") -> Path:
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    with PdfPages(out_pdf) as pdf:
        # Cover: who / when / what was collected.
        fig = _page(f"{participant}" + (f" - {season}" if season else ""),
                    "ExpiWell experience sampling - what the participant reported")
        ax = fig.add_axes([0.035, 0.08, 0.93, 0.78]); ax.axis("off")
        lines = []
        for s in surveys:
            n = len([r for r in s.responses if r.completed])
            if n:
                lines.append(f"{clean_text(s.name)}: {n} responses")
        if sleep_sum.get("nights"):
            lines.append(f"Sleep diary: {sleep_sum['nights']} nights")
        ax.text(0, 0.96, "\n".join(lines), fontsize=11.5, va="top", color=INK,
                linespacing=1.9)
        pdf.savefig(fig); plt.close(fig)

        _compliance_page(pdf, compliance)
        _mood_page(pdf, affect_rows)
        _mood_profile_page(pdf, items)
        _mood_small_multiples(pdf, series)
        _sleepiness_page(pdf, series)
        _sleep_duration_page(pdf, sleep_rows)
        _sleep_efficiency_page(pdf, sleep_rows)
        _sleep_disruption_page(pdf, sleep_rows)
        _sleep_timing_page(pdf, sleep_rows)
    return out_pdf
