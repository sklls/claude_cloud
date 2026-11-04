#!/usr/bin/env python3
"""
demo.py  --  one packet, end to end, with the Claude Agent SDK.

For the live client demo. Follows the "model reads, code checks" split:
  * the MODEL reads the scanned packet (Read tool only) and returns an extraction
  * CODE (the corvus-checklist skill's check_packet.py) decides the verdict
Then it prints the one JSON record (CLAUDE.md contract) and the cost.

Running the checker in code -- rather than asking the agent to run it via Bash --
keeps the agent truly read-only, makes the verdict deterministic, and means no
permission prompt can block the demo. It still uses the skill: check_packet and
checklist.json ARE the skill.

Every run is capped on turns and budget. It never approves, rejects or sends
anything.

Usage:
    python demo.py "Corvus Materials/Given to students/D01_PA-2610-43235.pdf"
    python demo.py D01            # shorthand: finds the D01 packet for you
"""
import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKETS_DIR = ROOT / "Corvus Materials" / "Given to students"

# reuse the tested extraction + record-building from run_all.py
import run_all
from run_all import build_record, extract_one, packet_id_from_name  # noqa: E402

sys.path.insert(0, str(ROOT / ".claude" / "skills" / "corvus-checklist"))
from check_packet import check_packet, load_checklist  # noqa: E402

run_all.MODEL = "sonnet"   # the cheaper reader the brief measured (~$0.08/packet)


def resolve_pdf(arg: str) -> Path:
    p = Path(arg)
    if p.exists():
        return p
    m = re.match(r"(D\d+)", arg, re.IGNORECASE)
    if m:
        hits = sorted(PACKETS_DIR.glob(f"{m.group(1).upper()}_*.pdf"))
        if hits:
            return hits[0]
    print(f"Packet not found: {arg}", file=sys.stderr)
    sys.exit(1)


async def main(arg: str):
    pdf = resolve_pdf(arg)
    pid = packet_id_from_name(pdf)

    extracted, cost, turns, raw = await extract_one(pdf)
    if extracted is None:
        # show what actually came back so the cause is visible (auth / budget /
        # permission error, truncated output, or just non-JSON prose)
        print("--- model reply could not be parsed as JSON; raw reply below ---",
              file=sys.stderr)
        print((raw or "<empty reply>")[:2000], file=sys.stderr)
        print("---------------------------------------------------------------",
              file=sys.stderr)
        record = {
            "packet_id": pid, "treatment_type": None, "status": "needs_review",
            "missing_items": [], "fields": {}, "evidence": {},
            "reason": "Could not read a valid extraction from the packet.",
        }
    else:
        extracted.setdefault("packet_id", pid)
        verdict = check_packet(extracted, load_checklist())
        record = build_record(pid, extracted, verdict)

    print(json.dumps(record, ensure_ascii=False, indent=2))
    print(f"\nCost: ${cost:.3f}   Turns: {turns}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print('usage: python demo.py "<packet.pdf>"  (or: python demo.py D01)', file=sys.stderr)
        raise SystemExit(2)
    asyncio.run(main(sys.argv[1]))
