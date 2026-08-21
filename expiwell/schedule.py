"""Survey schedule — the compliance denominator, and what kind of survey each is.

ExpiWell exports contain only *completed* responses, so "how many prompts were
expected" cannot be read from the data. It is therefore **configured** here (and
overridable with ``--schedule my_schedule.json``), while the data is still used
to *detect* each survey's type so the configuration can be sanity-checked.

Survey types
------------
``signal``    Notification-driven prompt at a randomly-timed window ("signal-
              contingent"). Detected by many distinct ``Time Scheduled`` windows.
              Response latency from the prompt is meaningful — this is the
              "did they attend the notification" case.
``interval``  A diary with the *same* window every day ("interval-contingent"),
              e.g. a morning sleep diary. Detected by a single fixed window.
              Compliance = did they complete that day's entry.
``event``     Only scheduled on specific protocol days (e.g. saliva sampling on
              days 1/5/12). Scored **against those days only** — scoring it daily
              would wrongly report ~20% compliance.
``exclude``   Setup/test surveys that are not part of the protocol.

Defaults below were derived from the CHiP-D exports (CD008 sample and CD011
staging); adjust them per study rather than editing code.
"""
from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

SIGNAL, INTERVAL, EVENT, EXCLUDE = "signal", "interval", "event", "exclude"

#: Study length in days (max ``Day of Survey`` observed in the CHiP-D exports).
DEFAULT_EXPECTED_DAYS = 15

#: Per-survey protocol. ``scored`` controls whether a survey contributes to the
#: overall Expiwell verdict; unscored surveys are still parsed and reported.
DEFAULT_SURVEYS: dict[str, dict[str, Any]] = {
    "Affect": {"type": SIGNAL, "prompts_per_day": 2, "scored": True},
    "PSRS-Affect": {"type": SIGNAL, "prompts_per_day": 1, "scored": True},
    "Cognitron": {"type": SIGNAL, "prompts_per_day": 1, "scored": True},
    "Sleep-Diary": {"type": INTERVAL, "prompts_per_day": 1, "scored": True},
    # Fixed 19:00-23:59 window daily in the exports, so it *looks* scheduled;
    # left unscored by protocol decision. Flip "scored" to true to include it.
    "Emotional-Events-Diary": {"type": INTERVAL, "prompts_per_day": 1, "scored": False},
    "Morning-Passive-Saliva-Drool": {
        "type": EVENT, "prompts_per_day": 1, "on_days": [1, 5, 12], "scored": False,
    },
    "Evening-Passive-Saliva-Drool": {
        "type": EVENT, "prompts_per_day": 1, "on_days": [1, 5, 12], "scored": False,
    },
    "Test-Notification": {"type": EXCLUDE, "prompts_per_day": 0, "scored": False},
}



# Survey filenames drift between seasons: "Sleep-Diary", "Sleep_Diary-S2",
# "Affect-S3", even a typo'd "Test-NotifictionsS3_Visit". Canonicalising the name
# (drop the season tag, unify separators) lets one schedule serve every season.
# The tag appears at either end depending on the season:
#   trailing  "Sleep_Diary-S2", "Test-NotifictionsS3_Visit"
#   leading   "S4-Sleep_Diary"
_SEASON_TAG = re.compile(r"[-_ ]*S\d+(?:[-_ ].*)?$", re.IGNORECASE)
_SEASON_TAG_LEAD = re.compile(r"^S\d+[-_ ]+", re.IGNORECASE)


def canonical_name(raw: str) -> str:
    """'Sleep_Diary-S2' and 'S4-Sleep_Diary' both -> 'Sleep-Diary'."""
    n = _SEASON_TAG_LEAD.sub("", (raw or "").strip())
    n = _SEASON_TAG.sub("", n)
    n = n.replace("_", "-").replace(" ", "-")
    n = re.sub(r"-+", "-", n).strip("-")
    return n


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", canonical_name(name).lower())


