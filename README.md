# expiwell-metrics

ESM (experience sampling) **compliance and response metrics** from ExpiWell
survey exports, for the Wellcome Trust **CHiP-D** study.

It reads a participant/season **Expiwell folder** and answers: *of the prompts
the protocol scheduled, how many did the participant actually complete — and how
promptly?* Designed as a standalone tool that CD-Compliance-Checks invokes per
participant/season, mirroring `actigraphy-sleep-metrics` and `luminosity-metrics`.

---

## Usage

```bash
python cli.py "<Expiwell folder>" --output "<output dir>" [--season "Autumn 2025"]
```

Common options:

| Flag | Meaning |
|---|---|
| `--schedule FILE.json` | Override the survey protocol (see below) |
| `--expected-days N` | Study length in days (default 15) |
| `--min-response-rate 70` | Response rate %% needed to PASS |
| `--review-margin 10` | Within this %% of the bar → REVIEW |
| `--stem NAME` | Output filename stem (default: participant id) |
| `--no-report` | Skip the PDF |
| `--verbose` | Per-survey parse summary |

### Outputs

| File | Contents |
|---|---|
| `<stem>_compliance.json` | Verdict, summary, per-survey detail, review notes |
| `<stem>_daily_compliance.csv` | One row per survey per study day |
| `<stem>_expiwell_metrics.csv` | One row per survey |
| `<stem>_expiwell_responses.csv` | Tidy long table of every answer |
| `<stem>_expiwell_report.pdf` | Summary · response calendar · timing |

---

## The input format

Each survey is exported as `CD###-Expiwell-Data-<Survey>.csv` with a **four-row
preamble**, not a plain header:

```
row 0   blank for admin cols, then  Survey · Participant · Question 1 · …
row 1   the question TEXT for each question column
row 2   the RESPONSE TYPE (DateTime, Instruction, …)
row 3   the real admin header:
        Start Date · End Date · Time Scheduled · Duration (in seconds) ·
        Day of Survey · Occasion within Day · Finished · Participant ID · …
row 4+  one row per COMPLETED response
```

The parser is schema-driven (it reads rows 1–2 rather than hard-coding question
names), so a new or altered survey needs no code change.

> **Only completed responses are exported.** A missed prompt leaves *no row* —
> `Day of Survey` simply skips a number. The compliance **denominator therefore
> cannot be read from the data**; it comes from the configured schedule below.

---

## Survey types — and why they are scored differently

`Time Scheduled` carries each prompt's window. Whether that window is *fixed* or
*varies* is what distinguishes the kinds of survey, and the tool detects this
from the data to sanity-check your configuration:

| Type | Detected by | Scored as |
|---|---|---|
| `signal` | many **different** windows (randomly timed prompts) | notification attended — response rate **+ latency from the prompt** |
| `interval` | a **single fixed** window every day | did today's diary entry get completed |
| `event` | scheduled only on protocol days | response rate **against those days only** |
| `exclude` | setup/test surveys | not scored |

Defaults derived from the CHiP-D exports:

| Survey | Type | Cadence | Scored |
|---|---|---|---|
| Affect | signal | 2 / day | ✅ |
| PSRS-Affect | signal | 1 / day | ✅ |
| Cognitron | signal | 1 / day | ✅ |
| Sleep-Diary | interval (06:00–11:00) | 1 / day | ✅ |
| Emotional-Events-Diary | interval (19:00–23:59) | 1 / day | ❌ |
| Morning-Passive-Saliva-Drool | event (07:00–12:00) | days 1, 5, 12 | ❌ |
| Evening-Passive-Saliva-Drool | event (19:00–23:59) | days 1, 5, 12 | ❌ |
| Test-Notification | exclude | — | ❌ |

Scoring saliva against **days 1/5/12 only** matters: judged daily it would read
~20% compliant instead of the true 100%.

### Changing the protocol

Copy `survey_schedule.example.json`, edit, and pass `--schedule`. Only the keys
you list change. To include the evening diary in the verdict, for example:

```json
{ "surveys": { "Emotional-Events-Diary": { "scored": true } } }
```

---

## Verdict

Pooling the surveys marked `scored`:

```
PASS    overall response rate >= --min-response-rate      (default 70%)
REVIEW  within --review-margin of that bar                (default 10%)
FAIL    otherwise
```

The report also flags scored surveys with **no responses at all** (a survey that
was never deployed will otherwise silently sink the score) and responses
completed implausibly fast (possible straight-lining).

---

## Install

```bash
python -m pip install -r requirements.txt
```

Parsing is stdlib-only; `matplotlib` is needed only for the PDF report.
