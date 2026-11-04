"""Corvus mock systems for the Session 4 integration build hour.

Run:   python corvus_systems.py            (serves http://127.0.0.1:8800, API docs at /docs)

Three systems, three APIs, two service accounts (Corvus policy ISP-07, rule 2):
  DocVault read API     /docvault/...     key: DOCVAULT_CLAIMCORE_READ_KEY (read only)
  ClaimCore read API    /claimcore/...    key: DOCVAULT_CLAIMCORE_READ_KEY (read only)
  Work-queue tagging    /workqueue/...    key: WORKQUEUE_WRITE_KEY (tags and notes only)
Send the key in the X-API-Key header. Keys are in .env.example. ClaimCore has no write API.

Behaviour you will meet (the same as on the system map):
  * DocVault returns superseded versions too, unless you pass latest_only=true.
  * ClaimCore lookup needs an exact member ID. Name search returns every namesake.
    Data comes from last night's batch (see the X-Data-As-Of header). Max 10 requests a second.
  * The tagging API answers HTTP 200 even when it refuses: read "status" in the body.
    It does not stop you tagging the same request twice.
Everything is synthetic. Every call is written to logs/server_audit.jsonl.
"""
import json, os, time, uuid, datetime as dt, threading
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Optional
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
LOGS = ROOT / "logs"; LOGS.mkdir(exist_ok=True)
READ_KEY = os.environ.get("DOCVAULT_CLAIMCORE_READ_KEY", "ro-corvus-7f3a9c")
WRITE_KEY = os.environ.get("WORKQUEUE_WRITE_KEY", "wq-corvus-2b8e1d")
AS_OF = "2026-10-12T02:00:00+05:30"

DOCVAULT = json.loads((DATA / "docvault" / "index.json").read_text())
DOCS = {d["doc_id"]: d for r in DOCVAULT.values() for d in r["documents"]}
MEMBERS = json.loads((DATA / "claimcore_members.json").read_text())["members"]
BY_ID = {m["member_id"]: m for m in MEMBERS}
WQ_SEED = DATA / "workqueue_seed.json"
WQ_STATE = DATA / "workqueue_state.json"
lock = threading.Lock()

def load_wq():
    return json.loads((WQ_STATE if WQ_STATE.exists() else WQ_SEED).read_text())
WQ = load_wq()

app = FastAPI(title="Corvus mock systems (synthetic)", version="1.0",
              description="DocVault read API, ClaimCore read API and the processors' work-queue tagging API, for the FDE course.")

def audit(request: Request, account: str, status: int, note: str = ""):
    with open(LOGS / "server_audit.jsonl", "a") as fh:
        fh.write(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), "account": account,
                             "method": request.method, "path": request.url.path, "query": str(request.url.query),
                             "status": status, "note": note}) + "\n")

def require(key: Optional[str], allowed: str, request: Request):
    if key is None:
        audit(request, "anonymous", 401); raise HTTPException(401, "Missing X-API-Key header")
    if key != allowed:
        audit(request, key[:6] + "...", 403)
        raise HTTPException(403, "This key is not allowed to use this system. Service accounts are scoped per system (ISP-07 rule 2).")
    return "read-service" if key == READ_KEY else "workqueue-service"

# --------------------------------------------------------------- rate limit (ClaimCore)
calls = defaultdict(deque)
def rate_limited(account: str, limit: int = 10) -> bool:
    now = time.time(); q = calls[account]
    while q and now - q[0] > 1: q.popleft()
    if len(q) >= limit: return True
    q.append(now); return False

# --------------------------------------------------------------- DocVault
@app.get("/docvault/requests/{request_id}/documents", tags=["DocVault (read only)"])
def list_documents(request_id: str, request: Request, latest_only: bool = False, x_api_key: Optional[str] = Header(None)):
    """All documents stored for a pre-authorisation request, oldest first. Includes superseded versions unless latest_only=true."""
    acct = require(x_api_key, READ_KEY, request)
    r = DOCVAULT.get(request_id)
    if not r:
        audit(request, acct, 404); raise HTTPException(404, f"No documents for request {request_id}")
    docs = r["documents"]
    if latest_only:
        replaced = {d["supersedes"] for d in docs if d["supersedes"]}
        docs = [d for d in docs if d["doc_id"] not in replaced]
    audit(request, acct, 200)
    return {"request_id": request_id, "count": len(docs), "documents": docs}

@app.get("/docvault/documents/{doc_id}", tags=["DocVault (read only)"])
def document_metadata(doc_id: str, request: Request, x_api_key: Optional[str] = Header(None)):
    acct = require(x_api_key, READ_KEY, request)
    d = DOCS.get(doc_id)
    if not d:
        audit(request, acct, 404); raise HTTPException(404, f"Unknown document {doc_id}")
    audit(request, acct, 200)
    return d

@app.get("/docvault/documents/{doc_id}/file", tags=["DocVault (read only)"])
def document_file(doc_id: str, request: Request, x_api_key: Optional[str] = Header(None)):
    """The scanned file itself (PDF, image pages only: there is no text layer)."""
    acct = require(x_api_key, READ_KEY, request)
    if doc_id not in DOCS:
        audit(request, acct, 404); raise HTTPException(404, f"Unknown document {doc_id}")
    audit(request, acct, 200)
    return FileResponse(DATA / "docvault" / "files" / f"{doc_id}.pdf", media_type="application/pdf", filename=f"{doc_id}.pdf")