@dataclass
class SurveyPlan:
    name: str
    type: str = SIGNAL
    prompts_per_day: int = 1
    on_days: Optional[list[int]] = None      # event-tied surveys only
    expected_days: int = DEFAULT_EXPECTED_DAYS
    scored: bool = True

    def expected_responses(self) -> int:
        """How many completed responses the protocol expects."""
        if self.type == EXCLUDE:
            return 0
        if self.type == EVENT:
            return len(self.on_days or []) * max(self.prompts_per_day, 0)
        return max(self.expected_days, 0) * max(self.prompts_per_day, 0)

    def expected_days_list(self) -> list[int]:
        if self.type == EVENT:
            return sorted(self.on_days or [])
        return list(range(1, max(self.expected_days, 0) + 1))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "prompts_per_day": self.prompts_per_day,
            "on_days": self.on_days,
            "expected_days": self.expected_days,
            "scored": self.scored,
            "expected_responses": self.expected_responses(),
        }


@dataclass
class Schedule:
    expected_days: int = DEFAULT_EXPECTED_DAYS
    plans: dict[str, SurveyPlan] = field(default_factory=dict)

    def plan_for(self, survey_name: str) -> SurveyPlan:
        """Plan for a survey, matching across season/separator naming drift.

        Tries the literal name, then the canonical form, then a close match (so a
        typo like 'Test-Notifictions' still resolves). Unknown surveys fall back
        to unscored so a new survey never silently changes a verdict.
        """
        if survey_name in self.plans:
            return self.plans[survey_name]
        wanted = _key(survey_name)
        by_key = {_key(k): v for k, v in self.plans.items()}
        if wanted in by_key:
            return by_key[wanted]
        close = difflib.get_close_matches(wanted, list(by_key), n=1, cutoff=0.85)
        if close:
            return by_key[close[0]]
        return SurveyPlan(
            name=survey_name, type=SIGNAL, prompts_per_day=1,
            expected_days=self.expected_days, scored=False,
        )


def default_schedule(expected_days: int = DEFAULT_EXPECTED_DAYS) -> Schedule:
    plans = {}
    for name, spec in DEFAULT_SURVEYS.items():
        plans[name] = SurveyPlan(
            name=name,
            type=spec.get("type", SIGNAL),
            prompts_per_day=int(spec.get("prompts_per_day", 1)),
            on_days=spec.get("on_days"),
            expected_days=int(spec.get("expected_days", expected_days)),
            scored=bool(spec.get("scored", True)),
        )
    return Schedule(expected_days=expected_days, plans=plans)


def load_schedule(path: Optional[Path], expected_days: Optional[int] = None) -> Schedule:
    """Default schedule, optionally overlaid with a JSON file.

    JSON shape::

        {"expected_days": 15,
         "surveys": {"Affect": {"type": "signal", "prompts_per_day": 2,
                                "scored": true}}}
    """
    sched = default_schedule(expected_days or DEFAULT_EXPECTED_DAYS)
    if path:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if raw.get("expected_days"):
            sched.expected_days = int(raw["expected_days"])
            for p in sched.plans.values():
                p.expected_days = sched.expected_days
        for name, spec in (raw.get("surveys") or {}).items():
            base = sched.plans.get(name) or SurveyPlan(
                name=name, expected_days=sched.expected_days
            )
            base.name = name
            base.type = spec.get("type", base.type)
            base.prompts_per_day = int(spec.get("prompts_per_day", base.prompts_per_day))
            base.on_days = spec.get("on_days", base.on_days)
            base.expected_days = int(spec.get("expected_days", base.expected_days))
            base.scored = bool(spec.get("scored", base.scored))
            sched.plans[name] = base
    if expected_days:  # explicit CLI flag wins over the file
        sched.expected_days = expected_days
        for p in sched.plans.values():
            if p.type != EVENT:
                p.expected_days = expected_days
    return sched


def classify(survey) -> dict[str, Any]:
    """Detect a survey's type from its data, to validate the configured plan.

    A single distinct ``Time Scheduled`` clock window across many days means the
    prompt is fixed (interval-contingent); several distinct windows mean it is
    randomly timed (signal-contingent / notification-driven).
    """
    sigs = survey.window_signature()
    days = survey.days_present
    occ = survey.occasions_present
    if not survey.responses:
        detected = "unknown (no responses)"
    elif len(sigs) == 1 and len(days) > 2:
        detected = INTERVAL
    elif len(sigs) > 1:
        detected = SIGNAL
    else:
        detected = "unknown"
    return {
        "detected_type": detected,
        "distinct_windows": sigs[:6],
        "n_distinct_windows": len(sigs),
        "days_present": days,
        "day_span": [min(days), max(days)] if days else None,
        "occasions_per_day_observed": len(occ),
        "n_responses": survey.n_responses,
    }
