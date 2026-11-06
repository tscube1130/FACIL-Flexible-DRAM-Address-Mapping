# Repository manifest

## Included

Original Git commit ancestry, native simulator source/build definitions/configurations and MIT/dependency licenses; reference mapping code and validators; corrected baseline generator and measurement driver; native decoder source/fixtures; original 2-KiB baseline and matched-read statistics; analytical SoC/PIM/TTFT models; batch feasibility and Experiments 1–5; original CSV/JSON/plots and essential traffic/manifests; negative padding comparison evidence; one canonical supplied manuscript/source/figure set; cumulative experimental log; reproducibility and validation documentation.

Code lives in `mapping/` and categorized `experiments/`. Evidence lives in grouped `results/`. See [script renames](docs/SCRIPT_RENAMES.csv), [result index](docs/RESULTS_INDEX.md) and [tree](REPOSITORY_TREE.txt).

The [viva evidence map](docs/FACIL_VIVA.md) links all 40 preparation questions to these files. The [K/V two-copy study](results/facil/facil_two_copy_k_v_2k) includes the original result files, native verifier, and runner. Its small mixed-routing input is retained with the raw counters. The two complete scans are regenerated and checked against recorded SHA-256 digests.

## Excluded from the release tip

Build trees, binaries/libraries, Python/editor caches, security sidecars, temporary outputs, duplicate submission directories, source ZIPs, obsolete report/presentation copies, local CLI/credentials, private preparation snapshots, and third-party paper PDFs. The old copy-size presentation variants and incomplete smoke/debug outputs are not final scientific results. Older commits remain in history because history is intentionally preserved.

Large regenerable `.trace` files are omitted. Original per-shape manifests and [trace checksums](docs/provenance/TRACE_CHECKSUMS.json) remain, alongside verified generators. The source streams and four samples essential for Experiment 5, plus small native fixtures and the upstream example trace, are explicitly retained. No retained trace exceeds the normal Git file-size limit.

## Historical evidence

Padding, bounded scheduling, channel-XOR, generic copy sweeps and earlier small-model scripts/results remain in the existing external historical archive beside the untouched original checkout. That archive is not deleted or published wholesale. Negative padding summary/figure and mapping/alignment evidence are included here; the cumulative experimental log remains under `docs/provenance/`.

A few earlier small baseline summaries and PIM workload records are retained because active preserved analytical scripts read them. They are labeled distinct from the canonical final 2-KiB/paper-aligned results.

## Integrity

Original result files retain byte-exact contents, including historical path strings and hashes. Path translation occurs in active code and documentation; original evidence is not rewritten to resemble a new run. The mapper and native C++ scientific source match the latest verified working checkout. CLI defaults/paths and test-framework compiler compatibility are the only non-mathematical behavior adjustments; full details are in [validation](VALIDATION_REPORT.md).

The original working checkout, its external archive, and retained revised submission package remain outside this staging copy and are verified against protection snapshots before publication. The owner removed the obsolete duplicate submission folder during preparation; it was not removed by release tooling.

`.gitattributes` preserves checksum-bearing results, traces, configuration and mapper bytes across checkouts; source code uses LF line endings.
