# Corvus mock systems (Session 4: Integration)

Stand-ins for the Corvus interfaces on the system map, so your group can connect the Session 3 prototype to "real" systems. All data is synthetic.

| Map | What you get here | How |
|---|---|---|
| A | Intake gateway feed | `gateway_drop.py` writes new deliveries into `./inbox/` |
| B | DocVault read API | `GET /docvault/...` |
| C | ClaimCore read API | `GET /claimcore/...` |
| ✕ | ClaimCore write | Does not exist. Don't ask for it. |
| D | Work-queue tagging API | `GET/POST /workqueue/...` |
| E | Warehouse SQL | Not provided (not needed for live decisions) |

## Setup (5 minutes)

Python 3.10 or newer.

```bash
pip install -r requirements.txt
cp .env.example .env          # the two service-account keys
python corvus_systems.py      # leave running: http://127.0.0.1:8800, API docs at http://127.0.0.1:8800/docs
python check_kit.py           # in a second terminal: should print "All good."
python gateway_drop.py        # in a third terminal: one new delivery every 2 minutes
```

Handy options: `gateway_drop.py --every 10` (faster), `--all` (everything now), `--reset` (empty the inbox). `POST /admin/reset` clears every tag in the work queue.

## Starter code

`starter/agent_starter.py` runs a minimal agent against these systems: three tools, the built-in Read tool for the scans, a shadow-mode hook and an audit log. It works, but the parts your group builds are marked TODO. Run `python starter/agent_starter.py --once` with the server running and at least one delivery in `inbox/`.

## Keys (policy ISP-07, rules 2 and 3)

Send the key in the `X-API-Key` header.

| Key in .env | Works for | Refused by |
|---|---|---|
| `DOCVAULT_CLAIMCORE_READ_KEY` | DocVault, ClaimCore (read only) | Work queue (403) |
| `WORKQUEUE_WRITE_KEY` | Work queue (tags and notes) | DocVault, ClaimCore (403) |

The server and `check_kit.py` already use these values. Your own code should read them from the environment (for example with `python-dotenv` loading `.env`). A key written into your code or notebook breaks rule 3, and the review panel will look.

## Endpoints

| Method and path | Notes |
|---|---|
| `GET /docvault/requests/{request_id}/documents` | Every document for a request, oldest first. Add `?latest_only=true` to drop superseded versions. |
| `GET /docvault/documents/{doc_id}` | Metadata: category, channel, version, `supersedes`, upload time. |
| `GET /docvault/documents/{doc_id}/file` | The scanned PDF. Images only: no text layer. |
| `GET /claimcore/members/{member_id}` | Exact ID only (CVH + 8 digits). 404 if not in last night's batch. |
| `GET /claimcore/members?name=...&dob=YYYY-MM-DD` | Every namesake, including legacy IDs from acquired insurers. |
| `GET /workqueue/requests/{request_id}` | The work item: hospital, received time, who it is assigned to, tags so far. |
| `POST /workqueue/requests/{request_id}/tags` | Body: `{"status": "complete"/"incomplete"/"needs_review", "missing_items": [...], "note": "...", "extracted_fields": {...}}` |
| `GET /workqueue/requests/{request_id}/tags` | Tags written so far. |
| `GET /health` | Counts and the ClaimCore batch time. |

## Behaviour you will meet

These match the "Known behaviour" column on the system map. Your integration has to cope with each.

1. **The gateway repeats itself.** Some requests arrive twice under a new delivery ID. Tag a request once.
2. **DocVault keeps old versions.** Four requests have a form that was re-sent with a field filled in. Read the latest unless you have a reason not to.
3. **ClaimCore is last night's data.** Every response carries `X-Data-As-Of`. A member missing from the batch is a 404, not proof that the member doesn't exist.
4. **ClaimCore allows 10 requests a second.** More than that returns 429 with `Retry-After`.
5. **Name search returns every namesake.** Use date of birth, and don't pick one when two match.
6. **The tagging API answers 200 even when it refuses.** Two requests are already assigned to a processor; tagging them returns `"status": "error"` in the body. Read the body.
7. **Nothing stops a duplicate tag.** Preventing duplicates is your job.

Every call is written to `logs/server_audit.jsonl`: which account, what, when (ISP-07 rule 4). Your own integration should keep its own log too.

## What is in `data/`

- `docvault/index.json` and `docvault/files/`: 20 requests, 111 scanned documents (the Session 3 packets, split into documents).
- `claimcore_members.json`: 627 members, including the ones in the Session 4 member extract.
- `workqueue_seed.json`: the 20 work items, two already assigned.
- `gateway_schedule.json`: the order the gateway delivers in, duplicates included.
