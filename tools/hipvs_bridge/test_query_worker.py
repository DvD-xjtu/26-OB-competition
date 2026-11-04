#!/usr/bin/env python3
"""Exercise the production adaptor callback/worker with a fake GPU bridge.

These are CPU synchronization and integration checks, not GPU validation.
"""
import argparse
import os
from pathlib import Path
import json
import re
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
ADAPTOR = ROOT / "src/oblib/lib/vector/ob_vsag_adaptor.cpp"
HEADER = ROOT / "src/oblib/lib/vector/cuvs_search_worker.h"

PREAMBLE = r'''
#include <atomic>
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <iostream>
#include <memory>
#include <pthread.h>
#include <thread>
#include <vector>

static std::atomic<int> create_count{0};
static std::atomic<bool> reject_create{false};
static int checked_create(pthread_t *t, const pthread_attr_t *a,
                          void *(*fn)(void *), void *arg) {
  ++create_count;
  if (reject_create) return EAGAIN;
  return pthread_create(t, a, fn, arg);
}
#ifndef BASELINE
#define pthread_create checked_create
#include "cuvs_search_worker.h"
#undef pthread_create
using oceanbase::common::obvsag::CuvsSearchWorker;
#endif

struct ObCuvsEntry {
  std::shared_ptr<void> bridge_;
  size_t built_n_ = 0;
  std::vector<float> buf_vecs_;
  std::vector<int64_t> buf_ids_, ids_;
};
static int fake_handle;
static std::atomic<int> build_count{0}, search_count{0};
static pthread_t search_thread;
static bool have_search_thread = false;
static bool require_same_thread = false;
static std::atomic<bool> fail_search{false};
static void *seekdb_cuvs_build(const float *, long, long) {
  ++build_count;
  return &fake_handle;
}
static std::shared_ptr<void> ob_cuvs_wrap(void *p) {
  return std::shared_ptr<void>(p, [](void *) {});
}
static int seekdb_cuvs_search(void *, const float *q, long nq, long k,
                            unsigned *ids, float *dist) {
  assert(nq == 1);
  if (require_same_thread && have_search_thread)
    assert(pthread_equal(search_thread, pthread_self()));
  search_thread = pthread_self();
  have_search_thread = true;
#ifdef __APPLE__
  assert(pthread_get_stacksize_np(pthread_self()) >= 32UL * 1024 * 1024);
#else
  pthread_attr_t attr;
  assert(pthread_getattr_np(pthread_self(), &attr) == 0);
  size_t stack_size = 0;
  assert(pthread_attr_getstacksize(&attr, &stack_size) == 0);
  assert(stack_size >= 32UL * 1024 * 1024);
  pthread_attr_destroy(&attr);
#endif
  ++search_count;
  if (fail_search) return 17;
  for (long i = 0; i < k; ++i) { ids[i] = unsigned(q[0]) + i; dist[i] = q[0] + i; }
  return 0;
}
'''

MAIN = r'''
static void prepare(ObCuvsEntry &ent) {
  ent.buf_vecs_ = {1, 2, 3, 4}; ent.buf_ids_ = {101, 303};
}
int main() {
  const pthread_t caller = pthread_self();
  ObCuvsEntry ent; prepare(ent);
  float q = 7;
  std::vector<unsigned> ids(2);
  std::vector<float> dist(2);
  ObCuvsJob job{&ent, &q, 2, 2, 2, true, &ids, &dist, -1, false};
#ifdef BASELINE
  pthread_t tid; pthread_attr_t attr;
  assert(pthread_attr_init(&attr) == 0);
  assert(pthread_attr_setstacksize(&attr, 32UL * 1024 * 1024) == 0);
  assert(pthread_create(&tid, &attr, ob_cuvs_job, &job) == 0);
  assert(pthread_join(tid, nullptr) == 0);
  pthread_attr_destroy(&attr);
#else
  {
  CuvsSearchWorker worker(ob_cuvs_job);
  reject_create = true;
  assert(!worker.run(&job));
  assert(search_count == 0 && build_count == 0 && job.rc_ == -1);
  reject_create = false;
  assert(!worker.run(nullptr));
  require_same_thread = true;
  assert(worker.run(&job));
#endif
  assert(job.rc_ == 0 && job.built_);
  assert(ent.built_n_ == 2 && ent.ids_ == ent.buf_ids_);
  assert(ids[0] == 7 && ids[1] == 8 && dist[1] == 8);
  assert(!pthread_equal(caller, search_thread));
#ifndef BASELINE
  job.need_build = false; job.built_ = false;
  fail_search = true;
  assert(worker.run(&job) && job.rc_ == 17 && !job.built_);
  fail_search = false;
  job.rc_ = -1; job.n = 3;
  int searches_before = search_count;
  assert(worker.run(&job) && job.rc_ == -1 && search_count == searches_before);

  // Contending callers must receive their own completed job, not another's.
  std::vector<std::thread> callers;
  for (int t = 0; t < 8; ++t) callers.emplace_back([&, t] {
    ObCuvsEntry local; prepare(local);
    local.bridge_ = ob_cuvs_wrap(&fake_handle); local.built_n_ = 2;
    std::vector<unsigned> out(2); std::vector<float> distances(2);
    for (int i = 0; i < 500; ++i) {
      float value = float(t * 500 + i);
      ObCuvsJob task{&local, &value, 2, 2, 2, false, &out, &distances, -1, false};
      assert(worker.run(&task) && task.rc_ == 0);
      assert(out[0] == unsigned(value) && out[1] == unsigned(value) + 1);
      assert(distances[0] == value && distances[1] == value + 1);
    }
  });
  for (auto &t : callers) t.join();
  assert(build_count == 1 && search_count == 4002 && create_count == 2);
  } // The waiting worker must stop and join without hanging.
  for (int i = 0; i < 12; ++i) {
    CuvsSearchWorker worker(ob_cuvs_job);
    require_same_thread = false;
    job.n = 2; job.rc_ = -1;
    assert(worker.run(&job) && job.rc_ == 0);
  }
  { CuvsSearchWorker unused(ob_cuvs_job); }
#ifdef INTEGRATED
  // Compile and call the actual adaptor dispatch wrapper as well.
  reject_create = true;
  assert(!ob_cuvs_run_search_job(&job));
  reject_create = false;
  require_same_thread = false;
  assert(ob_cuvs_run_search_job(&job) && job.rc_ == 0);
  require_same_thread = true;
  assert(ob_cuvs_run_search_job(&job) && job.rc_ == 0);
#endif
#endif
  std::cout << "PASS: callback, stack, completion, thread identity";
#ifndef BASELINE
  std::cout << ", 4000 contended jobs, startup failure/retry, shutdown";
#endif
  std::cout << std::endl;
}
'''


