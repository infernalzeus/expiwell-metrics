"""Reader for ExpiWell ESM survey exports.

An ExpiWell per-survey CSV export has a four-row preamble, not a plain header:

    row 0   partial header — blank for the admin columns, then
            ``Survey``, ``Participant``, ``Question 1`` ...
    row 1   the question *text* for each question column
    row 2   the *response type* for each question column (DateTime, Instruction, ...)
    row 3   the real header for the admin columns:
            ``Start Date`` ``End Date`` ``Time Scheduled`` ``Duration (in seconds)``
            ``Day of Survey`` ``Occasion within Day`` ``Finished`` ``Participant ID``
            ``Location - Lat`` ``Location - Long`` ``No Login`` ``Group Code``
    row 4+  one row per **completed response**

Two properties of the export drive the whole design:

* Only completed responses are present. A missed prompt leaves **no row at all**
  (``Day of Survey`` simply skips a number), so the compliance denominator can
  never be read from the file — it comes from the survey schedule (see
  ``schedule.py``).
* ``Time Scheduled`` carries the prompt window (``<start> - <end>``). Whether that
  window is *fixed* every day or *varies* is what distinguishes an interval-
  contingent diary from a signal-contingent (notification) prompt.

The reader is deliberately schema-driven rather than hard-coding question names
per survey, so a new or altered survey needs no code change.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Admin columns that live in the row-3 header.
ADMIN_COLUMNS = (
    "Start Date",
    "End Date",
    "Time Scheduled",
    "Duration (in seconds)",
    "Day of Survey",
    "Occasion within Day",
    "Finished",
    "Participant ID",
    "Location - Lat",
    "Location - Long",
    "No Login",
    "Group Code",
)

# ExpiWell writes 12-hour timestamps, e.g. "09/28/2025 07:31AM".
_TS_FORMATS = ("%m/%d/%Y %I:%M%p", "%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M")
# Tolerates the separator drift seen across seasons: "CD011-Expiwell-Data-X",
# "CD011- Expiwell-Data-X" (stray space), underscores, etc.
_FILENAME_RE = re.compile(
    r"^(?P<pid>.*?)[-_ ]*Expiwell[-_ ]*Data[-_ ]*(?P<survey>.+)$", re.IGNORECASE
)


def parse_timestamp(value: str) -> Optional[datetime]:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_window(value: str) -> tuple[Optional[datetime], Optional[datetime]]:
    """Split a ``Time Scheduled`` cell into (window_start, window_end)."""
    value = (value or "").strip()
    if not value:
        return None, None
    parts = [p.strip() for p in value.split(" - ")]
    if len(parts) != 2:
        return None, None
    return parse_timestamp(parts[0]), parse_timestamp(parts[1])


def _to_float(value: str) -> Optional[float]:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_int(value: str) -> Optional[int]:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


@dataclass
class Response:
    """One completed survey response."""

    start: Optional[datetime]
    end: Optional[datetime]
    window_start: Optional[datetime]
    window_end: Optional[datetime]
    duration_sec: Optional[float]
    day: Optional[int]
    occasion: Optional[int]
    finished: str
    participant_id: str
    answers: dict[str, Any] = field(default_factory=dict)

    @property
    def completed(self) -> bool:
        return str(self.finished).strip().lower() == "finished"

    @property
    def latency_minutes(self) -> Optional[float]:
        """Minutes from the opening of the prompt window to the response."""
        if self.start is None or self.window_start is None:
            return None
        return (self.start - self.window_start).total_seconds() / 60.0

    @property
    def in_window(self) -> Optional[bool]:
        if self.start is None or self.window_start is None or self.window_end is None:
            return None
        return self.window_start <= self.start <= self.window_end

    @property
    def window_minutes(self) -> Optional[float]:
        if self.window_start is None or self.window_end is None:
            return None
        return (self.window_end - self.window_start).total_seconds() / 60.0


@dataclass
class Survey:
    """One parsed survey export."""

    name: str                      # e.g. "Sleep-Diary"
    participant: str               # e.g. "CD011"
    path: Path
    description: str = ""
    questions: list[dict[str, str]] = field(default_factory=list)  # column/text/type
    responses: list[Response] = field(default_factory=list)

    @property
    def n_responses(self) -> int:
        return len(self.responses)

    @property
    def days_present(self) -> list[int]:
        return sorted({r.day for r in self.responses if r.day is not None})

    @property
    def occasions_present(self) -> list[int]:
        return sorted({r.occasion for r in self.responses if r.occasion is not None})

    def window_signature(self) -> list[str]:
        """Distinct clock-time windows, e.g. ['06:00-11:00'].

        A single signature across many days => a fixed (interval-contingent)
        window; many distinct signatures => randomly-timed signal-contingent
        prompts. This is what `schedule.classify` uses to detect the survey type.
        """
        sigs = set()
        for r in self.responses:
            if r.window_start and r.window_end:
                sigs.add(
                    f"{r.window_start.strftime('%H:%M')}-{r.window_end.strftime('%H:%M')}"
                )
        return sorted(sigs)


def _find_header_row(rows: list[list[str]]) -> int:
    """Index of the row holding the admin header (normally 3)."""
    for i, row in enumerate(rows[:12]):
        cells = [c.strip() for c in row[:4]]
        if "Start Date" in cells:
            return i
    return 3


def survey_name_from_path(path: Path) -> tuple[str, str]:
    """('CD011', 'Sleep-Diary') from 'CD011-Expiwell-Data-Sleep-Diary.csv'."""
    stem = Path(path).stem
    m = _FILENAME_RE.match(stem)
    if m:
        return m.group("pid"), m.group("survey")
    return "", stem


def read_survey(path: Path) -> Survey:
    """Parse one ExpiWell survey CSV (tolerates an export with zero responses)."""
    path = Path(path)
    participant, name = survey_name_from_path(path)
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))

    survey = Survey(name=name, participant=participant, path=path)
    if not rows:
        return survey

    hdr_i = _find_header_row(rows)
    header = [c.strip() for c in rows[hdr_i]]
    qtext = rows[1] if len(rows) > 1 else []
    qtype = rows[2] if len(rows) > 2 else []
    label_row = rows[0] if rows else []

    # Column indices for the admin fields.
    idx = {name_: i for i, name_ in enumerate(header) if name_}

    # Question columns are the ones labelled in row 0 beyond 'Survey'/'Participant'.
    q_cols: list[int] = []
    for i, lab in enumerate(label_row):
        lab = (lab or "").strip()
        if lab and lab not in ("Survey", "Participant"):
            q_cols.append(i)

    def _cell(row: list[str], i: Optional[int]) -> str:
        if i is None or i >= len(row):
            return ""
        return (row[i] or "").strip()

    # Survey description: the question-text row under the 'Question 1' column.
    if q_cols:
        first_q = q_cols[0]
        if first_q < len(qtext):
            survey.description = (qtext[first_q] or "").replace("\xa0", " ").strip()

    for i in q_cols:
        survey.questions.append(
            {
                "column": (label_row[i] or "").strip(),
                "text": ((qtext[i] if i < len(qtext) else "") or "").replace("\xa0", " ").strip(),
                "type": ((qtype[i] if i < len(qtype) else "") or "").strip(),
            }
        )

    for row in rows[hdr_i + 1:]:
        if not any((c or "").strip() for c in row):
            continue
        ws, we = parse_window(_cell(row, idx.get("Time Scheduled")))
        answers = {}
        for i in q_cols:
            key = (label_row[i] or "").strip()
            answers[key] = _cell(row, i)
        survey.responses.append(
            Response(
                start=parse_timestamp(_cell(row, idx.get("Start Date"))),
                end=parse_timestamp(_cell(row, idx.get("End Date"))),
                window_start=ws,
                window_end=we,
                duration_sec=_to_float(_cell(row, idx.get("Duration (in seconds)"))),
                day=_to_int(_cell(row, idx.get("Day of Survey"))),
                occasion=_to_int(_cell(row, idx.get("Occasion within Day"))),
                finished=_cell(row, idx.get("Finished")),
                participant_id=_cell(row, idx.get("Participant ID")),
                answers=answers,
            )
        )
    return survey


def read_folder(folder: Path) -> list[Survey]:
    """Parse every ``*-Expiwell-Data-*.csv`` in a participant/season folder.

    ZIP bundles that sit alongside (the raw ExpiWell download) are ignored — the
    extracted CSVs carry the same content plus the participant prefix.
    """
    folder = Path(folder)
    seen: set[Path] = set()
    surveys: list[Survey] = []
    # Any CSV whose name mentions ExpiWell, however it is punctuated.
    for p in sorted(folder.glob("*.csv")):
        if "expiwell" in p.name.lower():
            seen.add(p)
            surveys.append(read_survey(p))
    if not surveys:  # fall back to any CSV that parses with the ExpiWell preamble
        for p in sorted(folder.glob("*.csv")):
            if p in seen:
                continue
            s = read_survey(p)
            if s.questions:
                surveys.append(s)
    return surveys


def participant_of(surveys: list[Survey], folder: Path) -> str:
    for s in surveys:
        if s.participant:
            return s.participant
    return Path(folder).name
