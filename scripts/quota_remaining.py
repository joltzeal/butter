"""Estimate the Actions minutes left in the current billing month.

Prints "<used> <remaining>" on stdout. GitHub bills each job rounded up to the
minute times the runner multiplier (linux 1x, windows 2x, macos 10x); the
runs/{id}/timing endpoint answers 0 for this account, so the jobs endpoint is
used instead.

Progress goes to stderr. Anything unreadable degrades to the free-plan quota
rather than failing the release.
"""

from __future__ import annotations

import datetime
import json
import math
import os
import subprocess
import sys

MULT = {"windows": 2, "macos": 10}


def gh(path: str):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


def main() -> int:
    quota = os.environ.get("GITHUB_QUOTA_MINUTES", "").strip()
    if not quota:
        user = gh("user") or {}
        plan = (user.get("plan") or {}).get("name", "")
        quota = {"pro": 3000, "team": 10000}.get(plan, 2000)
        if not plan:
            print("   ! plan unreadable (gh token lacks the 'user' scope), assuming the free 2000", file=sys.stderr)
    quota = int(quota)

    now = datetime.datetime.now(datetime.timezone.utc)
    since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    used = 0.0

    for repo in gh("/user/repos?per_page=100&affiliation=owner") or []:
        if not repo.get("private"):
            continue
        name = repo["full_name"]
        print(f"   scanning {name}", file=sys.stderr)
        data = gh(f"/repos/{name}/actions/runs?created=%3E={since}&per_page=100") or {}
        for run in (data.get("workflow_runs") or [])[:100]:
            jobs = (gh(f"/repos/{name}/actions/runs/{run['id']}/jobs?per_page=100") or {}).get("jobs") or []
            for job in jobs:
                if not job.get("started_at") or not job.get("completed_at"):
                    continue
                start = datetime.datetime.fromisoformat(job["started_at"].replace("Z", "+00:00"))
                end = datetime.datetime.fromisoformat(job["completed_at"].replace("Z", "+00:00"))
                seconds = max(1.0, (end - start).total_seconds())
                labels = " ".join(job.get("labels") or []).lower()
                used += math.ceil(seconds / 60) * next((m for k, m in MULT.items() if k in labels), 1)

    used_min = math.ceil(used)
    print(f"{used_min} {quota - used_min}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
