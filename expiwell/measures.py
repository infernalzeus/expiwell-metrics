"""Measures computed from the answers themselves.

This is the substantive output of the tool: what the participant actually
*reported*, not whether they reported it.

Two layers:

1. **Item measures** (generic, no survey hard-coding). Every question whose
   answers carry a numeric coding is summarised — n, mean, SD, median, range —
   plus the per-occasion series so a value can be tracked over the study. Numbers
   come from the question's ``Choices`` legend (answers export as labels), from a
   plain numeric answer, or from a "45 minutes"-style free-text answer.

2. **Sleep-diary metrics** (Consensus Sleep Diary). Questions 1-9 of the sleep
   diary are the standard instrument, so the standard night-level metrics are
   derived from them:

       TIB   time in bed          = out-of-bed  -  into-bed
       SOL   sleep onset latency  = Q3 (minutes)
       WASO  wake after sleep onset = Q5 (minutes)
       TST   total sleep time     = (final wake - lights out) - SOL - WASO
       SE    sleep efficiency     = TST / TIB * 100

Times cross midnight, so any end-time earlier than its start is rolled to the
next day before differencing.
"""
from __future__ import annotations

import re
import statistics
from datetime import datetime, timedelta
from typing import Any, Optional

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_TIME_RE = re.compile(r"^\s*(\d{1,2})[:.](\d{2})")


