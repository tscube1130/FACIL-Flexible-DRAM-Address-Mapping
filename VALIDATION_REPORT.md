# Validation report

## Environment and commands

Fresh Ubuntu/WSL build with the versions recorded in `docs/provenance/VALIDATED_ENVIRONMENT.json`.

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j 2
python -B scripts/validate_release.py --regenerate-traces
```

The Python command used an existing environment containing the documented dependencies. It completed successfully. [Machine-readable check results](docs/provenance/RELEASE_VALIDATION.json) record the exact check names, outcomes and elapsed seconds. Full local stdout/stderr is retained in ignored `.validation/validation.log`.

## Passed checks

- Fresh native simulator build from the modified source; original C++ test target: 3 cases, 26 assertions.
- Python mapper and evidence suite: 15 tests. Active Python modules parsed successfully.
- Native verifier freshly compiled against the fresh library: 411 independent tuples, MapID 2/3 exhaustive page uniqueness, conventional fallback and channel-count fixture.
- Fresh mixed-page routing smoke: reads `(72,8,8,8)`, no WRITE requests. One-WRITE EOF smoke: one write callback and zero read callbacks, without reissuing the final request.
- Corrected geometry: 4 channels, 2 ranks/channel, 16 banks/rank, 2048 aggregate row bytes, 128-byte requests, 0.3125-ns tick. Four original manifest/config/mapper hashes and per-stage transaction counts match.
- Baseline byte-layout conversion restores 262,144 identifiable 32-byte fragments. Read/write stage arithmetic and whole-model 447.28352-ms sum match.
- Analytical SoC, final TTFT, PIM, feasibility, batch crossovers and dynamic switching reproduce the retained numerical evidence in an isolated results root. The original source-hash field and relocated placement CSV path fields are treated as provenance rather than numerical differences.
- Crossovers 17/5, conceptual one-/two-copy accounting, zero-overhead reference equality, offline/static/online invariants and all six h_max values match actual original CSVs.
- Experiment 5 saved samples: exact address-set/offered-time equality, source sampling equivalence, 32,768 transactions/stage, native read/issued-write counters and B/ns calculations match. No full diagnostic rerun was substituted for those files.
- Eight baseline read/write streams and eight matched-read streams regenerated with exact original checksums for all four matrix groups. No full-size traffic simulations rerun.
- Experiments run from a non-repository working directory using isolated output roots, demonstrating the repaired source/config/import paths.

The run recorded **30 successful check entries** and compared **27 original numerical files**.

## Findings and fixes

The initial added EOF smoke assertion required a physical write command within 3000 cycles. It failed because the stock controller can acknowledge one write into its buffer while issuing no DRAM WRITE command during that window. The corrected check verifies one callback, zero reads, and no duplicate issued command; the issued count is recorded. Simulator behavior was not changed, and acknowledgement is not presented as drain/completion.

The refactor exposed one remaining relative path in the retained PIM plotting producer. It was changed to the shared results root, then the entire analytical pipeline passed from a scratch working directory. Placement summary output-path fields and the SoC script SHA differ under relocation, as expected; their scientific values were independently compared.

The bundled old Catch header requires `CATCH_CONFIG_NO_POSIX_SIGNALS` on this compiler/libc combination. The definition is limited to the C++ test target; simulator calculations and native source are unchanged.

Upstream build warnings remain: old CMake compatibility, legacy fmt `char8_t`, an INIReader strncpy warning and a copied range-loop variable. They did not fail the fresh build/tests and were not changed as part of a structural release.

## Not independently verified

- Full-size baseline/native traffic simulations and the complete multi-run Experiment 5 were not rerun. Their original statistics, traffic accounting and checksums were checked.
- Exact historical 996-address/2,162,688-block claims and the original standalone numerical GEMV driver are not fully reproducible from identified active sources; see `docs/REPORT_RECONCILIATION.md`.
- The original Q/O and K/V timing-search drivers were not identified. Their exact streams, saved completion brackets and native statistics remain; those gaps are not filled with fabricated measurements.
- Actual GPU GEMM, PIM compute, OS/PTE modifications, physical switching overhead, native LPDDR5, full LLM inference and end-to-end TTFT/TTLT are outside this implementation.
- Optional upstream thermal support and two Python 2 utilities were not exercised. They are not active FACIL dependencies.
- Supplied manuscript author/team fields remain placeholders. The original report was preserved rather than silently altered.

Publication/CI status is reported separately after push; local validation alone is not a claim that a remote workflow ran.

## Publication review

Staged scientific evidence/config/mapper blobs were checked against working-file bytes; 286 checksum-bearing paths were verified before commit. Original results, traces and configurations retain their original CRLF/EOF formatting where present; Git attributes distinguish immutable evidence formatting from new source-code whitespace. The new rename table and upstream documentation whitespace were normalized. No scientific values were reformatted.

No credential pattern or obsolete coursework directory reference was found in staged active code/documentation. The old directory strings inside original result metadata and the historical project log are intentionally preserved as provenance. The release tip contains about 18 MB of files; the largest is the supplied report PDF (about 1.67 MB). Large prior trace files remain in existing Git history because history was not rewritten.
