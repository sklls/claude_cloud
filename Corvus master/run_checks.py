#!/usr/bin/env python3
"""
run_checks.py  --  the verification loop.

Compares results/<id>.json against the labelled answers and prints a score:
how many packets are correct, how many FALSE COMPLETES (the dangerous mistake),
which packets have the wrong missing-item IDs, and which went to needs_review.

Write this early and run it after every change, so each change shows up as a
number -- not a feeling.

Usage:
    python run_checks.py
    python run_checks.py --labels "Corvus Materials/Session 3 Labelled Packets (for groups).xlsx"

Labelled file: an .xlsx or .csv with, per packet, the packet id, the expected
status (complete / incomplete) and the expected missing item IDs. Column names
are matched loosely (packet/id, status/label/expected, missing/items).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"

ITEM_RE = re.compile(r"(?:form|doc|estimate|note)\.[a-z0-9_]+")


def find_labels_file(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    candidates = list(ROOT.glob("**/*Labelled*Packets*.xlsx")) + \
        list(ROOT.glob("**/*abelled*.xlsx")) + \
        list(ROOT.glob("**/*labelled*.csv")) + \
        list(ROOT.glob("**/*Labelled*.csv"))
    return candidates[0] if candidates else None


def _norm_status(value: str) -> str:
    v = (value or "").strip().lower()
    if v.startswith("complete"):
        return "complete"
    if v.startswith("incomplete"):
        return "incomplete"
    if "review" in v:
        return "needs_review"
    return v


def _parse_items(value) -> set:
    if value is None:
        return set()
    text = str(value)
    return set(ITEM_RE.findall(text))


def _pick(colnames, *needles):
    for i, name in enumerate(colnames):
        low = (name or "").strip().lower()
        if any(n in low for n in needles):
            return i
    return None


def load_labels(path: Path) -> dict:
    rows = _read_rows(path)
    if not rows:
        return {}
    header = rows[0]
    i_id = _pick(header, "packet", "id")
    i_status = _pick(header, "status", "label", "expected", "answer", "verdict")
    i_items = _pick(header, "missing", "item")
    if i_id is None:
        i_id = 0
    labels = {}
    for row in rows[1:]:
        if i_id >= len(row):
            continue
        raw_id = str(row[i_id]).strip()
        m = re.search(r"D\d+", raw_id.upper())
        if not m:
            continue
        pid = m.group(0)
        status = _norm_status(row[i_status]) if i_status is not None and i_status < len(row) else ""
        items = _parse_items(row[i_items]) if i_items is not None and i_items < len(row) else set()
        # if status missing but items present, infer
        if not status:
            status = "incomplete" if items else "complete"
        labels[pid] = {"status": status, "missing_items": items}
    return labels


def _read_rows(path: Path) -> list:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        try:
            import openpyxl
        except ImportError:
            print("openpyxl is needed to read .xlsx labels (pip install openpyxl).", file=sys.stderr)
            return []
        # copy-read to dodge OneDrive file locks
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        # pick the sheet with the most rows that mentions a packet id
        best, best_rows = None, []
        for ws in wb.worksheets:
            rows = [[("" if c is None else c) for c in r] for r in ws.iter_rows(values_only=True)]
            rows = [r for r in rows if any(str(c).strip() for c in r)]
            joined = " ".join(str(c) for r in rows for c in r)
            if re.search(r"D\d+", joined) and len(rows) > len(best_rows):
                best, best_rows = ws.title, rows
        return best_rows
    # csv / tsv
    with open(path, encoding="utf-8-sig", newline="") as fh:
        sample = fh.read(2048)
        fh.seek(0)
        delim = "\t" if sample.count("\t") > sample.count(",") else ","
        return [r for r in csv.reader(fh, delimiter=delim) if any(str(c).strip() for c in r)]


def load_results() -> dict:
    out = {}
    for f in sorted(RESULTS_DIR.glob("*.json")):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        pid = rec.get("packet_id", f.stem)
        out[pid] = {
            "status": _norm_status(rec.get("status", "")),
            "missing_items": set(rec.get("missing_items", []) or []),
            "reason": rec.get("reason", ""),
        }
    return out


def score(labels: dict, results: dict) -> dict:
    ids = sorted(labels.keys(), key=lambda s: (len(s), s))
    correct, false_completes, wrong_items, false_incompletes = [], [], [], []
    needs_review, not_run = [], []

    for pid in ids:
        exp = labels[pid]
        got = results.get(pid)
        if got is None:
            not_run.append(pid)
            continue
        if got["status"] == "needs_review":
            needs_review.append((pid, got["reason"]))
            continue
        if got["status"] == exp["status"]:
            if exp["status"] == "complete":
                correct.append(pid)
            else:  # incomplete: item IDs must match exactly
                if got["missing_items"] == exp["missing_items"]:
                    correct.append(pid)
                else:
                    wrong_items.append((pid, exp["missing_items"], got["missing_items"]))
        else:
            if got["status"] == "complete" and exp["status"] == "incomplete":
                false_completes.append(pid)
            elif got["status"] == "incomplete" and exp["status"] == "complete":
                false_incompletes.append(pid)
            else:
                wrong_items.append((pid, exp["missing_items"], got["missing_items"]))

    return {
        "total": len(ids), "correct": correct, "false_completes": false_completes,
        "false_incompletes": false_incompletes, "wrong_items": wrong_items,
        "needs_review": needs_review, "not_run": not_run,
    }


def report(s: dict) -> int:
    print("=" * 64)
    print(f"Packets correct: {len(s['correct'])} of {s['total']}")
    print(f"False completes: {len(s['false_completes'])}"
          f"   (said complete, but something was missing)")
    if s["false_completes"]:
        print(f"    -> {', '.join(s['false_completes'])}")
    print(f"False incompletes: {len(s['false_incompletes'])}"
          f"   (said incomplete, but it was complete)")
    if s["false_incompletes"]:
        print(f"    -> {', '.join(s['false_incompletes'])}")
    print(f"Wrong or missing item IDs: {len(s['wrong_items'])} packets")
    for pid, exp, got in s["wrong_items"]:
        print(f"    {pid}: expected {sorted(exp) or '[]'}, got {sorted(got) or '[]'}")
    print(f"Needs review: {len(s['needs_review'])}")
    for pid, reason in s["needs_review"]:
        print(f"    {pid}: {reason}")
    if s["not_run"]:
        print(f"Not yet run: {len(s['not_run'])}  -> {', '.join(s['not_run'])}")
    print("=" * 64)

    # exit non-zero if any false complete (the mistake that can hurt a patient)
    return 1 if s["false_completes"] else 0


def main():
    ap = argparse.ArgumentParser(description="Score results against the labelled answers.")
    ap.add_argument("--labels", help="path to the labelled packets file (.xlsx or .csv)")
    args = ap.parse_args()

    if not RESULTS_DIR.exists() or not any(RESULTS_DIR.glob("*.json")):
        print(f"No results found in {RESULTS_DIR}. Run run_all.py first.", file=sys.stderr)
        return 1

    labels_path = find_labels_file(args.labels)
    if labels_path is None:
        print("Labelled answers file not found.", file=sys.stderr)
        print("Drop 'Session 3 Labelled Packets (for groups).xlsx' into the project,", file=sys.stderr)
        print("or pass --labels <path to .xlsx/.csv>.", file=sys.stderr)
        return 1
    print(f"Labels: {labels_path.name}")

    labels = load_labels(labels_path)
    if not labels:
        print("Could not read any labelled packets from that file.", file=sys.stderr)
        return 1
    results = load_results()
    return report(score(labels, results))


if __name__ == "__main__":
    raise SystemExit(main())
