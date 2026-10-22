#!/usr/bin/env python3
"""Paper figure anchors and invertibility/property tests."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'personA'))
from facil_mapper import AiMMapper, PerHugePageMapper, Geometry, choose_mapid


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.geo = Geometry()

    def test_paper_figure10_mapids(self):
        self.assertEqual(choose_mapid(8192, self.geo), (3, False, 16 * 1024))
        self.assertEqual(choose_mapid(65536, self.geo), (5, True, 128 * 1024))

    def test_power_of_two_llama_shapes(self):
        self.assertEqual(choose_mapid(4096, self.geo)[0], 2)
        self.assertEqual(choose_mapid(14336, self.geo)[0], 4)

    def test_invertibility_entire_huge_page(self):
        for mid in (0, 2, 3, 4, 5):
            m = AiMMapper(self.geo, mid)
            seen = set()
            for addr in range(0, self.geo.page_bytes, self.geo.trace_transaction_bytes):
                decoded = m.decode(addr)
                self.assertEqual(m.encode(decoded), addr)
                self.assertNotIn(decoded, seen)
                seen.add(decoded)
            self.assertEqual(len(seen), self.geo.page_bytes // self.geo.trace_transaction_bytes)

    def test_chunk_contiguity_within_bank_and_dram_row(self):
        m = AiMMapper(self.geo, 3)
        for start in (0, 2048, 16384, 65536, 130*2048):
            tuples = set()
            for addr in range(start, start + self.geo.chunk_bytes, self.geo.trace_transaction_bytes):
                loc = m.decode(addr)
                tuples.add((loc.channel, loc.rank, loc.bank, loc.row))
            self.assertEqual(len(tuples), 1)

    def test_small_matrix_row_stays_on_one_pu(self):
        m = AiMMapper(self.geo, 3)
        cols = 8192
        for row in (0, 1, 2, 3, 10):
            pus = {(m.at_element(row, c, cols).channel,
                    m.at_element(row, c, cols).rank,
                    m.at_element(row, c, cols).bank)
                   for c in range(0, cols, 64)}
            self.assertEqual(len(pus), 1)
        self.assertNotEqual(m.at_element(0, 0, cols).channel,
                            m.at_element(1, 0, cols).channel)

    def test_large_matrix_row_partition(self):
        m = AiMMapper(self.geo, 5)
        # A 128KiB row, with 64KiB/page/PU, must spread across 2 PUs.
        pus = {(m.at_element(0, c, 65536).channel,
                m.at_element(0, c, 65536).bank)
               for c in range(0, 65536, 64)}
        self.assertEqual(len(pus), 2)

    def test_fig8_chunk_offset_and_col_bits(self):
        m = AiMMapper(self.geo, 3)
        self.assertEqual(m.xfer_bits, 5) # 32B transfer
        self.assertEqual(m.col_bits, 6)  # 2KiB / 32B = 64 columns
        self.assertEqual(m.decode(32).column, 1)
        self.assertEqual(m.decode(128).column, 4) # one 128B proxy trace step

    def test_per_page_mapid_no_alias_across_pages(self):
        g = self.geo
        m = PerHugePageMapper(g, {0: 3, 1: 5})
        seen = set()
        for p in (0, 1):
            for offset in range(0, g.page_bytes, g.trace_transaction_bytes):
                addr = p * g.page_bytes + offset
                loc = m.decode(addr)
                self.assertEqual(m.encode(loc), addr)
                self.assertNotIn(loc, seen)
                seen.add(loc)
        self.assertEqual(len(seen), 2 * g.page_bytes // g.trace_transaction_bytes)

    def test_four_channel_two_rank_changes_mapid(self):
        g = Geometry(channels=4, ranks=2, banks_per_rank=16)
        self.assertEqual(choose_mapid(65536, g)[0], 3)

    def test_nonpow2_row_mapid_not_promised_bank_confinement(self):
        mid = choose_mapid(14336, self.geo)[0]
        self.assertEqual(mid, 4)
        # The selector rounds 14336 -> 16384; compact row-major may not
        # meet ideal PIM alignment. Treat separately in integration.


if __name__ == '__main__':
    unittest.main()
