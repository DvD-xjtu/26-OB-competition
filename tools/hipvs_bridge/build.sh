#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
HIPVS_ROOT=${HIPVS_ROOT:-/opt/hipvs}
ROCM_ROOT=${ROCM_ROOT:-/opt/rocm}
HIPCC=${HIPCC:-$ROCM_ROOT/bin/hipcc}
OUTPUT=${1:-$SCRIPT_DIR/libseekdb_cuvs_bridge.so}
DIAGNOSTIC_STAGE=preflight
trap 'rc=$?; printf "[AMD_DIAG] event=bridge_build_failed stage=%s line=%s rc=%s\n" "$DIAGNOSTIC_STAGE" "$LINENO" "$rc" >&2; exit "$rc"' ERR
printf '[AMD_DIAG] event=bridge_build_begin hipvs=%s rocm=%s output=%s\n' "$HIPVS_ROOT" "$ROCM_ROOT" "$OUTPUT" >&2

[[ -x "$HIPCC" ]] || { echo "[AMD_DIAG] event=bridge_build_failed stage=hipcc_missing path=$HIPCC" >&2; exit 2; }
[[ -f "$HIPVS_ROOT/include/cuvs/core/c_api.h" ]] || {
  echo "[AMD_DIAG] event=bridge_build_failed stage=headers_missing path=$HIPVS_ROOT/include" >&2
  exit 2
}
[[ -f "$HIPVS_ROOT/lib/libcuvs_c.so" ]] || {
  echo "[AMD_DIAG] event=bridge_build_failed stage=libcuvs_missing path=$HIPVS_ROOT/lib" >&2
  exit 2
}

mkdir -p "$(dirname "$OUTPUT")"

DIAGNOSTIC_STAGE=hipcc
"$HIPCC" \
  -shared \
  -fPIC \
  -O2 \
  -D__HIP_PLATFORM_AMD__ \
  -I"$HIPVS_ROOT/include" \
  -I"$ROCM_ROOT/include" \
  "$SCRIPT_DIR/seekdb_cuvs_bridge.c" \
  -L"$HIPVS_ROOT/lib" \
  -Wl,-soname,libseekdb_cuvs_bridge.so \
  -Wl,-rpath,"$HIPVS_ROOT/lib:$ROCM_ROOT/lib" \
  -lcuvs_c \
  -o "$OUTPUT"

echo "built $OUTPUT"
printf '[AMD_DIAG] event=bridge_build_ok output=%s\n' "$OUTPUT" >&2
