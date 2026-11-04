#!/usr/bin/env python3
"""
run_all.py  --  the bulk worker.

Loops over every packet PDF and, for each one:
    1. the MODEL reads the scan and returns an extraction JSON (what is on the pages)
    2. CODE (check_packet.py) decides status + missing_items
    3. writes one record to results/<packet_id>.json  (the contract in CLAUDE.md)

This is a program doing the bulk work -- NOT the model "checking 15 packets by
reading them" in one conversation. Every SDK call is capped on turns and budget.

Usage:
    python run_all.py                 # all packets in the packets folder
    python run_all.py D01 D03         # just these (run one before you run fifteen)
    python run_all.py --limit 3       # first 3 packets

Needs ANTHROPIC_API_KEY in the environment (or a logged-in Claude Code setup).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKILL_DIR = ROOT / ".claude" / "skills" / "corvus-checklist"
sys.path.insert(0, str(SKILL_DIR))
from check_packet import check_packet, load_checklist  # noqa: E402

# ---- config -------------------------------------------------------------- #
PACKETS_DIR = ROOT / "Corvus Materials" / "Given to students"
RESULTS_DIR = ROOT / "results"
PAGE_CACHE = ROOT / ".page_cache"   # rendered page images live here
MODEL = os.environ.get("CORVUS_MODEL", "sonnet")
RENDER_ZOOM = 2.0              # 72 dpi * 2 = 144 dpi; enough for small print
MAX_TURNS = 20
MAX_BUDGET_USD = 0.60          # per packet
MAX_BUFFER = 50 * 1024 * 1024  # scanned PDFs come back as large messages

EXTRACTION_PROMPT = """You are the READING half of the Corvus intake assistant.

This pre-authorisation packet has been rendered to one image per page. Use the
Read tool to open EACH page image below, then write down what is on the pages:
{pages_block}

Write down ONLY what is on the pages, as a single JSON object matching this
schema (the checking code depends on these exact field names and formats):

{schema}

Rules:
- You MUST open every page image with the Read tool before answering. Do not
  return the schema with null values for information that is visible on a page.
- Report only what you can see. Do NOT decide whether the packet is complete.
- Dates as YYYY-MM-DD. estimated_cost and amounts as plain numbers (no "Rs", no commas).
- treatment_type is one of: cataract, tka, appendectomy, delivery, ptca (from the proposed procedure).
- laterality is "left"/"right" for a cataract eye or tka knee, else null.
- For a document that is only MENTIONED inside another note (not attached as its
  own report), add "mentions_only": true.
- Record EVERY document as its own entry. If there are several cost estimates
  (for example an original and a one stamped REVISED), add one cost_estimate
  entry per page, each with its own "signed", "total" and "line_items".
- If you cannot read something a check needs (illegible field, unreadable date),
  do NOT guess: add it to "uncertain" with a short reason.

Reply with ONLY the JSON object. No prose, no code fence."""

SCHEMA_HINT = """{
  "packet_id": "<from file name, e.g. D03>",
  "pages": <int>,
  "treatment_type": "cataract|tka|appendectomy|delivery|ptca",
  "form": {
    "present": true, "page": 1,
    "patient_name": null, "member_id": null, "hospital_id": null,
    "doctor_name": null, "doctor_reg_no": null, "diagnosis": null,
    "icd10": null, "procedure": null,
    "admission_type": "planned|emergency", "admission_date": "YYYY-MM-DD",
    "length_of_stay": null, "estimated_cost": null,
    "doctor_signature_present": false, "patient_signature_present": false,
    "laterality": null, "delivery_mode": null
  },
  "documents": [
    {"type": "id_card", "page": 0, "name": null, "member_id": null, "dob": null},
    {"type": "clinical_note", "page": 0, "date": "YYYY-MM-DD", "laterality": null, "lscs_indication": false},
    {"type": "cost_estimate", "page": 0, "total": null, "on_letterhead": true, "signed": true, "line_items": [{"desc": "", "amount": 0}]},
    {"type": "biometry|xray_knee|conservative_treatment|abdominal_imaging|antenatal_record|ecg|angiography", "page": 0, "date": "YYYY-MM-DD", "laterality": null, "weeks": null, "mentions_only": false}
  ],
  "uncertain": []
}"""


def packet_id_from_name(path: Path) -> str:
    m = re.match(r"(D\d+)", path.stem)
    return m.group(1) if m else path.stem


def render_pages(pdf: Path) -> list[Path]:
    """Render each PDF page to a PNG the model can read directly.

    The scans are image-only PDFs. The Claude CLI's Read tool needs poppler
    (pdftoppm) to rasterise a PDF, which may not be installed. Rendering here
    with PyMuPDF removes that dependency and makes reading reliable for every
    packet. Images are cached in .page_cache/<packet_id>/ and reused.
    """
    import fitz  # PyMuPDF

    pid = packet_id_from_name(pdf)
    out_dir = PAGE_CACHE / pid
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf)
    mat = fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM)
    pages: list[Path] = []
    for i, page in enumerate(doc, start=1):
        img = out_dir / f"page-{i:02d}.png"
        if not img.exists():
            page.get_pixmap(matrix=mat).save(img)
        pages.append(img)
    doc.close()
    return pages


def _pages_block(pages: list[Path]) -> str:
    return "\n".join(f"    - page {i}: {p.as_posix()}" for i, p in enumerate(pages, start=1))


def extract_json(text: str):
    """Pull the first JSON object out of the model's reply (tolerate code fences)."""
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    blob = fence.group(1) if fence else None
    if blob is None:
        start = text.find("{")
        end = text.rfind("}")
        blob = text[start:end + 1] if start != -1 and end > start else None
    if blob is None:
        return None
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


