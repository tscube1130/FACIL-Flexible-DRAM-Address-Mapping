# Methodology

## Workload and geometry

Four FP16 matrix classes represent seven projections per Llama3-8B decoder block, repeated across 32 blocks:

| Group | Output rows M | Input columns K | Copies/block | Requests/stage | MapID (proxy) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Q/O | 4096 | 4096 | 2 | 262144 | 2 |
| K/V | 1024 | 4096 | 2 | 65536 | 2 |
| FFN gate/up | 14336 | 4096 | 2 | 917504 | 2 |
| FFN down | 4096 | 14336 | 1 | 917504 | 3 |

The enumerated weights total 13,958,643,712 bytes, or 13 GiB. A serialized read-plus-write of those weights accounts for twice that traffic. This is projection-weight accounting, not total model/device memory demand.

The current config is [LPDDR5_6400_APPROX_v1.ini](../configs/LPDDR5_6400_APPROX_v1.ini): LPDDR4 protocol, rows=262144, columns=256/device, bus_width=64/channel, BL=16, four channels and two ranks/channel, four bank groups of four banks. Aggregate bank-row bytes = columns × bus_width / 8 = 2048. A request carries bus_width × BL / 8 = 128 bytes. The 0.3125-ns equivalent simulator tick yields a theoretical aggregate reference of 204.8 GB/s. These choices do not validate a physical LPDDR5 geometry or its CK/WCK behavior.

## Mapping

With n FP16 columns, b=2 bytes/element, K_chunk=1024 elements, H=2 MiB, and U processing banks, the selector uses rounded row bytes `2^ceil(log2(n)) * b`, per-PU bytes `H/U`, and `MapID = log2(min(rounded_row_bytes, H/U)/(K_chunk*b))`. Partitioning is required when rounded row bytes exceed H/U.

The reference bit order is `[row high][bank][rank][channel][MapID row-low bits][chunk column][32-byte offset]`. Each 2-KiB chunk contains 64 reference transfers. A DRAMsim3 request groups four such transfers and is checked for shared channel/rank/bank/row and contiguous columns.

A static `FACIL_PAGE_MAP_FILE` holds decimal `huge_page_number MapID` pairs. Native decoding and channel routing use the same interpretation. Unregistered pages fall back to conventional decoding. This fixture models per-page selection without implementing PTE extensions or OS allocation changes.

The separate paper-example organization uses two channels and one rank, and has different MapID anchors. The test suite preserves those examples alongside the evaluated proxy geometry.

## DRAM traffic and timing

Baseline source addresses encode validated PIM placement into the conventional decoder. Destination addresses start at 0x10000000. Source READ and destination WRITE are separate, serialized offered streams. Requests are offered at consecutive simulator cycles; backpressure can defer acceptance. Completion horizons are searched with finite resolution.

The saved baseline sum is `32 * sum(copies_i * (read_us_i + write_us_i)) / 1000 = 447.28352 ms`. Stage statistics count the native callbacks used by the original measurement tool. DRAMsim3 write acknowledgements may precede issue/drain, so the label does not establish durable write completion. Full CPU/GPU byte conversion and overlap are absent.

FACIL matched reads compare equal logical work and offered cycles, using conventional destination reads and logical source reads with native mapping. Their differences are sequential-read proxies, not GPU GEMM measurements. The synthetic trace-only regeneration helper reproduces original stream bytes without modeling any new timing.

## SoC GEMM and prefill component models

For each projection and P token vectors:

`F_i(P) = 2 M_i K_i P`

`V_i(P) = 2 M_i K_i + 2 P (M_i + K_i)`

`G_i(P) = 1000 * max(F_i / 42.5e12, V_i / 204.8e9)` ms

`G(P) = sum_i 32 copies_i G_i(P)`

The baseline component is G(P)+447.28352 ms. Ideal FACIL is G(P). The mapping sensitivity is G(P)+D, where `D = 32 sum_i copies_i (mapped_read_i - conventional_read_i) = 308.96428 ms`. The model already includes weight traffic, so only the increment is extrapolated. Transferring even that increment to actual GEMM latency is unvalidated.

## PIM GEMV sensitivity

Validated maximum chunks per bank are W=(128,32,448,448). The model uses `T_i = W_i * tau`, with assumed tau=75/100/200 ns, yielding 3.9936/5.3248/10.6496 ms for all linear projections per token. It omits input staging, command timing, reductions and contention. Optional short-prefill selection compares this repeated GEMV estimate with each SoC projection; it is distinct from the final decode-step policy.

## Batch-aware decode

`T_SoC(B,eta) = sum_i 32 copies_i G_i(B) / eta`

`T_PIM(B,T1,rho) = T1 * [1 + (B-1)*(1-rho)]`

T1 is either the uncalibrated 5.3248-ms scenario or an illustrative 20-ms scenario. The final policy chooses one engine for all linear projections of a decode step. Feasibility retains independent per-projection screening. Eta divides both compute- and bandwidth-limited SoC estimates; it is not measured efficiency. Positive rho is a hypothetical reuse sensitivity.

The offline recurrence tracks the best cumulative cost ending on each engine, adding h for an engine transition. The first engine is free. Online hysteresis changes engine only when that step’s alternative saving exceeds h. The offline break-even limit is `max((best_static - zero_cost_schedule)/number_of_transitions)` over strictly beneficial mixed schedules. It is a threshold for an offline optimum, not measured hardware overhead.

Conceptual two-copy dispatch shares the ideal minimum execution time and doubles the enumerated weight bytes. No duplicate tensors or physical PIM execution are implemented by this policy.

## Access-order diagnostic

The diagnostic selects the first 32,768 unique aligned transactions per stage from a preserved source. Original and sequential variants retain exactly the same address multiset and offered-cycle sequence; only address order changes. The read condition is all read callbacks; the write condition is all WRITE commands issued. Duration uses cycles × 0.3125 ns and bandwidth uses bytes / duration in B/ns (=GB/s). Search resolution is 256 cycles. Native statistics and original samples remain published.
