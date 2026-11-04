#!/usr/bin/env python3
"""Local AMD development diagnostics, never a formal contest scorer."""

import argparse
import json
from pathlib import Path
import re


LOG_FILES = ("bridge-build.log", "configure.log", "build.log", "loader.log",
             "seekdb.stdout.log", "log/seekdb.log", "log/seekdb.log.wf")
MARKER = re.compile(r"\[AMD_DIAG\]|GPU CAGRA|VSAG fallback|CMake Error|"
                    r"(?:^|\s)(?:ERROR|FATAL|error:)|OB_SERVER_OUTOF_DISK_SPACE")


def collect_logs(directory, limit=80):
    """Read bounded tails of known files, never follow links outside this run."""
    root = Path(directory).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("run directory is not a directory")
    lines = []
    files = []
    for relative in LOG_FILES:
        path = root / relative
        if not path.is_file() or not path.resolve().is_relative_to(root):
            continue
        files.append(relative)
        with path.open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 256 * 1024))
            tail = stream.read().decode("utf-8", "replace")
        for line in tail.splitlines():
            if MARKER.search(line):
                lines.append({"file": relative, "line": line[:1000]})
    return {"files_found": files, "diagnostic_lines": lines[-limit:],
            "interpretation": "Missing messages do not establish success or failure."}


def write_report(directory, report):
    path = Path(directory) / "report.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect-only", type=Path, required=True)
    args = parser.parse_args()
    result = {"kind": "local_log_collection", "status": "collected",
              "logs": collect_logs(args.collect_only)}
    path = write_report(args.collect_only, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Report: {path}")


if __name__ == "__main__":
    main()
