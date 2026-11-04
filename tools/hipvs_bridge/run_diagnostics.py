#!/usr/bin/env python3
"""Local AMD development diagnostics, never a formal contest scorer."""

import argparse
import json
import os
from pathlib import Path
import random
import re
import resource
import shutil
import socket
import subprocess
import sys
import tempfile
import time


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
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                     prefix=".report-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return path


class DiagnosticRun:
    def __init__(self, directory, repo):
        self.directory = Path(directory)
        self.repo = Path(repo)
        self.report = {"kind": "synthetic_local_diagnostic", "status": "running",
                       "stage": "created", "completed_stages": [],
                       "formal_evaluation": False}

    def stage(self, name):
        self.report["stage"] = name
        write_report(self.directory, self.report)
        print(f"[AMD_DIAG] stage={name}", flush=True)

    def complete(self):
        self.report["completed_stages"].append(self.report["stage"])
        write_report(self.directory, self.report)

    def command(self, stage, command, log, env=None, timeout=7200):
        self.stage(stage)
        with (self.directory / log).open("w") as output:
            result = subprocess.run(command, cwd=self.repo, env=env, stdout=output,
                                    stderr=subprocess.STDOUT, timeout=timeout)
        if result.returncode:
            raise RuntimeError(f"{stage} exited {result.returncode}; see {log}")
        return self.directory / log


def check_ids(text, count, rows):
    ids = [int(value) for value in text.splitlines()]
    if len(ids) != count or len(set(ids)) != count or any(i < 1 or i > rows for i in ids):
        raise RuntimeError(f"result integrity failed: expected {count} distinct IDs in 1..{rows}")
    return ids


