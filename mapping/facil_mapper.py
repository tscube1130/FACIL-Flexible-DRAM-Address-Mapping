#!/usr/bin/env python3
"""Reduced-scope AiM-style FACIL DRAM address mapper (Figures 8-10).

Reference *bit-selection model* only.  Physical addresses are row-major byte
addresses supplied by the caller. The selected MapID determines which of the
huge-page-offset bits become row/channel/rank/bank bits. DRAMsim3 itself does
not consume per-page MapIDs unless its decoder is adapted/encoded appropriately.

The mapping uses power-of-two geometry and assumes one 2-KiB PIM chunk is one
physical DRAM row. In Fig. 10 bit order (MSB -> LSB):
    [ROW_HI] [BANK] [RANK] [CHANNEL] [ROW_LO: MapID] [CHUNK_COL] [BYTE_OFFSET]
For AiM chunk=(1,1024) FP16 and 32-B byte offset, CHUNK_COL=6 bits.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import json
from math import log2


def is_pow2(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


def bits(n: int) -> int:
    if not is_pow2(n):
        raise ValueError(f"Expected a positive power of two; got {n}")
    return n.bit_length() - 1


def next_power_two(n: int) -> int:
    if n <= 0:
        raise ValueError("Value must be positive")
    return 1 << (n - 1).bit_length()


@dataclass(frozen=True)
class Geometry:
    page_bytes: int = 2 * 1024 * 1024
    channels: int = 2
    ranks: int = 1
    banks_per_rank: int = 16
    dram_transfer_bytes: int = 32  # Paper Fig. 8/10 physical DRAM transfer size
    trace_transaction_bytes: int = 128  # Our DRAMsim3 proxy requests
    element_bytes: int = 2
    chunk_columns: int = 1024
    dram_row_bytes: int = 2048

    def validate(self) -> None:
        for k, v in asdict(self).items():
            bits(v)
        if self.page_bytes % self.trace_transaction_bytes:
            raise ValueError("Page size must be divisible by transaction size")
        if self.trace_transaction_bytes > self.chunk_bytes:
            raise ValueError("Transaction must fit inside a chunk")
        if self.trace_transaction_bytes % self.dram_transfer_bytes:
            raise ValueError("Proxy transaction size must be a multiple of DRAM transfer size")
        if self.dram_row_bytes != self.chunk_bytes:
            raise ValueError("This reference assumes DRAM row bytes == AiM chunk bytes")
        if self.page_bytes < self.total_pus * self.chunk_bytes:
            raise ValueError("Insufficient huge-page offset bits for PUs and a chunk")

    @property
    def chunk_bytes(self) -> int:
        return self.element_bytes * self.chunk_columns

    @property
    def total_pus(self) -> int:
        return self.channels * self.ranks * self.banks_per_rank


@dataclass(frozen=True)
class DramLocation:
    channel: int
    rank: int
    bank: int
    row: int
    column: int  # in 32-byte DRAM transfers (paper-style transfer granularity)
    byte_offset: int


def choose_mapid(cols: int, geo: Geometry) -> tuple[int, bool, int]:
    """AiM selector, based on paper Figure 9, expressed in bytes.

    Returns (MapID, partition_required, rounded_row_bytes). For a non-power-of-
    two column count, Figure 9 rounds up for the selector. The tensor still
    has ordinary compact row-major logical addresses; in such cases bank-
    confinement properties should be separately checked rather than assumed.
    """
    geo.validate()
    if cols < geo.chunk_columns:
        raise ValueError("Reduced model expects columns >= PIM chunk columns")
    row_bytes = next_power_two(cols) * geo.element_bytes
    bytes_per_pu = geo.page_bytes // geo.total_pus
    usable = min(row_bytes, bytes_per_pu)
    if usable < geo.chunk_bytes or not is_pow2(usable // geo.chunk_bytes):
        raise ValueError("Mapping requires integral power-of-two rows/chunks")
    return bits(usable // geo.chunk_bytes), row_bytes > bytes_per_pu, row_bytes


class AiMMapper:
    def __init__(self, geo: Geometry, mapid: int):
        geo.validate()
        self.geo = geo
        self.mapid = mapid
        self.low_bits = bits(geo.dram_row_bytes)  # within one 2KiB DRAM row
        self.xfer_bits = bits(geo.dram_transfer_bytes)
        self.col_bits = self.low_bits - self.xfer_bits
        self.ch_bits = bits(geo.channels)
        self.rank_bits = bits(geo.ranks)
        self.bank_bits = bits(geo.banks_per_rank)
        self.pu_bits = self.ch_bits + self.rank_bits + self.bank_bits
        self.row_shift = self.low_bits + mapid + self.pu_bits
        if not 0 <= mapid <= bits(geo.page_bytes) - self.low_bits - self.pu_bits:
            raise ValueError(f"Invalid MapID {mapid} for geometry")

    @staticmethod
    def mask(n: int) -> int:
        return (1 << n) - 1

    def decode(self, address: int) -> DramLocation:
        if address < 0:
            raise ValueError("Address must be >= 0")
        g = self.geo
        off = address & self.mask(self.xfer_bits)
        col = (address >> self.xfer_bits) & self.mask(self.col_bits)
        row_lo = (address >> self.low_bits) & self.mask(self.mapid)
        pu = address >> (self.low_bits + self.mapid)
        ch = pu & self.mask(self.ch_bits)
        rank = (pu >> self.ch_bits) & self.mask(self.rank_bits)
        bank = (pu >> (self.ch_bits + self.rank_bits)) & self.mask(self.bank_bits)
        row_hi = address >> self.row_shift
        row = (row_hi << self.mapid) | row_lo
        return DramLocation(ch, rank, bank, row, col, off)

    def encode(self, location: DramLocation) -> int:
        g = self.geo
        if not (0 <= location.channel < g.channels and
                0 <= location.rank < g.ranks and
                0 <= location.bank < g.banks_per_rank and
                0 <= location.column < (g.dram_row_bytes // g.dram_transfer_bytes) and
                0 <= location.byte_offset < g.dram_transfer_bytes and
                location.row >= 0):
            raise ValueError(f"Out-of-range DRAM location: {location}")
        row_lo = location.row & self.mask(self.mapid)
        row_hi = location.row >> self.mapid
        pu = (location.bank << (self.rank_bits + self.ch_bits)) | (location.rank << self.ch_bits) | location.channel
        return ((row_hi << self.row_shift) |
                (pu << (self.low_bits + self.mapid)) |
                (row_lo << self.low_bits) |
                (location.column << self.xfer_bits) |
                location.byte_offset)

    def at_element(self, row: int, col: int, ncols: int) -> DramLocation:
        if min(row, col) < 0 or col >= ncols:
            raise ValueError("Element index outside logical row-major tensor")
        # *Compact* row major; non-power-of-2 row length can cross PUs.
        addr = (row * ncols + col) * self.geo.element_bytes
        return self.decode(addr)


class PerHugePageMapper:
    """Allow different huge pages to have different MapIDs (FACIL's key idea).

    The huge page number occupies the high DRAM row bits, independent of
    selected MapID. Missing page IDs are deliberately treated as an error.
    """
    def __init__(self, geo: Geometry, mapid_by_page: dict[int, int]):
        geo.validate()
        if not mapid_by_page or any(n < 0 for n in mapid_by_page):
            raise ValueError("Supply nonnegative huge-page indexes and MapIDs")
        self.geo = geo
        self.mapid_by_page = dict(mapid_by_page)
        self.mappers = {page: AiMMapper(geo, mid) for page, mid in mapid_by_page.items()}
        self.rows_per_page = geo.page_bytes // (geo.dram_row_bytes * geo.total_pus)

    def decode(self, address: int) -> DramLocation:
        page = address // self.geo.page_bytes
        if page not in self.mappers:
            raise KeyError(f"Unconfigured huge page {page}")
        loc = self.mappers[page].decode(address)
        if loc.row // self.rows_per_page != page:
            raise AssertionError("Page number changed during mapping")
        return loc

    def encode(self, loc: DramLocation) -> int:
        page = loc.row // self.rows_per_page
        if page not in self.mappers:
            raise KeyError(f"Unconfigured huge page {page}")
        result = self.mappers[page].encode(loc)
        if result // self.geo.page_bytes != page:
            raise AssertionError("Page identity lost during inverse mapping")
        return result


def main():
    p = argparse.ArgumentParser(description="Reference FACIL AiM MapID/DRAM mapper")
    p.add_argument("--rows", type=int, default=2048)
    p.add_argument("--cols", type=int, default=8192)
    p.add_argument("--channels", type=int, default=2)
    p.add_argument("--ranks", type=int, default=1)
    p.add_argument("--banks", type=int, default=16)
    p.add_argument("--sample", type=int, default=8, help="Number of example addresses")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    if a.rows <= 0 or a.cols <= 0 or a.sample <= 0:
        p.error("Rows, cols and sample must be positive")
    geo = Geometry(channels=a.channels, ranks=a.ranks, banks_per_rank=a.banks)
    mid, needs_part, padded_bytes = choose_mapid(a.cols, geo)
    mapper = AiMMapper(geo, mid)
    samples = []
    for i in range(a.sample):
        linear_element = (i * geo.chunk_columns) % (a.rows * a.cols)
        row, col = divmod(linear_element, a.cols)
        addr = linear_element * geo.element_bytes
        loc = mapper.decode(addr)
        assert mapper.encode(loc) == addr
        samples.append({"tensor_element": [row, col], "address": hex(addr), **asdict(loc)})
    out = {"shape": [a.rows, a.cols], "mapid": mid,
           "partition_required": needs_part, "rounded_row_bytes": padded_bytes,
           "geometry": asdict(geo), "samples": samples,
           "limitations": "Standalone AiM bit permutation, not a DRAMsim3-installed MapID controller"}
    if a.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"Matrix {a.rows}x{a.cols} FP16 | MapID={mid} | partition={needs_part} | rounded row={padded_bytes}B")
        print("Tensor (row,col)   Phys byte addr  Channel Rank Bank DRAM-row DRAM-col")
        for s in samples:
            print(f"{str(tuple(s['tensor_element'])):<18} {s['address']:<15} {s['channel']:>3} {s['rank']:>4} "
                  f"{s['bank']:>4} {s['row']:>8} {s['column']:>8}")


if __name__ == "__main__":
    main()
