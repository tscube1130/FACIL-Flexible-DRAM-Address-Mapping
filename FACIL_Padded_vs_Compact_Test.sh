#!/usr/bin/env bash
# FACIL — compact-vs-padded address-placement and standard BLAS leading-dimension test
# ------------------------------------------------------------------------------
# PURPOSE: Test the Llama3-8B FFN-down weight matrix (4096 x 14336, FP16) with
#          either compact 28-KiB logical rows or 32-KiB padded row stride.
#          Use exactly the SAME, unchanged personA/facil_mapper.py in both cases.
#
# RUN IN WSL:
#   1. Copy this single script into ~/DRAMsim3/DRAMsim3-master/ .
#   2. cd ~/DRAMsim3/DRAMsim3-master
#   3. bash FACIL_Padded_vs_Compact_Test.sh
#   4. Send the printed results, especially BLAS_SGEMM and the summary.json.
#
# PRECONDITIONS: Python 3 and NumPy (pip install numpy if missing).
# OPTIONAL:      libblas.so.3 provides a REAL standard CBLAS SGEMM check.
#                If missing, it reports BLAS_SGEMM=SKIPPED, not PASS.
#
# OUTPUT DIRECTORY: personA/results/llama3_validation/compact_vs_padded/
#   terminal_output.txt, summary.json, sampled_row_placement.csv
#
# GUARANTEES: Doesn't edit personA/facil_mapper.py, DRAMsim3 source or configs.
#             No DRAMsim3 benchmark, no native PIM timing, no custom GEMM kernel.
#             SGEMM checks FP32 *leading-dimension semantics* on 16 sampled rows.
#             Address placement uses full FP16 geometry on ALL 4096 rows.
# ------------------------------------------------------------------------------
set -euo pipefail

if [[ ! -f personA/facil_mapper.py ]]; then
  echo "ERROR: Run from DRAMsim3 repo root containing personA/facil_mapper.py" >&2
  exit 1
fi
python3 -c 'import numpy' || {
  echo "ERROR: NumPy missing (python3 -m pip install numpy)" >&2
  exit 1
}

OUT='personA/results/llama3_validation/compact_vs_padded'
mkdir -p "$OUT"
export FACIL_TEST_OUT="$OUT"
BEFORE_SHA=$(sha256sum personA/facil_mapper.py | awk '{print $1}')

python3 - <<'PY' | tee "$OUT/terminal_output.txt"
import csv
import ctypes
import ctypes.util
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path.cwd() / 'personA'))
from facil_mapper import Geometry, AiMMapper, choose_mapid

M, K = 4096, 14336                  # Llama3-8B FFN-down, weights stored as FP16
PAD_K = 16384                       # 16 * 1024 elements = 32 KiB at FP16
CHUNK_COLS = 1024
SAMPLE_ROWS = 16                    # Numerical test; placement checks all 4096
OUT = Path(os.environ['FACIL_TEST_OUT'])
G = Geometry(channels=4, ranks=2, banks_per_rank=16)
mid, requires_partition, rounded_row_bytes = choose_mapid(K, G)
assert (mid, requires_partition, rounded_row_bytes) == (3, True, 32768)
mp = AiMMapper(G, mid)