def parse_number(value: Any) -> Optional[float]:
    """First number in an answer: '45', '45 minutes', '1 hr 30' -> 45/45/1."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = _NUM_RE.search(str(value))
    return float(m.group()) if m else None


def parse_minutes(value: Any) -> Optional[float]:
    """Duration in minutes from free text: '1 hr 30', '90', '1.5 hours'."""
    if value is None or value == "":
        return None
    text = str(value).strip().lower()
    nums = [float(n) for n in _NUM_RE.findall(text)]
    if not nums:
        return None
    if "h" in text:  # hours (optionally hours + minutes)
        mins = nums[0] * 60
        if len(nums) > 1:
            mins += nums[1]
        return mins
    return nums[0]


def parse_clock(value: Any) -> Optional[tuple[int, int]]:
    """'21:40' -> (21, 40). Accepts 9:05 PM style too."""
    if not value:
        return None
    text = str(value).strip()
    m = _TIME_RE.match(text)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    low = text.lower()
    if "pm" in low and h < 12:
        h += 12
    if "am" in low and h == 12:
        h = 0
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return h, mi


def _numeric_for(question: dict, value_map: dict, answer: Any) -> Optional[float]:
    """Numeric value of one answer, using the Choices legend where available."""
    if answer is None or answer == "":
        return None
    col = question.get("column", "")
    mapped = value_map.get(col, {}).get(str(answer).casefold())
    if mapped is not None:
        return float(mapped)
    qtype = (question.get("type") or "").lower()
    if qtype in ("datetime",):          # times are handled by the sleep metrics
        return None
    if qtype in ("text",):
        return parse_minutes(answer)
    return parse_number(answer)


def _stats(values: list[float]) -> dict[str, Any]:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0, "mean": None, "sd": None, "median": None, "min": None, "max": None}
    return {
        "n": len(vals),
        "mean": round(statistics.fmean(vals), 3),
        "sd": round(statistics.stdev(vals), 3) if len(vals) > 1 else 0.0,
        "median": round(statistics.median(vals), 3),
        "min": round(min(vals), 3),
        "max": round(max(vals), 3),
    }


# ---------------------------------------------------------------------------
# 1. Generic item measures
# ---------------------------------------------------------------------------
def item_measures(surveys: list) -> list[dict[str, Any]]:
    """One row per question that yields numbers: distribution across the study."""
    rows: list[dict[str, Any]] = []
    for s in surveys:
        vmap = s.value_map()
        completed = [r for r in s.responses if r.completed]
        for q in s.questions:
            if (q.get("type") or "").lower() == "instruction":
                continue
            vals = [_numeric_for(q, vmap, r.answers.get(q["column"])) for r in completed]
            st = _stats([v for v in vals if v is not None])
            if not st["n"]:
                continue
            rows.append({
                "participant": s.participant,
                "survey": s.name,
                "item": short_item(q.get("text", "")),
                "question_text": q.get("text", ""),
                "response_type": q.get("type", ""),
                "scale_min": q.get("scale_min", ""),
                "scale_max": q.get("scale_max", ""),
                **st,
            })
    return rows


def item_series(surveys: list) -> list[dict[str, Any]]:
    """One row per answered item per occasion — the time course of each measure."""
    rows: list[dict[str, Any]] = []
    for s in surveys:
        vmap = s.value_map()
        for r in s.responses:
            if not r.completed:
                continue
            for q in s.questions:
                if (q.get("type") or "").lower() == "instruction":
                    continue
                raw = r.answers.get(q["column"])
                val = _numeric_for(q, vmap, raw)
                if val is None:
                    continue
                rows.append({
                    "participant": s.participant,
                    "survey": s.name,
                    "day": r.day,
                    "occasion": r.occasion,
                    "timestamp": r.start.isoformat(sep=" ") if r.start else "",
                    "item": short_item(q.get("text", "")),
                    "answer": raw,
                    "value": val,
                })
    return rows


#: Zero-width / BOM / control characters that appear in exported question text.
#: They break PDF text rendering (matplotlib calls ord() on each glyph), so any
#: string headed for a plot label or a table is scrubbed first.
_INVISIBLE = dict.fromkeys(
    [0xFEFF, 0x200B, 0x200C, 0x200D, 0x2060, 0x00AD] + list(range(0x00, 0x20)), " "
)


def clean_text(text: str) -> str:
    """Printable, single-spaced version of an exported string."""
    t = (text or "").replace(" ", " ").translate(_INVISIBLE)
    return re.sub(r"\s+", " ", t).strip()



def short_item(text: str) -> str:
    """Readable item label: the part after '...' or the leading question number."""
    t = clean_text(text)
    if "..." in t:
        tail = t.split("...")[-1].strip()
        if tail:
            return tail[:48]
    t = re.sub(r"^\s*\d+\s*[.)]\s*", "", t)
    return t[:48]


# ---------------------------------------------------------------------------
# 2. Sleep-diary night metrics (Consensus Sleep Diary)
# ---------------------------------------------------------------------------
_SLEEP_KEYS = {
    "into_bed": ("what time did you get", "into bed"),
    "lights_out": ("what time did you try", "go to sleep"),
    "sol": ("how long did it take you to fall asleep",),
    "n_awakenings": ("how many times did you wake up",),
    "waso": ("how long did these awakenings last",),
    "final_wake": ("what time did you finally wake up",),
    "out_of_bed": ("what time did you get out of bed",),
    "quality": ("rate the quality of your sleep",),
    "restedness": ("restful or refreshed",),
}


def _match_sleep_columns(survey) -> dict[str, str]:
    """Map each Consensus Sleep Diary concept to its question column."""
    found: dict[str, str] = {}
    for q in survey.questions:
        text = (q.get("text") or "").casefold()
        for key, needles in _SLEEP_KEYS.items():
            if key in found:
                continue
            if all(n in text for n in needles):
                found[key] = q["column"]
    return found


def _minutes_between(start: tuple[int, int], end: tuple[int, int]) -> float:
    """Minutes from start to end, rolling past midnight when end <= start."""
    base = datetime(2000, 1, 1, start[0], start[1])
    fin = datetime(2000, 1, 1, end[0], end[1])
    if fin <= base:
        fin += timedelta(days=1)
    return (fin - base).total_seconds() / 60.0


def sleep_metrics(surveys: list) -> list[dict[str, Any]]:
    """One row per diary night with the standard derived sleep metrics."""
    rows: list[dict[str, Any]] = []
    for s in surveys:
        if "sleep" not in s.name.casefold():
            continue
        cols = _match_sleep_columns(s)
        if not cols:
            continue
        vmap = s.value_map()
        for r in s.responses:
            if not r.completed:
                continue
            a = r.answers

            def clock(key):
                return parse_clock(a.get(cols.get(key, ""), ""))

            into_bed, lights_out = clock("into_bed"), clock("lights_out")
            final_wake, out_of_bed = clock("final_wake"), clock("out_of_bed")
            sol = parse_minutes(a.get(cols.get("sol", ""), ""))
            waso = parse_minutes(a.get(cols.get("waso", ""), ""))
            nwak = parse_number(a.get(cols.get("n_awakenings", ""), ""))

            tib = (_minutes_between(into_bed, out_of_bed)
                   if into_bed and out_of_bed else None)
            spt = (_minutes_between(lights_out, final_wake)
                   if lights_out and final_wake else None)
            tst = None
            if spt is not None:
                tst = spt - (sol or 0) - (waso or 0)
                tst = max(tst, 0.0)
            se = round(100.0 * tst / tib, 1) if (tst is not None and tib) else None

            def hhmm(t):
                return f"{t[0]:02d}:{t[1]:02d}" if t else ""

            rows.append({
                "participant": s.participant,
                "survey": s.name,
                "day": r.day,
                "date": r.start.date().isoformat() if r.start else "",
                "into_bed": hhmm(into_bed),
                "lights_out": hhmm(lights_out),
                "final_wake": hhmm(final_wake),
                "out_of_bed": hhmm(out_of_bed),
                "SOL_min": sol,
                "n_awakenings": nwak,
                "WASO_min": waso,
                "TIB_min": round(tib, 1) if tib is not None else None,
                "TST_min": round(tst, 1) if tst is not None else None,
                "TST_hours": round(tst / 60.0, 2) if tst is not None else None,
                "SE_pct": se,
                "quality": _numeric_for(
                    {"column": cols.get("quality", ""), "type": "Single selection"},
                    vmap, a.get(cols.get("quality", ""), "")),
                "restedness": _numeric_for(
                    {"column": cols.get("restedness", ""), "type": "Single selection"},
                    vmap, a.get(cols.get("restedness", ""), "")),
            })
    return rows


def sleep_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Study-level averages of the night metrics."""
    if not rows:
        return {}
    out: dict[str, Any] = {"nights": len(rows)}
    for key in ("TST_hours", "SOL_min", "WASO_min", "SE_pct", "TIB_min",
                "n_awakenings", "quality", "restedness"):
        st = _stats([r.get(key) for r in rows])
        if st["n"]:
            out[f"{key}_mean"] = st["mean"]
            out[f"{key}_sd"] = st["sd"]
    return out


