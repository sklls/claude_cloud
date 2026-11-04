"""Session 4 starter: connect your intake agent to the Corvus mock systems.

This file RUNS, but it is deliberately incomplete. Search for "TODO" — those are the parts your group builds.
It already shows you the patterns you need:
  * custom tools for the Agent SDK (DocVault, ClaimCore, work queue), served in-process;
  * the built-in Read tool, so the agent can look at the scanned PDFs it downloads;
  * a PreToolUse hook that enforces shadow mode, and a PostToolUse hook that writes an audit log;
  * a loop that picks up gateway deliveries from ../inbox.

Run from the corvus-mock-systems folder, with the server running (python corvus_systems.py):
    python starter/agent_starter.py                 # process every delivery in inbox/ that is not done yet
    python starter/agent_starter.py --once          # process one delivery, then stop
    CORVUS_MODE=assist python starter/agent_starter.py   # really write tags (default is shadow)
"""
import argparse, asyncio, datetime as dt, json, os, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from claude_agent_sdk import (query, ClaudeAgentOptions, HookMatcher, ResultMessage, tool, create_sdk_mcp_server)

ROOT = Path(__file__).resolve().parent.parent
INBOX, WORK, LOGS = ROOT / "inbox", ROOT / "work", ROOT / "logs"
BASE = os.environ.get("CORVUS_BASE_URL", "http://127.0.0.1:8800")
READ_KEY = os.environ.get("DOCVAULT_CLAIMCORE_READ_KEY")      # from .env: never write keys into code (ISP-07 rule 3)
WRITE_KEY = os.environ.get("WORKQUEUE_WRITE_KEY")
MODE = os.environ.get("CORVUS_MODE", "shadow")                 # off | shadow | assist
SERVER = "corvus"
TAG_TOOL = f"mcp__{SERVER}__tag_request"


def load_dotenv():
    """Tiny .env loader so you don't need another package."""
    global READ_KEY, WRITE_KEY
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    READ_KEY = os.environ.get("DOCVAULT_CLAIMCORE_READ_KEY")
    WRITE_KEY = os.environ.get("WORKQUEUE_WRITE_KEY")


