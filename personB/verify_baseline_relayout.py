#!/usr/bin/env python3
"""Standalone baseline: software PIM-layout to SoC-layout conversion.

Models the paper's conventional SoC bit-field order:
  [ROW][RANK][COLUMN][BANK][CHANNEL][32B OFFSET]

This is a correctness reference, not a DRAMsim3 decoder
installation or a cycle-level PIM simulation.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "personA"))
from facil_mapper import Geometry, AiMMapper, choose_mapid

ROWS, COLS = 1024, 4096       # Real Llama3-8B K/V projection shape
BYTES_PER_ELEMENT = 2
TRANSFER = 32
SIZE = ROWS * COLS * BYTES_PER_ELEMENT

geo = Geometry(channels=4, ranks=2, banks_per_rank=16)
mapid, partition, _ = choose_mapid(COLS, geo)
pim = AiMMapper(geo, mapid)

def conventional_soc_address(loc):
    # SoC reference mapping: row:rank:column:bank:channel:offset
    return (
        (loc.row << 18)
        | (loc.rank << 17)
        | (loc.column << 11)
        | (loc.bank << 7)
        | (loc.channel << 5)
        | loc.byte_offset
    )

def pim_storage_address(logical_address):
    loc = pim.decode(logical_address)
    return conventional_soc_address(loc)

# Identifiable values for every 32-byte fragment.
reference = bytearray(SIZE)
for offset in range(0, SIZE, TRANSFER):
    reference[offset:offset+TRANSFER] = (
        (offset // TRANSFER).to_bytes(4, "little") * 8
    )

# Baseline's PIM-optimized representation, under a fixed decoder.
pim_storage = bytearray(SIZE)
seen = bytearray(SIZE // TRANSFER)

for offset in range(0, SIZE, TRANSFER):
    physical = pim_storage_address(offset)
    assert physical % TRANSFER == 0
    assert 0 <= physical <= SIZE - TRANSFER
    assert not seen[physical // TRANSFER], "Address collision"
    seen[physical // TRANSFER] = 1
    pim_storage[physical:physical+TRANSFER] = (
        reference[offset:offset+TRANSFER]
    )

assert all(seen), "Some storage locations were never mapped"

# Baseline on-demand re-layout: gather from PIM layout
# into conventional contiguous SoC row-major layout.
soc_storage = bytearray(SIZE)

for offset in range(0, SIZE, TRANSFER):
    physical = pim_storage_address(offset)
    soc_storage[offset:offset+TRANSFER] = (
        pim_storage[physical:physical+TRANSFER]
    )

assert soc_storage == reference, "Re-layout mismatch!"

print("BASELINE RE-LAYOUT CORRECTNESS: PASS")
print(f"Matrix: {ROWS}x{COLS} FP16")
print(f"MapID used for PIM layout: {mapid}")
print(f"Source PIM-layout bytes: {SIZE:,}")
print(f"Destination SoC-layout bytes: {SIZE:,}")
print(f"32-byte fragments verified: {SIZE // TRANSFER:,}")
print("Every fragment restored to conventional row-major order.")
print("NOTE: No DRAMsim3 timing or PIM execution measured here.")
