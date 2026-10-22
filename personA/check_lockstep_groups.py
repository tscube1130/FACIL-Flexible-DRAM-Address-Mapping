#!/usr/bin/env python3
"""Structural lock-step grouping audit for Llama3-8B FFN-down.

Not a cycle-level PIM simulator or a latency measurement.
"""

import json
from pathlib import Path
from collections import defaultdict, Counter
from facil_mapper import Geometry, AiMMapper, choose_mapid

ROWS = 4096
COLS = 14336

geo = Geometry(channels=4, ranks=2, banks_per_rank=16)
mapid, partition, _ = choose_mapid(COLS, geo)

assert mapid == 3 and partition
mapper = AiMMapper(geo, mapid)

def audit(name, stride_cols):
    groups = defaultdict(set)
    chunks = 0

    for r in range(ROWS):
        for chunk in range(COLS // geo.chunk_columns):
            col = chunk * geo.chunk_columns
            addr = (r * stride_cols + col) * geo.element_bytes
            loc = mapper.decode(addr)

            assert loc.column == 0
            assert loc.byte_offset == 0

            # Same channel, rank, DRAM row and input-vector segment.
            key = (loc.channel, loc.rank, loc.row, chunk)

            # A bank cannot contribute twice to the same command group.
            assert loc.bank not in groups[key]
            groups[key].add(loc.bank)
            chunks += 1

    occupancy = Counter(len(banks) for banks in groups.values())
    groups_per_rank = Counter(
        (ch, rank) for ch, rank, dram_row, chunk in groups
    )

    assert chunks == ROWS * (COLS // geo.chunk_columns)
    assert sum(k * v for k, v in occupancy.items()) == chunks

    return {
        "layout": name,
        "stride_columns": stride_cols,
        "useful_chunks": chunks,
        "distinct_command_groups": len(groups),
        "active_banks_per_group_histogram": dict(sorted(occupancy.items())),
        "mean_active_banks_per_group": chunks / len(groups),
        "max_groups_per_channel_rank": max(groups_per_rank.values()),
        "classification": "Structural co-issuance proxy, not PIM timing"
    }

compact = audit("compact", 14336)
padded = audit("padded", 16384)

result = {
    "geometry": "4 channels x 2 ranks x 16 banks",
    "matrix": "4096x14336 FP16",
    "mapid": mapid,
    "compact": compact,
    "padded": padded,
    "total_group_reduction_factor":
        compact["distinct_command_groups"]
        / padded["distinct_command_groups"],
    "worst_channel_rank_group_reduction_factor":
        compact["max_groups_per_channel_rank"]
        / padded["max_groups_per_channel_rank"],
    "limitations": [
        "Assumes a common DRAM row and vector segment per command",
        "Does not execute PIM instructions",
        "Does not model latency, masking, synchronization or reductions",
        "Does not establish end-to-end performance"
    ]
}

out = Path(
    "personA/results/llama3_validation/lockstep_grouping"
)
out.mkdir(parents=True, exist_ok=True)

(out / "summary.json").write_text(
    json.dumps(result, indent=2) + "\n"
)

print(json.dumps(result, indent=2))
print("Saved:", out / "summary.json")