def build_record(packet_id: str, extracted: dict, verdict: dict) -> dict:
    form = (extracted or {}).get("form", {}) or {}
    cost = form.get("estimated_cost")
    try:
        cost = int(round(float(cost))) if cost is not None and str(cost) != "" else None
    except (TypeError, ValueError):
        cost = None
    return {
        "packet_id": packet_id,
        "treatment_type": verdict.get("treatment_type") or extracted.get("treatment_type"),
        "status": verdict["status"],
        "missing_items": verdict["missing_items"],
        "fields": {
            "member_id": form.get("member_id"),
            "patient_name": form.get("patient_name"),
            "icd10": form.get("icd10"),
            "admission_date": form.get("admission_date"),
            "estimated_cost": cost,
        },
        "evidence": verdict["evidence"],
        "reason": verdict["reason"],
    }


async def extract_one(pdf: Path) -> tuple[dict | None, float, int, str]:
    """Return (extracted_json | None, cost_usd, turns, raw_text)."""
    from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

    options = ClaudeAgentOptions(
        cwd=str(ROOT),
        setting_sources=["project"],
        allowed_tools=["Read"],
        model=MODEL,
        max_turns=MAX_TURNS,
        max_budget_usd=MAX_BUDGET_USD,
        max_buffer_size=MAX_BUFFER,
    )
    pages = render_pages(pdf)
    prompt = EXTRACTION_PROMPT.format(pages_block=_pages_block(pages), schema=SCHEMA_HINT)
    raw, cost, turns = "", 0.0, 0
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, ResultMessage):
            raw = msg.result or ""
            cost = getattr(msg, "total_cost_usd", 0.0) or 0.0
            turns = getattr(msg, "num_turns", 0) or 0
    return extract_json(raw), cost, turns, raw


async def run(pdfs: list[Path]):
    RESULTS_DIR.mkdir(exist_ok=True)
    checklist = load_checklist()
    total_cost, total_turns, t0 = 0.0, 0, time.time()

    for pdf in pdfs:
        pid = packet_id_from_name(pdf)
        try:
            extracted, cost, turns, raw = await extract_one(pdf)
        except Exception as exc:  # noqa: BLE001
            extracted, cost, turns, raw = None, 0.0, 0, f"<error: {exc}>"
        total_cost += cost
        total_turns += turns

        if extracted is None:
            record = {
                "packet_id": pid, "treatment_type": None, "status": "needs_review",
                "missing_items": [], "fields": {}, "evidence": {},
                "reason": "Could not read a valid extraction from the packet.",
            }
            note = "extraction failed -> needs_review"
        else:
            try:
                extracted.setdefault("packet_id", pid)
                verdict = check_packet(extracted, checklist)
                record = build_record(pid, extracted, verdict)
                note = f"{record['status']}"
                if record["missing_items"]:
                    note += f"  missing={record['missing_items']}"
            except Exception as exc:  # noqa: BLE001 - one bad packet must not kill the batch
                record = {
                    "packet_id": pid, "treatment_type": None, "status": "needs_review",
                    "missing_items": [], "fields": {}, "evidence": {},
                    "reason": f"Checker could not process the extraction ({exc}).",
                }
                note = f"check error -> needs_review ({exc})"

        (RESULTS_DIR / f"{pid}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{pid}: {note}   (${cost:.3f}, {turns} turns)")

    n = len(pdfs)
    print("-" * 60)
    print(f"{n} packets   total ${total_cost:.3f}   "
          f"avg ${total_cost / n:.3f}/packet   {time.time() - t0:.0f}s")
    if total_cost:
        print(f"At 1,800 requests/day: about ${total_cost / n * 1800:.0f}/day "
              f"(${total_cost / n * 1800 * 30:,.0f}/month)")


def select_pdfs(args) -> list[Path]:
    all_pdfs = sorted(PACKETS_DIR.glob("*.pdf"))
    if args.ids:
        wanted = {i.upper() for i in args.ids}
        picked = [p for p in all_pdfs if packet_id_from_name(p).upper() in wanted]
        missing = wanted - {packet_id_from_name(p).upper() for p in picked}
        if missing:
            print(f"warning: no PDF found for {sorted(missing)}", file=sys.stderr)
        return picked
    if args.limit:
        return all_pdfs[: args.limit]
    return all_pdfs


def main():
    ap = argparse.ArgumentParser(description="Run the intake assistant over the packets.")
    ap.add_argument("ids", nargs="*", help="packet ids to run, e.g. D01 D03 (default: all)")
    ap.add_argument("--limit", type=int, help="run only the first N packets")
    args = ap.parse_args()

    if not PACKETS_DIR.exists():
        print(f"Packets folder not found: {PACKETS_DIR}", file=sys.stderr)
        return 1
    pdfs = select_pdfs(args)
    if not pdfs:
        print("No packets selected.", file=sys.stderr)
        return 1
    asyncio.run(run(pdfs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