# ---------------------------------------------------------------------------
# 3. Affect composites (PANAS-style valence split)
# ---------------------------------------------------------------------------
#: The CHiP-D affect grid mixes pleasant and unpleasant adjectives on one 1-7
#: scale. Averaging them together would cancel out, so they are scored as two
#: composites and always reported as a pair.
POSITIVE_ITEMS = {"satisfied", "relaxed", "cheerful", "energetic",
                  "enthusiastic", "calm"}
NEGATIVE_ITEMS = {"upset", "irritated", "listless", "down", "nervous",
                  "bored", "anxious"}


def _valence(item: str) -> Optional[str]:
    key = clean_text(item).casefold()
    head = re.split(r"[ (]", key)[0]
    if head in POSITIVE_ITEMS:
        return "positive"
    if head in NEGATIVE_ITEMS:
        return "negative"
    return None


def affect_composites(surveys: list) -> list[dict[str, Any]]:
    """Per response: mean positive affect and mean negative affect (1-7)."""
    rows: list[dict[str, Any]] = []
    for s in surveys:
        if "affect" not in s.name.casefold() or "test" in s.name.casefold():
            continue
        vmap = s.value_map()
        for r in s.responses:
            if not r.completed:
                continue
            pos, neg = [], []
            for q in s.questions:
                val = _numeric_for(q, vmap, r.answers.get(q["column"]))
                if val is None:
                    continue
                v = _valence(short_item(q.get("text", "")))
                if v == "positive":
                    pos.append(val)
                elif v == "negative":
                    neg.append(val)
            if not pos and not neg:
                continue
            rows.append({
                "participant": s.participant, "survey": s.name,
                "day": r.day, "occasion": r.occasion,
                "positive_affect": round(statistics.fmean(pos), 3) if pos else None,
                "negative_affect": round(statistics.fmean(neg), 3) if neg else None,
                "n_positive_items": len(pos), "n_negative_items": len(neg),
            })
    return rows


def item_valences(items: list[dict[str, Any]]) -> dict[str, Optional[str]]:
    """item label -> 'positive' / 'negative' / None, for colouring the profile."""
    return {r["item"]: _valence(r["item"]) for r in items}
