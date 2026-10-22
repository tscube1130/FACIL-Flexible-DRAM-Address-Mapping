
## 2026-10-21 — Person B: LPDDR5 approximation

Completed:
- DRAMsim3 built successfully in WSL.
- LPDDR5_6400_APPROX.ini generated.
- Random-stream smoke test returned without visible error.
- Chosen LPDDR4 protocol with LPDDR5-style timing approximation.

Changes for next validation:
- AL corrected to zero.
- Modeled capacity set to 64 GiB with two ranks/channel.
- Transaction size established as 128 bytes.
- Sequential test mapping interleaves four channels.

Pending:
- Verify completed read counts.
- Measure per-channel and aggregate bandwidth.
- Establish accurate end-of-workload completion timing.
- Validate timing parameters and document approximations.