def compile_adaptor(database, source_ref=None, extra_flags=()):
    """Compile the full source with real project headers, not the fake bridge.

    A compatible checkout's compile database may supply the local platform port
    and dependency paths. Source include roots are then mapped to this checkout.
    This is a translation-unit check, not a Linux/ROCm build or link check.
    """
    for entry in json.loads(database.read_text()):
        path = Path(entry["file"])
        if str(path).endswith("/src/oblib/lib/vector/ob_vsag_adaptor.cpp"):
            original = str(path).split("/src/oblib/lib/vector/")[0]
            break
        if path.is_file():
            match = re.search(r'#include\s+"([^"]*/src/oblib/lib/vector/ob_vsag_adaptor\.cpp)"', path.read_text(errors="ignore"))
            if match:
                original = match.group(1).split("/src/oblib/lib/vector/")[0]
                break
    else:
        raise RuntimeError("No adaptor translation unit found in compile database")
    args = entry.get("arguments") or shlex.split(entry["command"])
    flags, index = [], 0
    while index < len(args):
        arg = args[index]
        if arg in ("-o", "-MF", "-MT", "-MQ"):
            index += 2
            continue
        if arg in ("-c", "-MD", "-MMD") or arg == entry["file"]:
            index += 1
            continue
        if arg.startswith("-I" + original + "/src"):
            arg = arg.replace(original + "/src", str(ROOT / "src"), 1)
        flags.append(arg)
        index += 1
    flags += ["-DOB_BUILD_CUVS=1", "-fsyntax-only", "-I" + str(ADAPTOR.parent)]
    flags += list(extra_flags)
    with tempfile.TemporaryDirectory(prefix="seekdb-adaptor-compile-") as tmp:
        source = ADAPTOR
        if source_ref:
            source = Path(tmp) / "ob_vsag_adaptor.cpp"
            source.write_bytes(subprocess.check_output(
                ["git", "show", f"{source_ref}:src/oblib/lib/vector/ob_vsag_adaptor.cpp"], cwd=ROOT))
        result = subprocess.run(flags + [str(source)], cwd=entry["directory"], timeout=120)
        if result.returncode:
            raise SystemExit(result.returncode)
    print("PASS: complete adaptor translation unit with real project headers", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--sanitize", choices=("address", "thread"))
    parser.add_argument("--compile-commands", type=Path, help="Check the complete adaptor using a compatible project compile database")
    parser.add_argument("--source-ref", help="Compile an earlier Git source revision as a regression control")
    parser.add_argument("--extra-flag", action="append", default=[], help="Explicit host-compiler adjustment for the full-source check only")
    args = parser.parse_args()
    if args.compile_commands:
        compile_adaptor(args.compile_commands, args.source_ref, args.extra_flag)
        return
    source = ADAPTOR.read_text()
    callback = source[source.index("struct ObCuvsJob {"):source.index("// [BATCH] Feed")]
    integrated = "// Reuse one large-stack GPU search worker." in callback
    if args.baseline and integrated:
        callback = callback[:callback.index("// Reuse one large-stack GPU search worker.")]
    if integrated:
        search = source[source.index("static bool ob_cuvs_try_search("):source.index("static const char OB_CUVS_SNAPSHOT_MAGIC")]
        assert "ob_cuvs_run_search_job(&job)" in search
        assert "pthread_create" not in search
        assert '#include "cuvs_search_worker.h"' in source
    with tempfile.TemporaryDirectory(prefix="seekdb-worker-test-") as tmp:
        cpp, binary = Path(tmp) / "test.cpp", Path(tmp) / "test"
        cpp.write_text(PREAMBLE + callback + MAIN)
        cmd = [os.environ.get("CXX", "c++"), "-std=c++17", "-pthread", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-I", str(HEADER.parent), str(cpp), "-o", str(binary)]
        if args.baseline:
            cmd.insert(1, "-DBASELINE")
        elif integrated:
            cmd.insert(1, "-DINTEGRATED")
        if args.sanitize:
            cmd[1:1] = [f"-fsanitize={args.sanitize}", "-fno-omit-frame-pointer", "-g"]
        subprocess.run(cmd, check=True, timeout=60)
        subprocess.run([str(binary)], check=True, timeout=45)


if __name__ == "__main__":
    main()