def run_smoke(args):
    repo = Path(__file__).resolve().parents[2]
    args.work_dir.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="seekdb-amd-diag-", dir=args.work_dir)).resolve()
    run = DiagnosticRun(directory, repo)
    print(f"Evidence: {directory}", flush=True)
    server = None
    server_log = None
    try:
        run.stage("preflight")
        if sys.platform != "linux":
            raise RuntimeError("ROCm execution requires Linux; collection/tests also work on this host")
        if not Path("/dev/kfd").exists():
            raise RuntimeError("/dev/kfd is missing; GPU device is not exposed")
        if shutil.disk_usage(directory).free < 24 * 1024**3:
            raise RuntimeError("less than 24 GiB free for the private 20 GiB data store")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", args.port))
        client = shutil.which("mysql") or shutil.which("obclient")
        if not client:
            candidate = repo / "deps/3rd/u01/obclient/bin/obclient"
            if os.access(candidate, os.X_OK):
                client = str(candidate)
            else:
                raise RuntimeError("mysql/obclient client is missing")
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                                  capture_output=True, text=True, check=True).stdout.strip()
        run.report.update(revision=revision, rows=args.rows, dim=args.dim, probes=args.probes)
        run.complete()

        bridge = repo / "tools/hipvs_bridge/libseekdb_cuvs_bridge.so"
        binary = repo / "build_release/src/observer/seekdb"
        env = dict(os.environ)
        env.update(HIPVS_ROOT="/opt/hipvs", ROCM_ROOT="/opt/rocm",
                   CMAKE_BUILD_PARALLEL_LEVEL=str(args.jobs))
        env["LD_LIBRARY_PATH"] = ":".join(filter(None, [str(bridge.parent),
                                  "/opt/hipvs/lib", "/opt/rocm/lib", env.get("LD_LIBRARY_PATH")]))
        if not args.skip_build:
            run.command("bridge_build", ["bash", "tools/hipvs_bridge/build.sh", str(bridge)],
                        "bridge-build.log", env=env)
            run.complete()
            run.command("cmake_configure", ["cmake", "-S", ".", "-B", "build_release", "-G", "Unix Makefiles",
                        "-DCMAKE_BUILD_TYPE=RelWithDebInfo", "-DOB_ENABLE_UNITY=ON", "-DOB_USE_LLD=ON",
                        "-DOB_BUILD_CUVS=ON", "-DOB_BUILD_CUVS_TRACE=OFF", f"-DCUVS_BRIDGE_LIB={bridge}"],
                        "configure.log", env=env)
            run.complete()
            run.command("seekdb_build", ["cmake", "--build", "build_release", "--target", "seekdb"],
                        "build.log", env=env)
            run.complete()
        if not os.access(binary, os.X_OK) or not bridge.is_file():
            raise RuntimeError("seekdb binary or bridge is missing")
        loader_log = run.command("loader", ["ldd", str(binary)], "loader.log", env=env)
        if "not found" in loader_log.read_text():
            raise RuntimeError("missing runtime library; see loader.log")
        run.complete()

        def sql(statement, timeout=360):
            result = subprocess.run([client, "--protocol=TCP", "-h127.0.0.1", f"-P{args.port}",
                                    "-uroot", "-ANB", "--connect-timeout=3", "--local-infile=1"],
                                   input="SET ob_query_timeout=300000000;" + statement,
                                   text=True, capture_output=True, timeout=timeout)
            if result.returncode:
                raise RuntimeError("SQL failed: " + result.stderr[-1500:])
            return result.stdout.strip()

        run.stage("server_start")
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if soft < 65535:
            resource.setrlimit(resource.RLIMIT_NOFILE, (min(65535, hard) if hard >= 0 else 65535, hard))
        server_log = (directory / "seekdb.stdout.log").open("w")
        server = subprocess.Popen([str(binary), "--nodaemon", "--port", str(args.port),
                                   "--base-dir", str(directory), "--data-dir", str(directory / "store"),
                                   "--parameter", "__min_full_resource_pool_memory=2147483648",
                                   "--parameter", "memory_budget=2G", "--parameter", "datafile_size=20G",
                                   "--parameter", "local_ip=127.0.0.1"],
                                  env=env, stdout=server_log, stderr=subprocess.STDOUT)
        (directory / "seekdb.pid").write_text(str(server.pid) + "\n")
        deadline = time.monotonic() + 180
        while True:
            if server.poll() is not None:
                raise RuntimeError(f"seekdb exited {server.returncode} during startup")
            try:
                if sql("SELECT 1;", timeout=5) == "1":
                    break
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("seekdb did not become ready in 180 seconds")
            time.sleep(1)
        mappings = Path(f"/proc/{server.pid}/maps").read_text()
        if not any(line.split(maxsplit=5)[-1] == str(bridge.resolve()) for line in mappings.splitlines()):
            raise RuntimeError("the actual process did not load this checkout's bridge")
        if not any(line.startswith("Starting seekdb ") and
                   line.rstrip().endswith(f"-{revision}.")
                   for line in (directory / "seekdb.stdout.log").read_text(errors="replace").splitlines()):
            raise RuntimeError("seekdb startup revision differs from this checkout; rebuild seekdb")
        run.report["loaded_bridge"] = str(bridge.resolve())
        run.complete()

        run.stage("load_synthetic_data")
        rng = random.Random(817)
        data = directory / "vectors.tsv"
        with data.open("w") as stream:
            for row in range(args.rows):
                vector = "[" + ",".join(f"{rng.uniform(-1, 1):.6f}" for _ in range(args.dim)) + "]"
                stream.write(f"{row + 1}\t{vector}\n")
                if row == 0:
                    first_probe = vector
        data_sql = str(data).replace("\\", "\\\\").replace("'", "''")
        sql(f"CREATE DATABASE amd_diagnostic; USE amd_diagnostic;"
            f"CREATE TABLE items(id BIGINT PRIMARY KEY, v VECTOR({args.dim}));"
            f"LOAD DATA LOCAL INFILE '{data_sql}' INTO TABLE items "
            "FIELDS TERMINATED BY '\\t' LINES TERMINATED BY '\\n' (id,v);")
        if sql("SELECT COUNT(*) FROM amd_diagnostic.items;") != str(args.rows):
            raise RuntimeError("loaded row count differs")
        run.complete()

        run.stage("gpu_ddl")
        begin = time.monotonic()
        sql("CREATE VECTOR INDEX idx ON amd_diagnostic.items(v) WITH "
            "(distance=l2,type=hnsw,lib=cuvs,m=16,ef_construction=200,ef_search=64);")
        ddl_seconds = time.monotonic() - begin
        run.complete()

        run.stage("gpu_first_query")
        begin = time.monotonic()
        first = sql(f"SELECT id FROM amd_diagnostic.items ORDER BY l2_distance(v,'{first_probe}') APPROXIMATE LIMIT 100;")
        run.report["synthetic_ddl_and_first_query_sec"] = ddl_seconds + (time.monotonic() - begin)
        check_ids(first, 100, args.rows)
        run.complete()

        run.stage("independent_probe_recall")
        rng = random.Random(20261104)
        recalls = {10: [], 100: []}
        for _ in range(args.probes):
            vector = "[" + ",".join(f"{rng.uniform(-1, 1):.6f}" for _ in range(args.dim)) + "]"
            query = f"SELECT id FROM amd_diagnostic.items ORDER BY l2_distance(v,'{vector}')"
            truth = check_ids(sql(query + " LIMIT 100;"), 100, args.rows)
            for k in recalls:
                ids = check_ids(sql(query + f" APPROXIMATE LIMIT {k};"), k, args.rows)
                recalls[k].append(len(set(ids) & set(truth[:k])) / k)
        run.report["synthetic_mean_recall"] = {str(k): sum(v) / len(v) for k, v in recalls.items()}
        run.complete()

        run.stage("cpu_vsag_smoke")
        sql(f"CREATE TABLE amd_diagnostic.cpu_items(id BIGINT PRIMARY KEY,v VECTOR({args.dim}));"
            "INSERT INTO amd_diagnostic.cpu_items SELECT id,v FROM amd_diagnostic.items;"
            "CREATE VECTOR INDEX cpu_idx ON amd_diagnostic.cpu_items(v) WITH "
            "(distance=l2,type=hnsw,lib=vsag,m=16,ef_construction=200,ef_search=64);")
        check_ids(sql(f"SELECT id FROM amd_diagnostic.cpu_items ORDER BY "
                      f"l2_distance(v,'{first_probe}') APPROXIMATE LIMIT 10;"), 10, args.rows)
        run.complete()

        run.stage("bridge_markers")
        server_log.flush()
        text = (directory / "seekdb.stdout.log").read_text(errors="replace")
        for event in ("build_ok", "serialize_ok", "search_ok"):
            if f"[AMD_DIAG] event={event}" not in text:
                raise RuntimeError(f"missing {event} marker; use this branch's diagnostic bridge")
        if re.search(r"\[AMD_DIAG\] event=\w+_failed", text):
            raise RuntimeError("bridge reported a failed operation; inspect retained diagnostic lines")
        run.complete()
        run.report.update(status="passed", stage="complete")
    except (Exception, KeyboardInterrupt) as error:
        run.report.update(status="failed", error=f"{type(error).__name__}: {error}")
    finally:
        if server is not None:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
            run.report["server_exit_code_after_cleanup"] = server.returncode
        if server_log is not None:
            server_log.close()
        run.report["logs"] = collect_logs(directory)
        if run.report["status"] == "passed" and not args.keep_store:
            shutil.rmtree(directory / "store", ignore_errors=True)
        path = write_report(directory, run.report)
        print(json.dumps(run.report, ensure_ascii=False, indent=2), flush=True)
        print(f"Report: {path}", flush=True)
    return 0 if run.report["status"] == "passed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect-only", type=Path)
    parser.add_argument("--work-dir", type=Path, default=Path("/workspace"))
    parser.add_argument("--port", type=int, default=2982)
    parser.add_argument("--rows", type=int, default=10000)
    parser.add_argument("--dim", type=int, choices=(128, 256), default=128)
    parser.add_argument("--probes", type=int, default=8)
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--skip-build", action="store_true",
                        help="reuse a seekdb binary and diagnostic bridge built from this branch")
    parser.add_argument("--keep-store", action="store_true")
    args = parser.parse_args()
    if args.collect_only:
        result = {"kind": "local_log_collection", "status": "collected"}
        # Keep an existing run's status/stage intact when recollecting its logs.
        report = args.collect_only / "report.json"
        if report.is_file() and not report.is_symlink():
            result = json.loads(report.read_text())
        result["logs"] = collect_logs(args.collect_only)
        path = write_report(args.collect_only, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"Report: {path}")
        return 0
    if not 1000 <= args.rows <= 250000 or not 1 <= args.probes <= 4096 or not 1 <= args.jobs <= 64:
        parser.error("require rows=1000..250000, probes=1..4096, jobs=1..64")
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")
    return run_smoke(args)


if __name__ == "__main__":
    sys.exit(main())
