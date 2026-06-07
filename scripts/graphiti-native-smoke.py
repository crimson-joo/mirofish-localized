#!/usr/bin/env python3
"""Graphiti native/repaired fact smoke for mirofish-localized.

Posts a message directly to the patched Graphiti service and verifies that
`/search` returns a Graphiti-native fact. This bypasses the MiroFish
compatibility cache, so PASS means the graph-memory service itself can store and
retrieve searchable facts.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"
STRICT_NATIVE = os.environ.get("GRAPHITI_NATIVE_ONLY_SMOKE", "0").lower() in {"1", "true", "yes"}
GROUP_ID = f"native_smoke_{int(time.time())}"
CONTENT = "Alice recommends Bob's MiroFish Graphiti native repair adapter for ZEP-free local runtime validation."


def request(method: str, path: str, payload: dict | None = None, timeout: int = 60):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="ignore")
        print(f"FAIL {method} {path} HTTP {exc.code} {raw}")
        raise


def main() -> int:
    status, health = request("GET", "/healthcheck", timeout=15)
    if status != 200:
        print(f"FAIL health status={status}")
        return 1
    print(f"PASS health {health}")

    payload = {
        "group_id": GROUP_ID,
        "messages": [
            {
                "uuid": f"episode_{GROUP_ID}",
                "name": "native repair smoke episode",
                "content": CONTENT,
                "role_type": "system",
                "role": "mirofish_native_smoke",
                "timestamp": datetime.now().isoformat(),
                "source_description": "mirofish native smoke",
            }
        ],
    }
    status, ingest = request("POST", "/messages", payload, timeout=180)
    if status not in {200, 202}:
        print(f"FAIL messages status={status} payload={ingest}")
        return 1
    print(f"PASS messages {ingest}")
    message = ingest.get("message", "") if isinstance(ingest, dict) else ""
    native_match = re.search(r"native=(\d+)", message)
    repaired_match = re.search(r"repaired=(\d+)", message)
    native_count = int(native_match.group(1)) if native_match else 0
    repaired_count = int(repaired_match.group(1)) if repaired_match else 0
    if STRICT_NATIVE and (native_count < 1 or repaired_count > 0):
        print(f"FAIL strict_native_extraction native={native_count} repaired={repaired_count}")
        return 1
    if STRICT_NATIVE:
        print(f"PASS strict_native_extraction native={native_count} repaired={repaired_count}")

    status, search = request(
        "POST",
        "/search",
        {"group_ids": [GROUP_ID], "query": "Alice Bob MiroFish native repair", "max_facts": 5},
        timeout=60,
    )
    facts = [row.get("fact", "") for row in search.get("facts", [])]
    joined = "\n".join(facts)
    if "MiroFish" not in joined or "Alice" not in joined:
        print("FAIL native_search no expected fact")
        print(json.dumps(search, ensure_ascii=False, indent=2)[:2000])
        return 1
    print(f"PASS native_search facts={len(facts)} group_id={GROUP_ID}")
    print(joined[:500])

    try:
        request("DELETE", f"/group/{GROUP_ID}", timeout=60)
        print("PASS cleanup")
    except Exception as exc:
        print(f"PARTIAL cleanup {exc!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
