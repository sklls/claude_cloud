# Corvus Health — Intake Assistant (Session 3 prototype)

Reads a scanned pre-authorisation packet (PDF), checks it against Meena's
checklist, and writes one JSON record saying whether it is **complete**,
**incomplete** (and exactly which items), or **needs_review** (and why).

**It never approves, rejects, or predicts the outcome of a request.** A
processor decides. The prototype only reads files and writes results.

## The design in one line

**The model reads, code checks.** The model turns each scanned packet into a
structured extraction (what is on the pages). Deterministic code
(`check_packet.py`) applies every checklist rule to that extraction. This is
what makes the verdict testable instead of just "looks right".

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...        # Windows: setx ANTHROPIC_API_KEY sk-...
```

The 15 packets live in `Corvus Materials/Given to students/`.

## Run it

```bash
# one packet, end to end, with the Agent SDK (the live demo)
python demo.py D01

# the bulk work: every packet -> results/<id>.json
python run_all.py            # all 15
python run_all.py D01 D03    # just these (run one before you run fifteen)

# score the results against the labelled answers
python run_checks.py
```

`run_checks.py` needs the labelled file
`Session 3 Labelled Packets (for groups).xlsx` in the project (or pass
`--labels <path>`). It prints packets-correct, **false completes** (the
dangerous mistake, counted separately), wrong item IDs, and needs_review.

## Check the logic without spending anything

`check_packet.py` is pure Python and needs no API key:

```bash
python .claude/skills/corvus-checklist/check_packet.py samples/D01_extracted.json
```

`samples/` holds a hand-made extraction so you can see the checker run offline.

## What's where

| File | Does |
|------|------|
| `CLAUDE.md` | The output contract and the read/check split |
| `.claude/skills/corvus-checklist/` | The skill: `SKILL.md`, `checklist.json` (Meena's rules as data), `check_packet.py` |
| `run_all.py` | Loops every packet: model extracts → code checks → writes a record |
| `run_checks.py` | Scores `results/` against the labelled answers |
| `demo.py` | One packet end to end with the Agent SDK; prints the record and cost |
| `results/` | One JSON record per packet |

## Safety / limits

- Read-only: the tools given to the SDK are `Read`, `Skill`, `Bash` — nothing
  that approves, sends or deletes.
- Every SDK run sets `max_turns` and `max_budget_usd`.
- No API keys in the code; `.env` and `*.key` are git-ignored.
- No ClaimCore member lookup yet (Session 4): member ID is checked for being
  filled, legible and matching the ID card only.