def inspect_layout(stride_cols):
    pu_per_row = Counter()
    row_start_chunk_offsets = Counter()
    page_crossings = 0
    rows_with_inconsistent_start = 0
    rows_with_mixed_rank_or_bank = 0
    total_chunks = 0
    samples = []
    sample_indices = {0, 1, 2, 3, 63, 64, 72, 73, 74, 4095}
    for r in range(M):
        base = r * stride_cols * G.element_bytes
        last_byte = base + K * G.element_bytes - 1
        page_crossings += int(base // G.page_bytes != last_byte // G.page_bytes)
        offset = (base // G.chunk_bytes) % (G.page_bytes // G.total_pus // G.chunk_bytes)
        row_start_chunk_offsets[offset] += 1
        seen_pus = []
        seen_parts = []
        for c in range(0, K, CHUNK_COLS):
            addr = base + c * G.element_bytes
            last = addr + G.chunk_bytes - 1
            s, e = mp.decode(addr), mp.decode(last)
            pu = (s.channel, s.rank, s.bank)
            assert (e.channel, e.rank, e.bank, e.row) == (*pu, s.row), (stride_cols, r, c)
            assert mp.encode(s) == addr
            assert mp.encode(e) == last
            if not seen_pus or pu != seen_pus[-1]:
                seen_pus.append(pu)
                seen_parts.append({'pu': pu, 'start_col': c, 'start_rowlo': s.row & 7, 'chunks': 0})
            seen_parts[-1]['chunks'] += 1
            total_chunks += 1
        assert sum(p['chunks'] for p in seen_parts) == K // CHUNK_COLS
        pu_per_row[len(seen_pus)] += 1
        if seen_parts[0]['start_rowlo'] != 0:
            rows_with_inconsistent_start += 1
        if len({p[1:] for p in seen_pus}) != 1:
            rows_with_mixed_rank_or_bank += 1
        if r in sample_indices:
            samples.append({
                'layout': 'compact' if stride_cols == K else 'padded',
                'row': r,
                'base_byte_address': base,
                'start_chunk_offset_within_pu': offset,
                'pus': len(seen_pus),
                'parts': ' | '.join(
                    f'CH{p["pu"][0]}/R{p["pu"][1]}/B{p["pu"][2]} '
                    f'col={p["start_col"]} rowlo={p["start_rowlo"]} chunks={p["chunks"]}'
                    for p in seen_parts),
            })
    return {
        'fp16_stride_columns': stride_cols,
        'fp16_stride_bytes': stride_cols * G.element_bytes,
        'allocated_footprint_MiB': M * stride_cols * G.element_bytes / (1024 * 1024),
        'chunks_checked': total_chunks,
        'PUs_per_row_histogram': dict(sorted(pu_per_row.items())),
        'row_start_chunk_offset_within_PU_histogram': dict(sorted(row_start_chunk_offsets.items())),
        'rows_with_first_chunk_nonzero_DRAM_rowlo': rows_with_inconsistent_start,
        'rows_spanning_multiple_ranks_or_banks': rows_with_mixed_rank_or_bank,
        'rows_crossing_2MiB_page': page_crossings,
        'samples': samples,
    }


compact = inspect_layout(K)
padded = inspect_layout(PAD_K)

# Assertions on concrete placement properties; no claim of PIM-cycle correctness.
assert compact['chunks_checked'] == padded['chunks_checked'] == 57344
assert compact['PUs_per_row_histogram'] == {2: 2048, 3: 2048}
assert padded['PUs_per_row_histogram'] == {2: 4096}
assert compact['rows_crossing_2MiB_page'] == 48
assert padded['rows_crossing_2MiB_page'] == 0
assert padded['row_start_chunk_offset_within_PU_histogram'] == {0: M}
assert compact['row_start_chunk_offset_within_PU_histogram'] == {0: 1024, 2: 1024, 4: 1024, 6: 1024}
assert padded['rows_with_first_chunk_nonzero_DRAM_rowlo'] == 0
assert padded['rows_spanning_multiple_ranks_or_banks'] == 0

# Test explicit leading dimension with REAL standard CBLAS SGEMM where available.
# The storage geometry above is FP16. This SGEMM is deliberately FP32 to test
# standard BLAS stride/lda behavior, not native FP16 performance.
ri = np.arange(SAMPLE_ROWS, dtype=np.int64)[:, None]
ci = np.arange(K, dtype=np.int64)[None, :]
A = (((ri * 7 + ci * 11) % 13) - 6).astype(np.float32) / 16.0
x = (((np.arange(K, dtype=np.int64) * 3 + 5) % 11) - 5).astype(np.float32) / 8.0
A_pad = np.full((SAMPLE_ROWS, PAD_K), np.nan, dtype=np.float32)
A_pad[:, :K] = A
reference = np.ascontiguousarray(A) @ x
np_strided = A_pad[:, :K] @ x
assert np.allclose(reference, np_strided, atol=1e-2, rtol=1e-4)

blas_result = {'status': 'SKIPPED', 'reason': 'No compatible CBLAS SGEMM library found'}
lib = None
attempts = []
for libname in filter(None, (ctypes.util.find_library('blas'),
                             ctypes.util.find_library('openblas'),
                             'libblas.so.3', 'libopenblas.so.0')):
    try:
        candidate = ctypes.CDLL(libname)
        if hasattr(candidate, 'cblas_sgemm'):
            lib = candidate
            selected_lib = libname
            break
        attempts.append(libname + ': lacks cblas_sgemm')
    except OSError:
        continue
if lib is not None:
    sg = lib.cblas_sgemm
    ptr = ctypes.POINTER(ctypes.c_float)
    sg.argtypes = [ctypes.c_int] * 6 + [ctypes.c_float, ptr, ctypes.c_int,
                   ptr, ctypes.c_int, ctypes.c_float, ptr, ctypes.c_int]
    sg.restype = None
    out = np.empty(SAMPLE_ROWS, dtype=np.float32)
    A_p = A_pad.ctypes.data_as(ptr)
    x_p = np.ascontiguousarray(x).ctypes.data_as(ptr)
    out_p = out.ctypes.data_as(ptr)
    # CblasRowMajor=101; CblasNoTrans=111; M=16, N=1, K=14336
    # A's leading dimension is the padded stride in FP32 elements.
    sg(101, 111, 111, SAMPLE_ROWS, 1, K, ctypes.c_float(1.0),
       A_p, PAD_K, x_p, 1, ctypes.c_float(0.0), out_p, 1)
    max_err = float(np.max(np.abs(out - reference)))
    assert np.allclose(out, reference, atol=1e-2, rtol=1e-4), max_err
    blas_result = {'status': 'PASS', 'library': selected_lib,
                   'precision': 'FP32 for API/stride semantics, not native FP16',
                   'M_sample': SAMPLE_ROWS, 'N_output': 1, 'K': K,
                   'lda': PAD_K, 'max_abs_error': max_err}

# Include a negative control: treating the padded data as compact would touch
# NaN padding for rows after row 0. This is deliberately NOT a valid GEMM call.
misread = A_pad.ravel()[:SAMPLE_ROWS * K].reshape(SAMPLE_ROWS, K)
wrong_stride_detected = bool(np.isnan(misread[1:]).any())
assert wrong_stride_detected

mapper_path = Path('personA/facil_mapper.py')
source_sha = hashlib.sha256(mapper_path.read_bytes()).hexdigest()
result = {
    'test': 'FACIL FFN-down compact vs padded row placement + CBLAS leading dimension',
    'geometry': {'matrix_rows': M, 'logical_matrix_cols': K,
                 'fp16_bytes_per_element': G.element_bytes,
                 'channels': G.channels, 'ranks_per_channel': G.ranks,
                 'banks_per_rank': G.banks_per_rank, 'huge_page_bytes': G.page_bytes,
                 'PIM_chunk_cols': CHUNK_COLS, 'DRAM_transfer_bytes': G.dram_transfer_bytes},
    'mapid': mid, 'partition': requires_partition,
    'rounded_selector_row_bytes': rounded_row_bytes,
    'source_mapper_sha256': source_sha,
    'compact': {k: v for k, v in compact.items() if k != 'samples'},
    'padded': {k: v for k, v in padded.items() if k != 'samples'},
    'numpy_strided_numerical_check': 'PASS (16 sampled rows)',
    'standard_blas_sgemm': blas_result,
    'incorrect_compact_lda_on_padded_memory_exposes_padding': wrong_stride_detected,
    'not_verified': [
        'PIM cycle-level lock-step scheduling or input-register broadcasts',
        'Whether the paper explicitly mandates 32-KiB physical row padding',
        'Unmodified SoC GEMM API compatibility: padded matrix needs lda=16384',
        'FP16 GEMM performance or native LPDDR5 timing',
        'Actual DRAMsim3 mapid-aware physical controller'],
}

with (OUT / 'sampled_row_placement.csv').open('w', newline='') as f:
    rows = compact['samples'] + padded['samples']
    w = csv.DictWriter(f, fieldnames=['layout', 'row', 'base_byte_address',
                                      'start_chunk_offset_within_pu', 'pus', 'parts'])
    w.writeheader()
    w.writerows(rows)
with (OUT / 'summary.json').open('w') as f:
    json.dump(result, f, indent=2)
    f.write('\n')

print('EVALUATION GEOMETRY: 2MiB pages, 4CH x 2R x 16 banks/rank, AiM 1024 FP16 elements per chunk')
print(f'MATRIX: {M}x{K} FP16 | MapID={mid} | partition={requires_partition}')
for name, val in (('COMPACT', compact), ('PADDED', padded)):
    print(f'{name}: stride={val["fp16_stride_bytes"]//1024} KiB, '
          f'footprint={val["allocated_footprint_MiB"]:.0f} MiB, '
          f'PUs/row={val["PUs_per_row_histogram"]}, '
          f'row-start offsets (chunks)={val["row_start_chunk_offset_within_PU_histogram"]}, '
          f'page-crossings={val["rows_crossing_2MiB_page"]} PASS')
print('FULL-PLACEMENT CHECKS: 57,344 chunks/layout; same DRAM row and PU per chunk; reversible: PASS')
print('NUMPY STRIDED GEMV: PASS (16 sampled rows, no native timing)')
print(f'STANDARD_BLAS_SGEMM: {blas_result["status"]} '
      f'({blas_result.get("library", blas_result.get("reason"))}; lda={PAD_K} where applicable)')
print(f'WRONG_LDA_NEGATIVE_CONTROL: {"PASS" if wrong_stride_detected else "FAIL"}')
print('CAVEAT: Alignment/stride validation only; NOT a proof of PIM lock-step hardware execution.')
print('CAVEAT: Padded layout needs a non-default lda; transparent compact GEMM is NOT demonstrated.')
print('SAVED:', OUT / 'summary.json')
print('SAVED:', OUT / 'sampled_row_placement.csv')
PY

AFTER_SHA=$(sha256sum personA/facil_mapper.py | awk '{print $1}')
if [[ "$BEFORE_SHA" != "$AFTER_SHA" ]]; then
  echo 'ERROR: mapper source hash changed unexpectedly!' >&2
  exit 1
fi
echo 'MAPPER_SOURCE_UNCHANGED: PASS' | tee -a "$OUT/terminal_output.txt"
echo 'SEND BACK: terminal_output.txt + summary.json (or paste both)' | tee -a "$OUT/terminal_output.txt"
