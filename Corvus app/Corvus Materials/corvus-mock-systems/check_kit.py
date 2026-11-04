"""Check the mock systems are running and your keys work. Run after starting corvus_systems.py.
   python check_kit.py"""
import json, os, sys, urllib.request, urllib.error
BASE = os.environ.get("CORVUS_BASE_URL", "http://127.0.0.1:8800")
READ = os.environ.get("DOCVAULT_CLAIMCORE_READ_KEY", "ro-corvus-7f3a9c")
WRITE = os.environ.get("WORKQUEUE_WRITE_KEY", "wq-corvus-2b8e1d")

def get(path, key=None):
    req = urllib.request.Request(BASE + path, headers={"X-API-Key": key} if key else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()

ok = True
def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name); ok &= cond

s, b = get("/health"); check("server is running", s == 200)
if s != 200: sys.exit("Start it first:  python corvus_systems.py")
h = json.loads(b); print(f"     {h['requests']} requests, {h['documents']} documents, {h['members']} members")
s, b = get("/docvault/requests/PA-2610-43235/documents", READ); check("DocVault list with the read key", s == 200)
doc = json.loads(b)["documents"][0]["doc_id"]
s, b = get(f"/docvault/documents/{doc}/file", READ); check("DocVault file download (PDF)", s == 200 and b[:4] == b"%PDF")
s, b = get("/claimcore/members/CVH36109074", READ); check("ClaimCore member lookup", s == 200)
s, b = get("/workqueue/requests/PA-2610-43235", WRITE); check("Work queue with the write key", s == 200)
s, b = get("/workqueue/requests/PA-2610-43235", READ); check("Read key is refused by the work queue (expected 403)", s == 403)
print("\nAll good." if ok else "\nSomething is wrong: see the FAIL lines.")
