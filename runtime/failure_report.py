from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--source-pin", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = {
        "schema": "externes-gehirn.runtime-bootstrap.v0.1",
        "candidate": args.candidate,
        "distribution": args.distribution,
        "expected_version": args.expected_version,
        "source_pin": args.source_pin,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "github_run_id": os.getenv("GITHUB_RUN_ID"),
        "github_sha": os.getenv("GITHUB_SHA"),
        "installed_version": None,
        "import_ok": False,
        "version_ok": False,
        "status": "BLOCKED",
        "error": f"{args.stage}_FAILED; inspect GitHub Actions job log for provider output",
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
