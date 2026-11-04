#!/usr/bin/env python3
"""Profile one offline CAGRA DDL on a fresh, private seekdb instance."""

import argparse
import json
import os
from pathlib import Path
import random
import resource
import shutil
import socket
import subprocess
import tempfile
import time


def main():
    repo = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=2981)
    parser.add_argument("--rows", type=int, default=10000)
    parser.add_argument("--dim", type=int, choices=(128, 256), default=128)
    args = parser.parse_args()
    if not 256 <= args.rows <= 250000:
        parser.error("--rows must be between 256 and 250000")

    observer = repo / "build_release/src/observer/seekdb"
    bridge = repo / "tools/hipvs_bridge/libseekdb_cuvs_bridge.so"
    bundled_client = repo / "deps/3rd/u01/obclient/bin/obclient"
    client = shutil.which("mysql") or shutil.which("obclient") or str(bundled_client)
    for executable in (observer, Path(client)):
        if not os.access(executable, os.X_OK):
            parser.error(f"missing executable: {executable}")
    if not bridge.is_file() or not Path("/dev/kfd").exists():
        parser.error("the bridge and /dev/kfd are required")
    with socket.socket() as probe_port:
        probe_port.bind(("127.0.0.1", args.port))

    evidence = Path(tempfile.mkdtemp(prefix="seekdb-cagra-profile-"))
    print(f"Evidence: {evidence}", flush=True)
    data = evidence / "vectors.tsv"
    rng = random.Random(817)
    with data.open("w") as file:
        for row in range(args.rows):
            vector = "[" + ",".join(f"{rng.uniform(-1, 1):.6f}" for _ in range(args.dim)) + "]"
            file.write(f"{row + 1}\t{vector}\n")
            if row == 0:
                query = vector

    trace = evidence / "trace.log"
    env = dict(os.environ, OB_VSAG_TRACE="1", OB_VSAG_TRACE_FILE=str(trace), OB_CUVS_TIMING="1")
    env.pop("OB_VSAG_USE_CUVS", None)
    env["LD_LIBRARY_PATH"] = os.pathsep.join(filter(None, (
        str(bridge.parent), "/opt/hipvs/lib", "/opt/rocm/lib", env.get("LD_LIBRARY_PATH")
    )))
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft < 65535:
        resource.setrlimit(resource.RLIMIT_NOFILE, (min(65535, hard) if hard >= 0 else 65535, hard))

    def sql(statement, timeout=600):
        return subprocess.run([
            client, "--protocol=TCP", "-h127.0.0.1", f"-P{args.port}", "-uroot", "-ANB",
            "--connect-timeout=3", "--local-infile=1",
            "-e", "set ob_query_timeout=540000000; " + statement,
        ], check=True, text=True, capture_output=True, timeout=timeout).stdout.strip()

    with (evidence / "seekdb.stdout.log").open("w") as log:
        server = subprocess.Popen([
            str(observer), "--nodaemon", "--port", str(args.port),
            "--base-dir", str(evidence), "--data-dir", str(evidence / "store"),
            "--parameter", "__min_full_resource_pool_memory=2147483648",
            "--parameter", "memory_budget=2G",
            "--parameter", "datafile_size=20G",
            "--parameter", "local_ip=127.0.0.1",
        ], env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 180
            while True:
                if server.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("seekdb did not become ready; see seekdb.stdout.log")
                try:
                    if sql("select 1", timeout=5) == "1":
                        break
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    time.sleep(1)

            sql(f"""create database profile_ddl; use profile_ddl;
                create table items(id bigint primary key, v vector({args.dim}));
                load data local infile '{data}' into table items
                fields terminated by '\\t' lines terminated by '\\n' (id,v);""")
            if int(sql("select count(*) from profile_ddl.items")) != args.rows:
                raise RuntimeError("loaded row count differs from the requested size")

            query_sql = f"select id from profile_ddl.items order by l2_distance(v,'{query}')"
            start = time.monotonic()
            sql("""use profile_ddl; create vector index idx on items(v)
                with (distance=l2,type=hnsw,lib=cuvs,m=16,ef_construction=200,ef_search=64);""")
            built = time.monotonic()
            ids = sql(query_sql + " approximate limit 100").splitlines()
            end = time.monotonic()
            records = trace.read_text().splitlines() if trace.is_file() else []
            phases = {}
            for line in records:
                fields = line.split()
                if len(fields) == 4 and fields[0].endswith("_us"):
                    phases.setdefault(fields[0], []).append(int(fields[2].removeprefix("a=")))
            if not all(phase in phases for phase in (
                "ddl_build_call_us", "ddl_graph_write_us", "ddl_snapshot_out_us",
                "query_bridge_us"
            )) or not any(line.startswith("cuvs_serve ") for line in records):
                raise RuntimeError("missing GPU DDL/search trace; use a build with OB_BUILD_CUVS_TRACE=ON")
            if len(ids) != 100 or len(set(ids)) != 100 or not all(1 <= int(i) <= args.rows for i in ids):
                raise RuntimeError("query returned invalid IDs")
            exact = set(sql(query_sql + " limit 100").splitlines())
            if len(exact) != 100:
                raise RuntimeError("exact query did not return 100 distinct IDs")
            result = {
                "rows": args.rows,
                "dim": args.dim,
                "ddl_s": built - start,
                "first_query_s": end - built,
                "ddl_and_first_query_s": end - start,
                "single_probe_recall_at_100": len(exact.intersection(ids)) / 100,
                "phase_samples_us": phases,
            }
            (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result, indent=2))
        except subprocess.CalledProcessError as error:
            print(error.stderr)
            raise
        finally:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__ == "__main__":
    main()
