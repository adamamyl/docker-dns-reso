import json
from typing import Dict

from net_tester.utils import run_cmd


def capture_processes_ndjson() -> Dict[str, object]:
    """
    Capture a snapshot of running processes as NDJSON.

    This data is diagnostic only:
    - not diffed
    - not logged
    - intentionally compact

    Each line represents one process.
    """
    cmd = ["ps", "-axo", "pid,ppid,uid,gid,comm"]
    result = run_cmd(cmd, check=True)

    lines = result.stdout.strip().splitlines()
    ndjson_lines = []

    for line in lines[1:]:  # skip header
        parts = line.strip().split(None, 4)
        if len(parts) != 5:
            continue

        pid, ppid, uid, gid, comm = parts
        if not pid.isdigit() or not uid.isdigit():
            continue

        uid_int = int(uid)
        gid_int = int(gid)

        record = {
            "pid": int(pid),
            "ppid": int(ppid),
            "uid": uid_int,
            "gid": gid_int,
            "comm": comm,
            "is_root": uid_int == 0,
        }

        ndjson_lines.append(json.dumps(record, separators=(",", ":")))

    return {
        "format": "ndjson",
        "count": len(ndjson_lines),
        "data": "\n".join(ndjson_lines),
    }
