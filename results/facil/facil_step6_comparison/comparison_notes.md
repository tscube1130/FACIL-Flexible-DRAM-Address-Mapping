# Step 6: FACIL comparison

Baseline re-layout: 447.283520 ms across 32 blocks.
FACIL mapping sensitivity: 308.964280 ms across 32 blocks.

Original paper: Seo et al., HPCA 2025.
https://99dhl.github.io/assets/pdf/hpca25_facil.pdf

Paper Fig. 13: Jetson geometric-mean TTFT speedup = 2.89x.
Paper Table III: Worst-case measured Jetson GEMM slowdown
on PIM layout = 2.1%.
Paper Fig. 15: 2.37x and 2.63x TTFT speedups on real datasets.

Differences and limitations:
- Our results are analytical reduced-scope TTFT proxies.
- Our GEMM values use ideal peak roofline, not measured GPU kernels.
- Our DRAMsim3 uses LPDDR4 protocol with LPDDR5-style timing.
- Our baseline uses serialized DRAMsim3 re-layout estimates.
- The mapping sensitivity extrapolates sequential DRAM reads to
  GEMM and is NOT measured GEMM slowdown.
- The published 2.1% GEMM slowdown cannot be compared directly
  with our raw sequential-read slowdown.
- Attention, normalization, output head, runtime overhead omitted.
- No PIM GEMV or TTLT included yet.
- Different methodology prevents exact numerical reproduction.
