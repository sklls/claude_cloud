#!/usr/bin/env python3
"""
app.py  --  a small local web console for the Corvus intake assistant.

A browser front end that drives the SAME agent as the command line. You can:
  * pick one of the 15 packets and run it live, or
  * drag in a FRESH PDF (e.g. the held-back packets) and run it,
and see exactly what the model READ (form fields + documents found), the code
VERDICT (complete / incomplete / needs_review with the item IDs), the cost, and
a table of every result so far with the score against the labelled answers.

It only reads files and writes result records. It never approves or rejects.

Run:
    pip install flask
    python app.py          # then open http://127.0.0.1:5000

This is a thin HTTP layer over run_all.py / check_packet.py / run_checks.py --
all the logic lives there; nothing is re-implemented here.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "corvus-checklist"))

import run_all  # noqa: E402
from run_all import (  # noqa: E402
    PACKETS_DIR, RESULTS_DIR, build_record, extract_one,
    packet_id_from_name, render_pages,
)
from check_packet import check_packet, load_checklist  # noqa: E402
import run_checks  # noqa: E402

run_all.MODEL = "sonnet"   # the cheaper reader for the demo

UPLOAD_DIR = ROOT / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder=str(ROOT / "web"), static_url_path="")
CHECKLIST = load_checklist()


# --------------------------------------------------------------------------- #
# run one PDF through the whole pipeline
# --------------------------------------------------------------------------- #
def run_pdf(pdf: Path, packet_id: str | None = None) -> dict:
    pid = packet_id or packet_id_from_name(pdf)
    extracted, cost, turns, raw = asyncio.run(extract_one(pdf))

    if extracted is None:
        record = {
            "packet_id": pid, "treatment_type": None, "status": "needs_review",
            "missing_items": [], "fields": {}, "evidence": {},
            "reason": "Could not read a valid extraction from the packet.",
        }
        extraction = {"error": "unreadable", "raw": (raw or "")[:1500]}
    else:
        extracted.setdefault("packet_id", pid)
        try:
            verdict = check_packet(extracted, CHECKLIST)
            record = build_record(pid, extracted, verdict)
        except Exception as exc:  # noqa: BLE001
            record = {
                "packet_id": pid, "treatment_type": None, "status": "needs_review",
                "missing_items": [], "fields": {}, "evidence": {},
                "reason": f"Checker could not process the extraction ({exc}).",
            }
        extraction = extracted

    # persist so it shows up in the "all results" table
    (RESULTS_DIR / f"{pid}.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    # attach the requirement text for any missing/flagged item, for the UI
    items = CHECKLIST["items"]
    requirements = {i: items.get(i, {}).get("requirement", "") for i in record["missing_items"]}
    return {
        "record": record,
        "extraction": extraction,
        "requirements": requirements,
        "cost": round(cost, 4),
        "turns": turns,
    }


def safe_pid(name: str) -> str:
    stem = Path(name).stem
    m = re.match(r"(D\d+)", stem)
    if m:
        return m.group(1)
    return re.sub(r"[^A-Za-z0-9_-]+", "_", stem)[:40] or "upload"


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/packets")
def api_packets():
    pdfs = sorted(PACKETS_DIR.glob("*.pdf")) if PACKETS_DIR.exists() else []
    return jsonify({
        "packets": [{"id": packet_id_from_name(p), "filename": p.name} for p in pdfs],
        "packets_dir": str(PACKETS_DIR),
    })


@app.get("/api/results")
def api_results():
    records = []
    for f in sorted(RESULTS_DIR.glob("*.json")):
        try:
            records.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    records.sort(key=lambda r: (len(str(r.get("packet_id", ""))), str(r.get("packet_id", ""))))

    # score against the labelled answers, if the file is present
    score_summary = None
    labels_path = run_checks.find_labels_file(None)
    if labels_path is not None:
        try:
            labels = run_checks.load_labels(labels_path)
            results = run_checks.load_results()
            s = run_checks.score(labels, results)
            score_summary = {
                "labels_file": labels_path.name,
                "total": s["total"],
                "correct": len(s["correct"]),
                "false_completes": s["false_completes"],
                "false_incompletes": s["false_incompletes"],
                "wrong_items": [{"id": p, "expected": sorted(e), "got": sorted(g)}
                                for p, e, g in s["wrong_items"]],
                "needs_review": [{"id": p, "reason": r} for p, r in s["needs_review"]],
                "not_run": s["not_run"],
            }
        except Exception as exc:  # noqa: BLE001
            score_summary = {"error": str(exc)}

    return jsonify({"results": records, "score": score_summary})


@app.post("/api/run")
def api_run():
    data = request.get_json(silent=True) or {}
    pid = (data.get("packet_id") or "").strip()
    if not pid:
        return jsonify({"error": "no packet_id"}), 400
    hits = sorted(PACKETS_DIR.glob(f"{pid}_*.pdf")) + sorted(PACKETS_DIR.glob(f"{pid}.pdf"))
    if not hits:
        return jsonify({"error": f"packet {pid} not found"}), 404
    try:
        return jsonify(run_pdf(hits[0], pid))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


@app.post("/api/upload")
def api_upload():
    f = request.files.get("pdf")
    if f is None or not f.filename:
        return jsonify({"error": "no file"}), 400
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "please upload a PDF"}), 400
    pid = safe_pid(f.filename)
    dest = UPLOAD_DIR / f"{pid}.pdf"
    f.save(dest)
    try:
        return jsonify(run_pdf(dest, pid))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    print("Corvus intake console -> http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
