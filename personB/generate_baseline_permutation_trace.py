#!/usr/bin/env python3
"""Generate *baseline* re-layout DRAMsim3 traffic using a reversible address permutation.

This extends the existing sequential traffic proxy. It enumerates all 32-byte
weight fragments in logical row-major order, maps their PIM storage locations
into a separate fixed-layout address space, and issues each unique 128-byte
source read on first touch. Destination writes remain sequential. The 128-byte
first-touch coalescing assumes ideal reuse (one read per block), so this is a
controlled pattern sensitivity experiment, not a validated hardware re-layout
implementation or full timing bound.

The software reference fixed SoC mapping is [ROW][RANK][COL][BANK][CH][OFFSET].
DRAMsim3's independently configured decoder is *not* assumed to implement that
bit-field exactly; it merely times the injected address sequence. FACIL MapIDs
are NOT consumed by DRAMsim3 in this experiment.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # script at repo/personB/*.py
sys.path.insert(0, str(ROOT / 'personA'))
from facil_mapper import AiMMapper, Geometry, choose_mapid


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--rows', type=int, default=1024)
    p.add_argument('--cols', type=int, default=4096)
    p.add_argument('--src-base', type=lambda s: int(s, 0), default=0)
    p.add_argument('--dst-base', type=lambda s: int(s, 0), default=0x10000000)
    p.add_argument('--output', type=Path, default=Path('personB/traces/llama3_k_v_permutation'))
    a = p.parse_args()
    g = Geometry(channels=4, ranks=2, banks_per_rank=16)
    g.validate()
    if a.rows <= 0 or a.cols < 1024 or a.cols % 1024 != 0:
        p.error('rows must be positive; cols must be multiple of 1024 (AiM chunks)')
    F = g.dram_transfer_bytes  # 32 bytes: mapping granularity
    T = g.trace_transaction_bytes  # 128 bytes: simulator trace granularity
    SIZE = a.rows * a.cols * g.element_bytes
    if SIZE % T or a.src_base % T or a.dst_base % T:
        p.error('Size and base addresses must be 128-byte aligned')
    if max(a.src_base, a.dst_base) < min(a.src_base + SIZE, a.dst_base + SIZE):
        p.error('Source and destination regions overlap')
    mapid, partition, _ = choose_mapid(a.cols, g)
    aim = AiMMapper(g, mapid)

    # Reference conventional SoC address field packing, not the live DRAMsim3 map.
    off_bits = g.dram_transfer_bytes.bit_length() - 1
    ch_bits = g.channels.bit_length() - 1
    bank_bits = g.banks_per_rank.bit_length() - 1
    col_bits = g.dram_row_bytes.bit_length() - 1 - off_bits
    rank_bits = g.ranks.bit_length() - 1
    ch_shift = off_bits
    bank_shift = ch_shift + ch_bits
    col_shift = bank_shift + bank_bits
    rank_shift = col_shift + col_bits
    row_shift = rank_shift + rank_bits

    def position(addr: int) -> int:
        loc = aim.decode(addr)
        return (loc.byte_offset
                | (loc.channel << ch_shift)
                | (loc.bank << bank_shift)
                | (loc.column << col_shift)
                | (loc.rank << rank_shift)
                | (loc.row << row_shift))

    a.output.mkdir(parents=True, exist_ok=True)
    expected_frags = SIZE // F
    expected_blocks = SIZE // T
    seen_frag = bytearray(expected_frags)
    seen_block = bytearray(expected_blocks)
    unique_reads = 0
    source_consecutive = 0
    previous_read_block = None
    with (a.output / 'copy_read.trace').open('w', encoding='utf-8') as read_out:
        # Visit *logical* 32-B fragments in application order. First-touch
        # uniqueness is an OPTIMISTIC coalescing assumption, not a cache model.
        for i in range(expected_frags):
            phys = position(i * F)
            if phys % F or not (0 <= phys <= SIZE - F):
                raise AssertionError(f'Invalid storage address at fragment {i}: {phys}')
            frag_idx = phys // F
            if seen_frag[frag_idx]:
                raise AssertionError(f'Address alias at fragment {i}')
            seen_frag[frag_idx] = 1
            block_idx = phys // T
            if not seen_block[block_idx]:
                seen_block[block_idx] = 1
                if previous_read_block is not None and block_idx == previous_read_block + 1:
                    source_consecutive += 1
                previous_read_block = block_idx
                read_out.write(f'{a.src_base + block_idx*T:#x} READ {unique_reads}\n')
                unique_reads += 1
    if sum(seen_frag) != expected_frags or sum(seen_block) != expected_blocks:
        raise AssertionError('Incomplete/redundant address permutation')
    if unique_reads != expected_blocks:
        raise AssertionError('Unexpected 128B unique-block count')
    with (a.output / 'copy_write.trace').open('w', encoding='utf-8') as write_out:
        for i in range(expected_blocks):
            write_out.write(f'{a.dst_base + i*T:#x} WRITE {i}\n')

    manifest = {
        'matrix_shape': [a.rows, a.cols],
        'element_bytes': g.element_bytes,
        'matrix_bytes': SIZE,
        'transaction_bytes': T,
        'transactions_per_stage': expected_blocks,
        'total_read_and_write_bytes': 2*SIZE,
        'source_address_range': [hex(a.src_base), hex(a.src_base+SIZE)],
        'destination_address_range': [hex(a.dst_base), hex(a.dst_base+SIZE)],
        'read_trace': str(a.output/'copy_read.trace'),
        'write_trace': str(a.output/'copy_write.trace'),
        'method': 'first-touch unique-128B baseline source read order from a reference 32B PIM-storage permutation; sequential destination writes; ideal coalescing; no reshape computation or timing for permutation',
        'paper_reference_soc_field_order': 'row:rank:column:bank:channel:offset',
        'standalone_reference_pim_mapid': mapid,
        'partition_required': partition,
        'tested_32B_fragments': expected_frags,
        'verified_unique_128B_blocks': expected_blocks,
        'adjacent_incrementing_source_read_pairs': source_consecutive,
        'nonsequential_source_read_pairs': (expected_blocks - 1 - source_consecutive),
        'important_limitations': [
            'DRAMsim3 internal address decoder NOT changed to this reference mapping',
            'DRAMsim3 has no per-huge-page MapID in this experiment',
            'Each 128B block issued once on first touch: ideal reuse/coalescing',
            'Read and write stages separate; no CPU/GPU permutation cost',
            'LPDDR4 protocol with LPDDR5-style timing proxy; not native LPDDR5',
        ]
    }
    (a.output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'BASELINE PERMUTATION ADDRESS CHECK: PASS')
    print(f'Matrix={a.rows}x{a.cols} FP16; MapID={mapid}; partition={partition}')
    print(f'All {expected_frags:,} 32B fragments permute bijectively; {expected_blocks:,} distinct 128B source blocks')
    print(f'Source first-touch sequential next-block pairs: {source_consecutive:,}/{expected_blocks - 1:,}')
    print(f'Read/write traffic: {SIZE/T:,.0f} requests per stage; {2*SIZE/(1024*1024):.2f} MiB combined')
    print(f'Traces + manifest: {a.output}')
    print('LIMITATION: simulated controller decoder is not MapID-aware; first-touch read order is an optimistic traffic proxy.')

if __name__ == '__main__':
    main()
