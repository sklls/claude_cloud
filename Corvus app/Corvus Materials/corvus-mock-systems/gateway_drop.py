"""Intake gateway mock: drops a new pre-authorisation delivery into ./inbox every few minutes.

  python gateway_drop.py                 # one delivery every 120 seconds (default)
  python gateway_drop.py --every 10      # faster, for testing
  python gateway_drop.py --all           # drop everything now
  python gateway_drop.py --reset         # empty the inbox and start again

Each delivery is a folder inbox/<delivery_id>/ holding delivery.json and a copy of every document
the hospital sent (the same files DocVault stores). The gateway sometimes delivers the same
request twice, under a new delivery ID. A delivery is complete when its delivery.json exists.
"""
import argparse, json, shutil, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEDULE = json.loads((ROOT / "data" / "gateway_schedule.json").read_text())
FILES = ROOT / "data" / "docvault" / "files"
INBOX = ROOT / "inbox"
STATE = ROOT / "logs" / "gateway_state.json"


def drop(d):
    tmp = INBOX / (d["delivery_id"] + ".partial")
    tmp.mkdir(parents=True, exist_ok=True)
    for doc_id in d["documents"]:
        shutil.copy(FILES / f"{doc_id}.pdf", tmp / f"{doc_id}.pdf")
    (tmp / "delivery.json").write_text(json.dumps(d, indent=1))
    tmp.rename(INBOX / d["delivery_id"])        # appears all at once
    print(f"dropped {d['delivery_id']}  request {d['request_id']}  ({len(d['documents'])} documents)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=float, default=120)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args()
    (ROOT / "logs").mkdir(exist_ok=True)
    if a.reset:
        shutil.rmtree(INBOX, ignore_errors=True); STATE.unlink(missing_ok=True); print("inbox emptied"); return
    INBOX.mkdir(exist_ok=True)
    done = json.loads(STATE.read_text()) if STATE.exists() else 0
    for i, d in enumerate(SCHEDULE[done:], start=done):
        drop(d)
        STATE.write_text(json.dumps(i + 1))
        if not a.all and i + 1 < len(SCHEDULE):
            time.sleep(a.every)
    print("all deliveries made")


if __name__ == "__main__":
    main()
