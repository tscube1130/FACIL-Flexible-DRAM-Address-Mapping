from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'personB'))
from ttft_model import compute_gemm_us, evaluate

class TtftTest(unittest.TestCase):
    def test_roofline_floor(self):
        g = compute_gemm_us(512, 1024, 8, 2, 204.8, 42.5, 1.0)
        self.assertGreaterEqual(g['gemm_us_analytical'], g['memory_component_us'])
        self.assertGreaterEqual(g['gemm_us_analytical'], g['compute_component_us'])

    def test_copy_affects_prefill_and_no_decode_term(self):
        r = evaluate(512, 1024, 2, [8], 204.8, 42.5, 1.0, 0.0, 18.48, True)[0]
        self.assertAlmostEqual(r['baseline_us_scenario'] - r['facil_us_scenario'], 18.48)
        self.assertEqual(r['copy_proxy_us_upper_bound'], 18.48)
        self.assertNotIn('gemv', r)

    def test_increasing_prefill_compute(self):
        a = evaluate(512,1024,2,[8,64,512],204.8,42.5,1.0,0,18.48,True)
        self.assertLess(a[0]['gemm_model_us'], a[1]['gemm_model_us'])
        self.assertLess(a[1]['gemm_model_us'], a[2]['gemm_model_us'])
        self.assertGreater(a[0]['speedup_scenario'], a[-1]['speedup_scenario'])

if __name__ == '__main__':
    unittest.main()
