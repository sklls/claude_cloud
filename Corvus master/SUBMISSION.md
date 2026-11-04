# Corvus Health — Intake Assistant (Session 3 submission)

A working prototype that reads a scanned pre-authorisation packet (PDF), checks
it against Meena's checklist, and writes one JSON record per packet saying
whether it is **complete**, **incomplete** (and exactly which items), or
**needs_review** (and why).

**The one hard rule:** it never approves, rejects, or predicts the outcome of a
request. It only reads files and writes result records. A processor decides.

---

## 1. How it works — the model reads, code checks

The scans are image-only (some handwritten; some notes in Hindi, Telugu or
Tamil). The work is split by what each half is good at:

- **The model reads.** It turns each scanned page into a structured extraction
  — the form fields, which documents are attached, the dates, the eye/knee, the
  totals. It reports only what is on the page; if it cannot read something, it
  flags it rather than guessing.
- **Code checks.** `check_packet.py` applies every checklist rule to that
  extraction: required items per treatment, date windows, cost agreement, ICD-10
  consistency, same eye/knee throughout, standalone-document rules. Deterministic
  and testable — the verdict is never a model opinion.

PDFs are rendered to page images with PyMuPDF before reading, so the pipeline
does not depend on poppler being installed.

### Files handed in

| Path | What it is |
|------|-----------|
| `CLAUDE.md` | The output contract and the read/check split |
| `.claude/skills/corvus-checklist/SKILL.md` | When and how to apply the checklist |
| `.claude/skills/corvus-checklist/checklist.json` | **Meena's spreadsheet exported as data** — every item ID, per-treatment required lists, and the rule config |
| `.claude/skills/corvus-checklist/check_packet.py` | Applies every rule → `status` + `missing_items` |
| `run_all.py` | Bulk worker: model extracts → code checks → `results/<id>.json` |
| `run_checks.py` | Scores `results/` against the labelled answers (counts false completes) |
| `demo.py` | Agent SDK — one packet end to end, prints the record and cost |
| `results/` | One JSON record per packet (15 included) |
| `samples/` | A hand-made extraction, to run the checker offline with no API key |

---

## 2. How to run

No Anthropic API key required — the Agent SDK runs on the Claude Code login.

```bash
pip install -r requirements.txt
python demo.py D01            # one packet, end to end, prints record + cost
python run_all.py             # all packets -> results/<id>.json
python run_checks.py          # score against the labelled answers file
```

Check the rules offline, no model/cost:

```bash
python .claude/skills/corvus-checklist/check_packet.py samples/D01_extracted.json
```

---

## 3. Score

Run over the 15 labelled packets. **Verdicts produced (15/15):**

| Packet | Treatment | Status | Missing items |
|--------|-----------|--------|---------------|
| D01 | cataract | complete | — |
| D03 | cataract | complete | — |
| D04 | tka | complete | — |
| D05 | tka | **incomplete** | `doc.xray_knee` |
| D06 | tka | complete | — |
| D07 | appendectomy | complete | — |
| D08 | appendectomy | **incomplete** | `form.patient_signature` |
| D09 | appendectomy | complete | — |
| D11 | delivery | complete | — |
| D12 | delivery | complete | — |
| D13 | ptca | complete | — |
| D15 | ptca | complete | — |
| D16 | cataract | **incomplete** | `form.icd10` |
| D18 | delivery | complete | — |
| D20 | cataract | complete | — |

**Summary:** 12 complete, 3 incomplete, 0 needs_review.

**Measured accuracy against the answer key:** pending. The
`Session 3 Labelled Packets (for groups).xlsx` answer file was not in the
materials provided, so `run_checks.py` cannot yet print the official
correct/false-complete numbers. The moment it is dropped into the project,
`python run_checks.py` prints:

```
Packets correct: N of 15
False completes: n   (said complete, but something was missing)
Wrong or missing item IDs: n packets
Needs review: n
```

A manual eyeball of the three "incomplete" verdicts confirms them as true
catches — e.g. **D16's ICD-10 field is genuinely blank on the form (p.1)**.

---

## 4. Cost

Measured with the Agent SDK (Sonnet reader, via the Claude Code login):

- **~$0.14 per packet** (e.g. D01 $0.15, D06 $0.14; 5–8 turns each).
- Corvus receives about **1,800 requests/day** → roughly **$250/day**, on the
  order of **$7,600/month**, for the reading step.

What this means: the completeness pass is cheap enough to run on every request.
The cost scales with pages read, so the biggest lever is reading only the pages
a check needs. (Figures are subscription-metered; list API pricing would differ.)

---

## 5. One failure — found and fixed

**Packet D06 (tka), before the fix: a false incomplete.**

D06 carries **two cost estimates** — an unsigned draft (p.4) and a signed, sealed
**REVISED** estimate (p.5). The first version of the checker only looked at the
first estimate, saw it was unsigned, and reported the packet incomplete
(`doc.cost_estimate`). That is the wrong answer: a valid signed estimate exists.

- **Why it happened:** the checker assumed one cost estimate per packet.
- **The fix:** it now considers *every* attached estimate and passes the item if
  **any** qualifies (on letterhead, signed, total within 10%); the extractor is
  told to record each estimate separately. D06 now reads **complete**.

**Residual risk:** the remaining failure mode is a mis-read on a hard scan — a
handwritten or multilingual note, a smudged field. The design contains this: when
the reader cannot judge a required item it is flagged, and the packet goes to
**needs_review** with a reason, never silently to "complete". A false complete is
the one mistake that can hurt a patient, so uncertainty never resolves that way.

---

## 6. Verification approach

- `run_checks.py` compares `results/` with the labelled answers and prints a
  score, with **false completes counted separately** (a `complete` verdict on a
  packet that was really incomplete). It exits non-zero if any false complete
  exists.
- The checker has an offline self-test: it passes a complete packet and fires
  correctly on 13 rule-breaking variations (blank/mismatched member ID, wrong
  ICD-10 chapter, note too old or after admission, cost >10% off, unsigned
  estimate, missing/wrong-eye biometry, missing line item, illegible field →
  needs_review, unknown treatment → needs_review).
- Malformed model output (a bare-string `uncertain`, a stray document entry) is
  tolerated: one odd packet becomes `needs_review`, never a crashed batch.

---

## 7. Safety checklist

- [x] Never approves, rejects or promises an outcome — reads files, writes records only.
- [x] Every record uses the exact field names and formats in the brief.
- [x] Missing items use Meena's item IDs.
- [x] The checks are code, in `check_packet.py`, not just a prompt.
- [x] `run_checks.py` runs and prints the score, including false completes (needs the answer file).
- [x] Uncertain packets go to `needs_review`, with a reason.
- [x] Every SDK run sets `max_turns` and `max_budget_usd`.
- [x] No API keys in the code or files (`.env` / `*.key` git-ignored).

---

## 8. Not built (per the brief)

No approve/reject/send actions; no connection to Corvus's systems (Session 4);
a command and a folder of JSON records is the interface. A local web console
(`app.py`) is in progress as an optional demo aid and is not part of this
submission.
