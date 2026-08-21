#!/usr/bin/env python
"""expiwell-metrics — ESM compliance and response metrics from ExpiWell exports.

Reads a participant/season **Expiwell folder** (the 8 ``*-Expiwell-Data-*.csv``
survey exports) and writes compliance, per-survey metrics, a tidy response table
and a PDF report.

    python cli.py "<Expiwell folder>" --output "<output dir>"

Outputs (named after the participant stem, mirroring the other CHiP-D tools):

    <stem>_compliance.json            verdict + summary + per-survey detail
    <stem>_daily_compliance.csv       one row per survey per study day
    <stem>_expiwell_metrics.csv       one row per survey
    <stem>_expiwell_responses.csv     tidy long table of every answer
    <stem>_expiwell_report.pdf        multi-page report

Because an ExpiWell export contains only *completed* responses, the compliance
denominator comes from the configured schedule — see ``schedule.py`` for the
defaults and ``--schedule`` to override them per study.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from expiwell import compliance as comp_mod  # noqa: E402
from expiwell import parser as parser_mod  # noqa: E402
from expiwell import report as report_mod  # noqa: E402
from expiwell import schedule as schedule_mod  # noqa: E402


def _write_csv(path: Path, rows: list[dict]) -> Path:
    import csv as _csv

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return path
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = _csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    return path


def _response_rows(surveys) -> list[dict]:
    """Tidy long table: one row per answered question."""
    rows = []
    for s in surveys:
        for r in s.responses:
            base = {
                "participant": s.participant,
                "survey": s.name,
                "day": r.day,
                "occasion": r.occasion,
                "start": r.start.isoformat(sep=" ") if r.start else "",
                "window_start": r.window_start.isoformat(sep=" ") if r.window_start else "",
                "window_end": r.window_end.isoformat(sep=" ") if r.window_end else "",
                "latency_min": (round(r.latency_minutes, 2)
                                if r.latency_minutes is not None else ""),
                "in_window": r.in_window if r.in_window is not None else "",
                "duration_sec": r.duration_sec if r.duration_sec is not None else "",
                "finished": r.finished,
            }
            qtext = {q["column"]: q["text"] for q in s.questions}
            for col, val in r.answers.items():
                if val == "":
                    continue
                rows.append({**base, "question": col,
                             "question_text": qtext.get(col, "")[:200], "answer": val})
    return rows


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="expiwell-metrics",
        description="ESM compliance + response metrics from an ExpiWell folder.",
    )
    p.add_argument("input", type=Path, help="Participant/season Expiwell folder")
    p.add_argument("--output", type=Path, required=True, help="Output directory")
    p.add_argument("--stem", default=None,
                   help="Output filename stem (default: participant id from the CSVs)")
    p.add_argument("--season", default="", help="Season label, used in the report title")
    p.add_argument("--schedule", type=Path, default=None,
                   help="JSON file overriding the survey schedule / expected counts")
    p.add_argument("--expected-days", type=int, default=None,
                   help="Study length in days (overrides the schedule default)")
    p.add_argument("--min-response-rate", type=float, default=70.0,
                   help="Response rate %% needed to PASS (default 70)")
    p.add_argument("--review-margin", type=float, default=10.0,
                   help="Within this %% of the bar => REVIEW (default 10)")
    p.add_argument("--min-duration", type=float, default=5.0,
                   help="Responses faster than this many seconds are flagged")
    p.add_argument("--no-report", action="store_true", help="Skip the PDF report")
    p.add_argument("--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    folder = Path(args.input)
    if not folder.is_dir():
        print(f"ERROR: not a folder: {folder}", file=sys.stderr)
        return 2

    surveys = parser_mod.read_folder(folder)
    if not surveys:
        print(f"ERROR: no ExpiWell survey CSVs found in {folder}", file=sys.stderr)
        return 2
    participant = parser_mod.participant_of(surveys, folder)
    stem = args.stem or participant or folder.name
    if args.verbose:
        print(f"Participant: {participant}   surveys: {len(surveys)}")
        for s in surveys:
            print(f"  - {s.name:34s} responses={s.n_responses:3d} "
                  f"windows={len(s.window_signature())}")

    sched = schedule_mod.load_schedule(args.schedule, args.expected_days)
    params = comp_mod.ComplianceParams(
        min_response_rate_pct=args.min_response_rate,
        review_margin_pct=args.review_margin,
        min_plausible_duration_sec=args.min_duration,
    )
    result = comp_mod.evaluate(surveys, sched, params)
    # Per-day rows live on the compliance object too, so the dashboard can read
    # them without opening the CSV.
    result["per_day"] = comp_mod.daily_rows(result)
    context = {
        "participant": participant,
        "season": args.season,
        "input_folder": str(folder),
        "surveys_found": [s.name for s in surveys],
    }
    result["context"] = context
    # Same envelope as the other CHiP-D tools: {"context": ..., "compliance": ...}
    envelope = {"context": context, "compliance": result}

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    comp_json = out / f"{stem}_compliance.json"
    comp_json.write_text(json.dumps(envelope, indent=2, default=str), encoding="utf-8")
    _write_csv(out / f"{stem}_daily_compliance.csv", comp_mod.daily_rows(result))
    _write_csv(out / f"{stem}_expiwell_metrics.csv", comp_mod.survey_rows(result))
    _write_csv(out / f"{stem}_expiwell_responses.csv", _response_rows(surveys))

    if not args.no_report:
        try:
            report_mod.build_report(out / f"{stem}_expiwell_report.pdf", result,
                                    surveys, participant, args.season)
        except Exception as exc:  # a failed plot must not lose the compliance result
            print(f"WARNING: report generation failed: {exc}", file=sys.stderr)

    s = result["summary"]
    print(f"{stem}: {result['verdict']}  "
          f"{s['overall_response_rate_pct']:.1f}% "
          f"({s['total_completed']}/{s['total_expected']} prompts)")
    for note in result.get("notes", []):
        print(f"  note: {note}")
    if args.verbose:
        print(f"Outputs written to: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