# --------------------------------------------------------------- ClaimCore
def cc_response(request, acct, body, status=200):
    audit(request, acct, status)
    return JSONResponse(body, status_code=status, headers={"X-Data-As-Of": AS_OF})

@app.get("/claimcore/members/{member_id}", tags=["ClaimCore (read only)"])
def get_member(member_id: str, request: Request, x_api_key: Optional[str] = Header(None)):
    """Exact lookup by Corvus member ID (CVH + 8 digits). Read replica refreshed nightly at 02:00."""
    acct = require(x_api_key, READ_KEY, request)
    if rate_limited(acct):
        audit(request, acct, 429)
        return JSONResponse({"error": "rate_limited", "message": "Max 10 requests a second"}, 429, headers={"Retry-After": "1"})
    m = BY_ID.get(member_id)
    if not m:
        return cc_response(request, acct, {"error": "not_found", "message": f"No member {member_id} in the {AS_OF} batch"}, 404)
    return cc_response(request, acct, m)

@app.get("/claimcore/members", tags=["ClaimCore (read only)"])
def search_members(request: Request, name: str = Query(..., min_length=3), dob: Optional[str] = None,
                   x_api_key: Optional[str] = Header(None)):
    """Search by full name (case-insensitive, exact words in any order), optionally narrowed by date of birth (YYYY-MM-DD).
    Returns every match, including legacy IDs from acquired insurers."""
    acct = require(x_api_key, READ_KEY, request)
    if rate_limited(acct):
        audit(request, acct, 429)
        return JSONResponse({"error": "rate_limited", "message": "Max 10 requests a second"}, 429, headers={"Retry-After": "1"})
    want = sorted(name.lower().split())
    hits = [m for m in MEMBERS if sorted(m["name"].lower().split()) == want and (not dob or m["dob"] == dob)]
    return cc_response(request, acct, {"count": len(hits), "matches": hits})

# --------------------------------------------------------------- Work queue
class Tag(BaseModel):
    status: str
    missing_items: list[str] = []
    note: str = ""
    extracted_fields: dict[str, Any] = {}
    source: str = "intake-assistant"

def save_wq():
    WQ_STATE.write_text(json.dumps(WQ, indent=1))

@app.get("/workqueue/requests/{request_id}", tags=["Work queue"])
def get_request(request_id: str, request: Request, x_api_key: Optional[str] = Header(None)):
    acct = require(x_api_key, WRITE_KEY, request)
    r = WQ.get(request_id)
    if not r:
        audit(request, acct, 404); raise HTTPException(404, f"No work item for {request_id}")
    audit(request, acct, 200)
    return r

@app.post("/workqueue/requests/{request_id}/tags", tags=["Work queue"])
def add_tag(request_id: str, tag: Tag, request: Request, x_api_key: Optional[str] = Header(None)):
    """Add a tag and a note to a request in the processors' queue. Always answers HTTP 200 for a known request:
    check "status" in the body. Tagging the same request twice creates two tags."""
    acct = require(x_api_key, WRITE_KEY, request)
    with lock:
        r = WQ.get(request_id)
        if not r:
            audit(request, acct, 404); raise HTTPException(404, f"No work item for {request_id}")
        if r["assigned_to"]:
            audit(request, acct, 200, "refused: assigned")
            return {"status": "error", "error": f"Request {request_id} is already assigned to processor {r['assigned_to']}; tags are locked",
                    "tag_id": None}
        t = {"tag_id": "TG-" + uuid.uuid4().hex[:8], "at": dt.datetime.now().isoformat(timespec="seconds"), **tag.model_dump()}
        r["tags"].append(t); save_wq()
    audit(request, acct, 200, f"tag {t['tag_id']}")
    return {"status": "ok", "tag_id": t["tag_id"]}

@app.get("/workqueue/requests/{request_id}/tags", tags=["Work queue"])
def list_tags(request_id: str, request: Request, x_api_key: Optional[str] = Header(None)):
    acct = require(x_api_key, WRITE_KEY, request)
    r = WQ.get(request_id)
    if not r:
        audit(request, acct, 404); raise HTTPException(404, f"No work item for {request_id}")
    audit(request, acct, 200)
    return {"request_id": request_id, "tags": r["tags"]}

# --------------------------------------------------------------- admin (for instructors and testing)
@app.post("/admin/reset", tags=["Admin"])
def reset(request: Request):
    """Clear all tags (back to the seed state)."""
    global WQ
    with lock:
        if WQ_STATE.exists(): WQ_STATE.unlink()
        WQ = load_wq()
    audit(request, "admin", 200, "reset")
    return {"status": "ok"}

@app.get("/health", tags=["Admin"])
def health():
    return {"status": "ok", "requests": len(DOCVAULT), "documents": len(DOCS), "members": len(MEMBERS), "claimcore_data_as_of": AS_OF}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("CORVUS_PORT", 8800)))
