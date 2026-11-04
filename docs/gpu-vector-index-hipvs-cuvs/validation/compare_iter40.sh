#!/usr/bin/env bash
set -euo pipefail

repo=$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)
cd "$repo"
export TMPDIR="${TMPDIR:-/workspace}"
# The earlier V5 profiling run already produced this bridge. Preserve it.
reference="$repo/tools/hipvs_bridge/libseekdb_cuvs_bridge.so"
if [[ ! -f "$reference" ]]; then
  echo "Missing the previously built V5 bridge: $reference" >&2
  exit 2
fi

variant=$(mktemp -d "$TMPDIR/seekdb-iter40-bridge.XXXXXX")
candidate="$variant/libseekdb_cuvs_bridge.so"
bash tools/hipvs_bridge/build.sh "$candidate"

profile=docs/gpu-vector-index-hipvs-cuvs/validation/profile_offline_ddl.py
for dim in 128 256; do
  echo "V5 iterations=100 dim=$dim"
  python3 "$profile" --dim "$dim" --bridge "$reference" --discard-store "$@"
  echo "Candidate iterations=40 dim=$dim"
  python3 "$profile" --dim "$dim" --bridge "$candidate" --discard-store "$@"
done