# ----------------------------------------------------------------------------- HTTP helper
def call(method, path, key, body=None, raw=False):
    """Call a Corvus API. Returns (http_status, json_or_bytes, headers)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"X-API-Key": key or "", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = r.read()
            return r.status, (payload if raw else json.loads(payload)), dict(r.headers)
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            payload = json.loads(payload)
        except ValueError:
            pass
        return e.code, payload, dict(e.headers)
    # TODO (step 1): ClaimCore answers 429 when you go over 10 requests a second. Retry after Retry-After.


def out(obj, error=False):
    return {"content": [{"type": "text", "text": json.dumps(obj, ensure_ascii=False, indent=1)}], "is_error": error}


# ----------------------------------------------------------------------------- tools
@tool("get_documents",
      "Fetch the documents DocVault holds for a pre-authorisation request and save the scanned PDFs locally. "
      "Returns each document's category, version, upload time, source and the local path to open with Read.",
      {"type": "object", "properties": {"request_id": {"type": "string"}}, "required": ["request_id"]})
async def get_documents(args):
    rid = args["request_id"]
    # WORKED EXAMPLE. TODO (step 1): should you be asking DocVault for the latest versions only?
    status, body, _ = call("GET", f"/docvault/requests/{urllib.parse.quote(rid)}/documents", READ_KEY)
    if status != 200:
        return out({"error": f"DocVault returned {status}", "detail": body}, error=True)
    folder = WORK / rid
    folder.mkdir(parents=True, exist_ok=True)
    docs = []
    for d in body["documents"]:
        s, pdf, _ = call("GET", f"/docvault/documents/{d['doc_id']}/file", READ_KEY, raw=True)
        if s == 200:
            path = folder / d["filename"]
            path.write_bytes(pdf)
            docs.append({**{k: d[k] for k in ("doc_id", "category", "version", "supersedes", "uploaded_at", "channel")},
                         "source": f"DocVault {d['doc_id']} v{d['version']}", "local_path": str(path)})
    return out({"request_id": rid, "documents": docs})


@tool("resolve_member",
      "Find the ClaimCore member for a request. Give the member ID written on the form, and the patient's name "
      "(and date of birth if a document shows it). Returns a status, the member record if found, and how sure the match is.",
      {"type": "object", "properties": {"member_id_on_form": {"type": "string"}, "name": {"type": "string"},
                                        "dob": {"type": "string"}}, "required": ["member_id_on_form", "name"]})
async def resolve_member(args):
    status, body, headers = call("GET", f"/claimcore/members/{urllib.parse.quote(args['member_id_on_form'])}", READ_KEY)
    as_of = headers.get("X-Data-As-Of") or headers.get("x-data-as-of")
    if status == 200:
        return out({"status": "matched", "confidence": "exact", "member": body, "data_as_of": as_of})
    # TODO (step 1): your matching rule. Near misses (swapped digits, O for 0, legacy IDs, employee or family numbers),
    # namesakes, and members missing from last night's batch. Decide what goes to a person.
    return out({"status": "not_found", "detail": body, "data_as_of": as_of})


@tool("tag_request",
      "Write the result for a request into the processors' work queue: status complete, incomplete or needs_review, "
      "the missing checklist items, the key fields, and a short note for the processor. The only write. Once per request.",
      {"type": "object", "properties": {
          "request_id": {"type": "string"},
          "status": {"type": "string", "enum": ["complete", "incomplete", "needs_review"]},
          "missing_items": {"type": "array", "items": {"type": "string"}},
          "extracted_fields": {"type": "object"},
          "note": {"type": "string"}},
       "required": ["request_id", "status", "note"]})
async def tag_request(args):
    rid = args.pop("request_id")
    # TODO (step 2): validate the input, check for an existing tag first, and read "status" in the response BODY:
    # the API answers HTTP 200 even when it refuses.
    status, body, _ = call("POST", f"/workqueue/requests/{urllib.parse.quote(rid)}/tags", WRITE_KEY, args)
    return out({"http_status": status, "response": body})


TOOLS = [get_documents, resolve_member, tag_request]


# ----------------------------------------------------------------------------- hooks (step 3)
def log(name, record):
    LOGS.mkdir(exist_ok=True)
    with open(LOGS / name, "a") as fh:
        fh.write(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), "mode": MODE, **record},
                            ensure_ascii=False) + "\n")


async def enforce_mode(input_data, tool_use_id, context):
    """Shadow mode is enforced in code, not in the prompt: the tag call is blocked and recorded instead."""
    if MODE != "assist":
        log("shadow_tags.jsonl", {"would_have_tagged": input_data["tool_input"]})
        return {"hookSpecificOutput": {"hookEventName": input_data["hook_event_name"], "permissionDecision": "deny",
                                       "permissionDecisionReason": "Shadow mode: the tag was recorded, not written. "
                                                                   "Do not retry. Finish this request."}}
    return {}


async def audit(input_data, tool_use_id, context):
    # TODO (step 3): is this enough for ISP-07 rule 4 (which account, what, when, for which request)?
    log("agent_audit.jsonl", {"tool": input_data["tool_name"], "input": input_data["tool_input"]})
    return {}


# ----------------------------------------------------------------------------- the agent
SYSTEM_PROMPT = """You are the Corvus Health pre-authorisation intake assistant.
You check whether a cashless pre-authorisation packet is complete against Meena's checklist and tag it
for a processor. You never approve or reject anything.
For the request you are given: get its documents, open each local_path with Read, resolve the member,
then call tag_request exactly once.
TODO: paste in the checklist rules and instructions from your Session 3 prototype."""


def options():
    return ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        tools=["Read"],                                   # built-in tools available: only Read (to see the PDFs)
        mcp_servers={SERVER: create_sdk_mcp_server(SERVER, tools=TOOLS)},
        allowed_tools=["Read"] + [f"mcp__{SERVER}__{t.name}" for t in TOOLS],   # no wildcards
        hooks={"PreToolUse": [HookMatcher(matcher=TAG_TOOL, hooks=[enforce_mode])],
               "PostToolUse": [HookMatcher(hooks=[audit])]},
        cwd=str(ROOT),
        setting_sources=[],                               # don't load CLAUDE.md or settings meant for Claude Code
        max_turns=30,
        max_budget_usd=float(os.environ.get("CORVUS_MAX_BUDGET_USD", 1.0)),
        max_buffer_size=50 * 1024 * 1024,                 # scanned PDFs read with Read come back as large messages
    )


async def process(delivery):
    rid = delivery["request_id"]
    prompt = (f"New pre-authorisation request {rid} from {delivery.get('hospital_name', delivery.get('hospital_id'))}, "
              f"received {delivery.get('received_at', '')}. Process it.")
    result = None
    async for msg in query(prompt=prompt, options=options()):
        if isinstance(msg, ResultMessage):
            result = msg
    log("runs.jsonl", {"request_id": rid, "delivery_id": delivery["delivery_id"],
                       "subtype": getattr(result, "subtype", None), "cost_usd": getattr(result, "total_cost_usd", None),
                       "final": getattr(result, "result", None)})
    print(f"{rid}: {getattr(result, 'subtype', 'no result')}  ${getattr(result, 'total_cost_usd', 0) or 0:.3f}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    load_dotenv()
    if not READ_KEY or not WRITE_KEY:
        sys.exit("Keys missing: copy .env.example to .env")
    if MODE == "off":
        sys.exit("CORVUS_MODE=off: the assistant is switched off.")
    done_file = LOGS / "deliveries_done.json"
    done = set(json.loads(done_file.read_text())) if done_file.exists() else set()
    for folder in sorted(INBOX.glob("GW-*")):
        meta = folder / "delivery.json"
        if not meta.exists() or folder.name in done:
            continue
        delivery = json.loads(meta.read_text())
        # TODO (step 2): the gateway can deliver the same REQUEST twice under a new delivery ID.
        await process(delivery)
        done.add(folder.name)
        LOGS.mkdir(exist_ok=True)
        done_file.write_text(json.dumps(sorted(done)))
        if a.once:
            break
    print(f"Mode: {MODE}. Logs in {LOGS}")


if __name__ == "__main__":
    asyncio.run(main())
