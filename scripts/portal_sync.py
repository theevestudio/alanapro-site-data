#!/usr/bin/env python3
"""Build the encrypted client-portal files for alanapro.com/portal.

Input: one JSON file holding the raw Notion query rows:
  {"clients": [...], "invoices": [...], "contracts": [...], "proposals": [...], "plans": [...]}
(column names exactly as the Notion SQL queries return them).

For every client with "Website Portal" checked and a "Portal Key", writes portal/<id>.json, encrypted with
AES-256-GCM using a key derived from the Portal Key. The repo is public, but a
file can only be found and read by someone holding that client's link.
Files whose content has not changed are left alone, so git only sees real updates.
Files for clients whose key was removed are deleted.

Usage: python3 scripts/portal_sync.py raw.json
"""
import base64, hashlib, hmac, json, os, re, sys
from datetime import datetime, timezone
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "portal")

HIDE_INVOICE = {"Draft", "Send", "VOID"}
HIDE_CONTRACT = {"Draft"}


def pid(v):
    """Notion page URL / id / JSON list of URLs -> first 32-hex id."""
    if not v:
        return None
    if isinstance(v, str) and v.startswith("["):
        try:
            v = (json.loads(v) or [None])[0]
        except Exception:
            pass
    if not v:
        return None
    m = re.search(r"([0-9a-f]{32})", str(v).replace("-", ""))
    return m.group(1) if m else None


def file_id(key):
    return hashlib.sha256(("alanapro-portal-file:" + key).encode()).hexdigest()[:32]


def enc_key(key):
    return hashlib.sha256(("alanapro-portal-enc:" + key).encode()).digest()


def b64(b):
    return base64.b64encode(b).decode()


def clean(s):
    return (s or "").strip() or None


def build(raw):
    by_client = {}
    for c in raw.get("clients", []):
        key = clean(c.get("Portal Key"))
        cid = pid(c.get("url"))
        on = c.get("Website Portal", "__YES__") == "__YES__"  # the on/off switch in Notion
        if on and key and cid:
            by_client[cid] = {"key": key, "row": c}

    out = {}
    for cid, info in by_client.items():
        c = info["row"]
        inv = [i for i in raw.get("invoices", []) if pid(i.get("Client")) == cid and i.get("Status") not in HIDE_INVOICE]
        inv.sort(key=lambda i: (i.get("date:Issue Date:start") or "", i.get("Invoice #") or ""), reverse=True)
        con = [k for k in raw.get("contracts", []) if pid(k.get("Client")) == cid and k.get("Status") not in HIDE_CONTRACT]
        con.sort(key=lambda k: k.get("date:Start Date:start") or k.get("createdTime") or "", reverse=True)
        pro = [p for p in raw.get("proposals", []) if pid(p.get("Client")) == cid]
        pro.sort(key=lambda p: p.get("createdTime") or "", reverse=True)
        pla = [p for p in raw.get("plans", []) if cid in [pid(x) for x in (json.loads(p["Client"]) if str(p.get("Client") or "").startswith("[") else [p.get("Client")])]
               and p.get("Hide from portal") != "__YES__" and clean(p.get("Link"))]
        pla.sort(key=lambda p: p.get("date:Month:start") or "", reverse=True)

        out[cid] = (info["key"], {
            "v": 1,
            "name": clean(c.get("Client Name")),
            "business": clean(c.get("Business Name")),
            "rella": clean(c.get("Access RELLA Space")),
            "plans": [{"title": clean(p.get("Plan")), "month": p.get("date:Month:start"), "url": clean(p.get("Link"))} for p in pla],
            "invoices": [{
                "num": clean(i.get("Invoice #")) or clean(i.get("Invoice")),
                "issued": i.get("date:Issue Date:start"),
                "due": i.get("date:Due Date:start"),
                "amount": i.get("Amount"),
                "status": i.get("Status"),
                "pay": clean(i.get("Pay Link")),
            } for i in inv],
            "contracts": [{
                "title": clean(k.get("Contract")),
                "status": k.get("Status"),
                "start": k.get("date:Start Date:start"),
                "signed": k.get("date:Signed Date:start"),
                "link": clean(k.get("Drive Link")),
            } for k in con],
            "proposals": [{
                "title": clean(p.get("Proposal")),
                "status": p.get("Status"),
                "sent": p.get("date:Sent Date:start"),
                "sections": [[label, val] for label, val in [
                    ("Objective", clean(p.get("Objective"))),
                    ("What's included", clean(p.get("What's Included")) or clean(p.get("What’s Included"))),
                    ("Packages", clean(p.get("Signature Content Packages"))),
                    ("Investment & terms", clean(p.get("Investment & Terms"))),
                    ("Not included", clean(p.get("Not Included"))),
                    ("The result", clean(p.get("The Result"))),
                ] if val],
            } for p in pro],
        })
    return out


def main(path):
    raw = json.load(open(path))
    data = build(raw)
    os.makedirs(OUT, exist_ok=True)
    keep, changed = set(), 0
    for cid, (key, payload) in data.items():
        fid = file_id(key)
        keep.add(fid + ".json")
        plain = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        h = hmac.new(enc_key(key), plain, hashlib.sha256).hexdigest()[:32]
        dest = os.path.join(OUT, fid + ".json")
        if os.path.exists(dest):
            try:
                if json.load(open(dest)).get("h") == h:
                    continue
            except Exception:
                pass
        payload["updated"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
        body = json.dumps(payload, ensure_ascii=False).encode()
        iv = os.urandom(12)
        ct = AESGCM(enc_key(key)).encrypt(iv, body, None)
        json.dump({"v": 1, "h": h, "iv": b64(iv), "ct": b64(ct)}, open(dest, "w"))
        changed += 1
    removed = 0
    for f in os.listdir(OUT):
        if f.endswith(".json") and f not in keep:
            os.remove(os.path.join(OUT, f)); removed += 1
    print(f"portals: {len(data)}  updated: {changed}  removed: {removed}")


if __name__ == "__main__":
    main(sys.argv[1])
