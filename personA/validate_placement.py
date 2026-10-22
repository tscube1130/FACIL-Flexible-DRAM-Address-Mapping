#!/usr/bin/env python3
"""FACIL standalone AiM layout audit using paper Figures 8-10.
Does not modify the mapper, simulate PIM execution, or invent hardware timings.
"""
from __future__ import annotations
import csv
import json
import sys
from collections import Counter
from pathlib import Path

# Place this script in personA/ alongside facil_mapper.py.
from facil_mapper import AiMMapper, Geometry, choose_mapid

OUT = Path('personA/results/llama3_validation/placement_audit')
# Paper Fig. 10 is a distinct illustrative memory organization.
PAPER = Geometry(channels=2, ranks=1, banks_per_rank=16)
# Current evaluation setup chosen earlier by the project, not the paper's Fig. 10 geometry.
EVAL = Geometry(channels=4, ranks=2, banks_per_rank=16)
CASES = [
    ('q_o', 4096, 4096, 2, False),
    ('k_v', 1024, 4096, 2, False),
    ('ffn_gate_up', 14336, 4096, 2, False),
    ('ffn_down', 4096, 14336, 3, True),
]

def pu_of(loc):
    return (loc.channel, loc.rank, loc.bank)

def audit_case(name: str, rows: int, cols: int, exp_mid: int, exp_partition: bool):
    geo = EVAL
    assert cols % geo.chunk_columns == 0, f'{name}: partial chunks require separate handling'
    mid, partition, rounded = choose_mapid(cols, geo)
    assert (mid, partition) == (exp_mid, exp_partition), (name, mid, partition)
    mapper = AiMMapper(geo, mid)
    n_chunks = cols // geo.chunk_columns
    row_hist = Counter()
    page_crossings = 0
    row_records = []
    seen_chunk_starts = set()
    checked = 0
    for r in range(rows):
        pus = set()
        row_first = r * cols * geo.element_bytes
        row_last = row_first + cols * geo.element_bytes - 1
        crosses_page = (row_first // geo.page_bytes != row_last // geo.page_bytes)
        page_crossings += int(crosses_page)
        for k in range(n_chunks):
            a = row_first + k * geo.chunk_bytes
            assert a % geo.chunk_bytes == 0, (name, r, k, 'chunk misaligned')
            first = mapper.decode(a)
            last = mapper.decode(a + geo.chunk_bytes - 1)
            assert (pu_of(first), first.row) == (pu_of(last), last.row), (name, r, k, 'chunk crosses bank/DRAM row')
            assert mapper.encode(first) == a, (name, r, k, 'round trip failed')
            assert mapper.encode(last) == a + geo.chunk_bytes - 1, (name, r, k, 'last-byte round trip failed')
            assert first.column == 0 and first.byte_offset == 0, (name, r, k, 'chunk not at row start')
            # Confirm that every 128-byte DRAMsim3 proxy transaction fits the same 2KiB chunk/row.
            for off in range(0, geo.chunk_bytes, geo.trace_transaction_bytes):
                lo = mapper.decode(a + off)
                hi = mapper.decode(a + off + geo.trace_transaction_bytes - 1)
                assert (pu_of(lo), lo.row) == (pu_of(first), first.row), (name, r, k, off, 'transaction starts in wrong DRAM row')
                assert (pu_of(hi), hi.row) == (pu_of(first), first.row), (name, r, k, off, 'transaction crosses DRAM row')
            loc_key = (first.channel, first.rank, first.bank, first.row, first.column, first.byte_offset)
            assert loc_key not in seen_chunk_starts, (name, r, k, 'aliased chunk start')
            seen_chunk_starts.add(loc_key)
            pus.add(pu_of(first))
            checked += 1
        if not partition:
            assert len(pus) == 1, (name, r, 'nonpartitioned row touches multiple PUs')
        else:
            assert len(pus) >= 2, (name, r, 'partitioned row did not span multiple PUs')
        row_hist[len(pus)] += 1
        row_records.append({'layer': name, 'matrix_row': r, 'n_columns': cols,
                            'chunk_count': n_chunks, 'distinct_pus': len(pus),
                            'crosses_2MiB_page': crosses_page,
                            'row_start_hex': hex(row_first)})

    path = OUT / f'{name}_row_placement.csv'
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(row_records[0]))
        writer.writeheader()
        writer.writerows(row_records)
    print(f'{name:12} {rows:5}x{cols:<5} MapID={mid} partition={partition!s:<5} '
          f'chunks={checked:,} PUs-per-row={dict(sorted(row_hist.items()))} '
          f'page-crossing-rows={page_crossings} PASS')
    return {'layer': name, 'rows': rows, 'cols': cols, 'mapid': mid,
            'partition': partition, 'rounded_selector_row_bytes': rounded,
            'compact_logical_row_bytes': cols * geo.element_bytes,
            'checked_chunks': checked, 'checked_128B_transactions': checked * geo.chunk_bytes // geo.trace_transaction_bytes,
            'distinct_pus_per_row_histogram': dict(sorted(row_hist.items())),
            'rows_crossing_2MiB_page': page_crossings, 'csv': str(path)}

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    assert choose_mapid(8192, PAPER)[:2] == (3, False), 'Paper Fig 10A MapID mismatch'
    assert choose_mapid(65536, PAPER)[:2] == (5, True), 'Paper Fig 10B MapID mismatch'
    print('PASS paper Fig. 10 anchors (2 channels x 1 rank x 16 banks): MapID 3, MapID 5')
    print('Evaluation geometry: 4 channels x 2 ranks x 16 banks/rank; 2MiB page, FP16, AiM (1,1024)')
    results = [audit_case(*case) for case in CASES]
    out = {
      'classification': 'standalone, paper-grounded address-placement validation; not DRAMsim3 or PIM performance',
      'paper_anchors': {'2048x8192': 3, '2048x65536': 5},
      'geometry': {'channels': 4, 'ranks_per_channel': 2, 'banks_per_rank': 16,
                   'huge_page_bytes': EVAL.page_bytes, 'AiM_chunk_columns': 1024,
                   'FP16_bytes': 2, 'physical_DRAM_transfer_bytes': 32,
                   'separate_DRAMsim3_proxy_transaction_bytes': 128},
      'cases': results,
      'not_verified': ['Native LPDDR5 protocol', 'DRAMsim3 decoder matches MapID mapping',
                       'PIM instruction timing, register contention, reductions',
                       'Bank lock-step scheduling and interference',
                       'Whether compact 14336-column row-stride is optimal or explicitly intended by the paper'],
    }
    (OUT / 'summary.json').write_text(json.dumps(out, indent=2) + '\n')
    print('Saved:', OUT / 'summary.json')
    print('No mapper source or DRAMsim3 config was modified.')

if __name__ == '__main__':
    main()
