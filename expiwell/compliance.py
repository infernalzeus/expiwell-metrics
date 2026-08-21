"""ESM compliance from ExpiWell exports.

Compliance for experience sampling is a *response rate*: of the prompts the
protocol scheduled, how many did the participant actually complete. Because the
export lists only completed responses, the denominator comes from the configured
schedule (``schedule.py``) and the numerator from the parsed rows.

Per survey we report:

* **response rate** — completed / expected, and the per-day breakdown
* **timeliness** — for notification-driven (signal) surveys, how long after the
  prompt window opened the response arrived, and what share landed inside the
  window at all
* **effort** — median completion duration, a rough quality signal (implausibly
  fast responses suggest straight-lining)

The overall verdict pools the surveys flagged ``scored`` in the schedule:

    PASS    overall response rate >= min_response_rate_pct
    REVIEW  within review_margin_pct of that bar
    FAIL    otherwise
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Optional

from .schedule import EVENT, EXCLUDE, Schedule, classify


@dataclass
class ComplianceParams:
    min_response_rate_pct: float = 70.0
    review_margin_pct: float = 10.0
    #: A response faster than this is flagged as implausibly quick (quality only).
    min_plausible_duration_sec: float = 5.0


def _median(values: list[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return round(statistics.median(vals), 2) if vals else None


def _survey_compliance(survey, plan, params: ComplianceParams) -> dict[str, Any]:
    """Per-survey response rate, timeliness and per-day table."""
    completed = [r for r in survey.responses if r.completed]
    expected = plan.expected_responses()
    n_done = len(completed)
    rate = (100.0 * n_done / expected) if expected else None

    # --- per-day table -----------------------------------------------------
    by_day: dict[int, int] = {}
    for r in completed:
        if r.day is not None:
            by_day[r.day] = by_day.get(r.day, 0) + 1
    per_day = []
    for day in plan.expected_days_list():
        exp = plan.prompts_per_day
        got = by_day.get(day, 0)
        per_day.append(
            {
                "survey": survey.name,
                "day": day,
                "expected": exp,
                "completed": got,
                "pct": round(min(100.0, 100.0 * got / exp), 2) if exp else None,
                "complete_day": bool(exp and got >= exp),
                "missed": max(0, exp - got),
            }
        )
    # Responses on days outside the protocol (e.g. an extra saliva day).
    extra_days = sorted(d for d in by_day if d not in set(plan.expected_days_list()))

    # --- timeliness --------------------------------------------------------
    latencies = [r.latency_minutes for r in completed if r.latency_minutes is not None]
    in_window = [r.in_window for r in completed if r.in_window is not None]
    durations = [r.duration_sec for r in completed if r.duration_sec is not None]

    return {
        "survey": survey.name,
        "type": plan.type,
        "scored": plan.scored,
        "expected": expected,
        "completed": n_done,
        "missed": max(0, expected - n_done) if expected else None,
        "response_rate_pct": round(min(100.0, rate), 2) if rate is not None else None,
        "response_rate_raw_pct": round(rate, 2) if rate is not None else None,
        "days_expected": len(plan.expected_days_list()),
        "days_with_response": len(by_day),
        "complete_days": sum(1 for d in per_day if d["complete_day"]),
        "extra_days": extra_days,
        # timeliness — most meaningful for signal-contingent prompts
        "median_latency_min": _median(latencies),
        "pct_within_window": (
            round(100.0 * sum(1 for x in in_window if x) / len(in_window), 2)
            if in_window else None
        ),
        "median_duration_sec": _median(durations),
        "n_implausibly_fast": sum(
            1 for d in durations if d < params.min_plausible_duration_sec
        ),
        "detected": classify(survey),
        "per_day": per_day,
    }


def evaluate(surveys: list, schedule: Schedule, params: ComplianceParams) -> dict[str, Any]:
    """Full compliance result for one participant/season Expiwell folder."""
    per_survey: list[dict[str, Any]] = []
    for s in surveys:
        plan = schedule.plan_for(s.name)
        if plan.type == EXCLUDE:
            per_survey.append(
                {
                    "survey": s.name, "type": EXCLUDE, "scored": False,
                    "expected": 0, "completed": len([r for r in s.responses if r.completed]),
                    "response_rate_pct": None, "per_day": [],
                    "detected": classify(s), "note": "excluded from scoring by schedule",
                }
            )
            continue
        per_survey.append(_survey_compliance(s, plan, params))

    scored = [p for p in per_survey if p.get("scored")]
    total_expected = sum(p["expected"] or 0 for p in scored)
    total_completed = sum(min(p["completed"], p["expected"]) if p["expected"] else 0
                          for p in scored)
    overall = (100.0 * total_completed / total_expected) if total_expected else 0.0

    if not scored or not total_expected:
        verdict = "ERROR"
    elif overall >= params.min_response_rate_pct:
        verdict = "PASS"
    elif overall >= params.min_response_rate_pct - params.review_margin_pct:
        verdict = "REVIEW"
    else:
        verdict = "FAIL"

    # Notes worth surfacing to a human reviewer.
    notes: list[str] = []
    empty = [p["survey"] for p in per_survey if p.get("scored") and not p["completed"]]
    if empty:
        notes.append(
            f"Scored survey(s) with NO responses at all: {', '.join(empty)} — "
            "check the survey was actually deployed for this participant."
        )
    for p in per_survey:
        det = p.get("detected", {}).get("detected_type")
        if p.get("scored") and det in ("signal", "interval") and det != p.get("type"):
            notes.append(
                f"{p['survey']}: configured as '{p['type']}' but the data looks "
                f"'{det}' ({p['detected']['n_distinct_windows']} distinct prompt "
                "windows) — verify the schedule config."
            )
    fast = sum(p.get("n_implausibly_fast", 0) or 0 for p in per_survey)
    if fast:
        notes.append(f"{fast} response(s) completed implausibly fast (<"
                     f"{params.min_plausible_duration_sec:g}s) — possible straight-lining.")

    summary = {
        "verdict": verdict,
        "overall_response_rate_pct": round(overall, 2),
        # Device-agnostic alias: the CHiP-D dashboard rolls every device up on
        # `pct_compliance_mean`, so expose the response rate under that name too.
        "pct_compliance_mean": round(overall, 2),
        "total_expected": total_expected,
        "total_completed": total_completed,
        "total_missed": max(0, total_expected - total_completed),
        "scored_surveys": [p["survey"] for p in scored],
        "n_surveys_found": len(per_survey),
        "expected_days": schedule.expected_days,
        "min_response_rate_pct": params.min_response_rate_pct,
    }
    return {
        "device": "expiwell",
        "verdict": verdict,
        "summary": summary,
        "per_survey": per_survey,
        "parameters": {
            "rule": "ESM response-rate against configured schedule",
            "min_response_rate_pct": params.min_response_rate_pct,
            "review_margin_pct": params.review_margin_pct,
            "expected_days": schedule.expected_days,
            "schedule": {n: p.to_dict() for n, p in schedule.plans.items()},
        },
        "notes": notes,
    }


def daily_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten every survey's per-day table into the daily compliance CSV."""
    rows: list[dict[str, Any]] = []
    for p in result["per_survey"]:
        for d in p.get("per_day", []):
            rows.append({**d, "type": p.get("type"), "scored": p.get("scored")})
    return rows


def survey_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-survey summary rows for the metrics CSV (drops nested structures)."""
    rows = []
    for p in result["per_survey"]:
        det = p.get("detected", {}) or {}
        rows.append(
            {
                "survey": p.get("survey"),
                "type": p.get("type"),
                "scored": p.get("scored"),
                "expected": p.get("expected"),
                "completed": p.get("completed"),
                "missed": p.get("missed"),
                "response_rate_pct": p.get("response_rate_pct"),
                "days_expected": p.get("days_expected"),
                "days_with_response": p.get("days_with_response"),
                "complete_days": p.get("complete_days"),
                "median_latency_min": p.get("median_latency_min"),
                "pct_within_window": p.get("pct_within_window"),
                "median_duration_sec": p.get("median_duration_sec"),
                "detected_type": det.get("detected_type"),
                "n_distinct_windows": det.get("n_distinct_windows"),
            }
        )
    return rows
