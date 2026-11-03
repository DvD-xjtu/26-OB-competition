"""Read-only Git provenance check; never print remote URLs or credentials."""
import argparse
import json
import subprocess
from pathlib import Path


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def inspect(repo, base, candidate):
    result = {"repository": str(Path(repo).resolve()), "checks": {}}
    for label, ref in (("base", base), ("candidate", candidate)):
        p = git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
        if p.returncode:
            result["checks"][label] = "unresolved"
        else:
            result[label + "_commit"] = p.stdout.strip()
            result["checks"][label] = "resolved"
    if all(result["checks"].get(x) == "resolved" for x in ("base", "candidate")):
        p = git(repo, "merge-base", "--is-ancestor", result["base_commit"], result["candidate_commit"])
        shallow = git(repo, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"
        result["checks"]["ancestry"] = ("pass" if p.returncode == 0 else
                                         "unknown_shallow_history" if shallow else
                                         "fail" if p.returncode == 1 else "unknown")
    p = git(repo, "status", "--porcelain=v1")
    result["worktree_changes"] = p.stdout.splitlines() if p.returncode == 0 else None
    result["checks"]["worktree"] = "unknown" if p.returncode else "dirty" if p.stdout else "clean"
    result["branch"] = git(repo, "branch", "--show-current").stdout.strip() or "detached_or_unavailable"
    result["ready_for_runtime_validation"] = (result["checks"].get("ancestry") == "pass"
                                               and result["checks"]["worktree"] == "clean")
    result["runtime_validation"] = "not_performed_by_this_script"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--candidate", default="HEAD")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = inspect(args.repo, args.base, args.candidate)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0 if result["ready_for_runtime_validation"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
