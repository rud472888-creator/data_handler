# Independent integration validation

Tested locally on 2026-10-14 using FFmpeg 7.1.5, NumPy 2.3.5 and Pillow 12.3.0. Actual CLI subprocesses were exercised, not only imported functions. Independent synthetic fixtures were generated losslessly with FFV1.

## Passed checks

- **Persistent candidates:** 20 RGB16 frames yielded exactly one bright coordinate (x=7,y=8) and one dark coordinate (x=21,y=20), each lasting 20 frames / 2 seconds. A one-frame bright transient at (15,14) was excluded from qualifying intervals. Numeric persistence maps retained its 1/20 occupancy.
- **16-bit endpoints:** Distinct source values 0, 1, 256, 4096, 60160, 65279, 65534 and 65535 were retained. Exact endpoint counts included only 0 and 65535, not adjacent values.
- **VFR:** All five frames retained their actual PTS: 0, 0.12, 0.44, 1.12 and 1.36 seconds, with no timestamp fallback.
- **Incomplete input:** Truncation produced a nonzero exit and `partial_failure`, with decoding errors recorded, rather than a successful result.
- **Decoder startup failure:** A controlled failing decoder returned nonzero `failed` for a 2,000-frame source without hanging on timestamp extraction.
- **Evidence integrity:** Crop dimensions, source coordinates, and expected black/white candidate preview pixels matched the report. Clipping pixel totals, per-frame bounding boxes and summary totals were inspected.
- **Nonmutation:** Source hashes were unchanged. Reusing an existing output directory was refused, and every existing output-file hash remained unchanged.
- **Zero threshold:** The initially discovered zero-pixel-delta degeneracy was fixed; the final CLI rejects `--pixel-delta 0`.
- **Bounded-duration-memory smoke test:** 32×32 clips of 20 and 2,000 frames completed at approximately 36 MiB and 35 MiB maximum child-process RSS. This supports frame-count boundedness at small resolution, not a 4K performance certification. Code uses fixed per-pixel state, streaming CSV, two-frame lookahead and row-tiled neighborhood analysis.

## Important interpretation limit

The tool measures decoded RGB threshold occupancy, not original YUV or sensor clipping. Independently reproduced: tagged limited-range 10-bit neutral YUV code 940 decoded to RGB 65283/65535 on this FFmpeg build, and code 1023 to 65506/65535. Consequently the exact default highlight threshold 1.0 found no highlight endpoints in that fixture. A relaxed threshold such as 0.99 measures near-white occupancy and is not proof of source clipping. The final documentation/report warn about this conversion limitation. The final CLI provides `--threshold-preset endpoints|near-endpoints`; the potentially misleading `legal` preset was removed. Neither preset is a YUV legal-range-compliance check. The near-endpoints smoke test verified effective thresholds 0.01/0.99, 384 shadow pixels and 512 highlight pixels per frame/channel in the limited-YUV fixture, while exact endpoint highlights were zero. These are different decoded-domain occupancy measures, not proof of source clipping.

Persistent scene details can be indistinguishable from defective-pixel candidates. No real user video, ground-truth labeled sensor corpus, HDR calibration, 4K benchmark, or production integration was tested. All findings concern synthetic screening behavior. No unresolved defect was found within the tested scenarios; this is not exhaustive validation.

## Review fixes — 2026-10-16, cloud Linux

Reviewed the findings against PR head `6651dff310d437f1e2d9d5796605d43eef3e68c5`.
Python 3.12, NumPy 2.3.5, Pillow 12.3.0, FFmpeg 7.1.5.

- **Reproduced evidence starvation:** an 8-frame synthetic input with early bright candidates and later dark/shadow/highlight candidates exhausted all four crops on bright in the original code. The revised code retained all four kinds within the same total limit. Kind reservations, including zero/small limits and module selection, are tested. Unused reservations are deliberately not reassigned.
- **Exact median semantics:** all 40,320 permutations of eight distinct inputs and all 256 binary endpoint/tie patterns pass the sorting-network test. Random uint16 frames crossing row-tile boundaries retain exact float32 residual arrays and do not mutate inputs. Full 1080p/4K random-array comparisons also passed.
- **Kernel benchmark:** five-repeat medians on this cloud host: 1920x1080, 0.757754 s to 0.224985 s (3.37x); 3840x2160, 3.101900 s to 0.969935 s (3.20x). `benchmark_residual.py` provides a reproducible seeded comparison. Timings are host/load specific, not real-time guarantees.
- **End-to-end benchmark:** one 60-frame 1080p H.264 synthetic testsrc2 clip, all modules, max-crops=0: original 35.733 s, revised 22.199 s (1.61x). Both processed all 60 frames successfully. All three CSV files, all six numeric NPY arrays, pixel/clipping summaries, timestamp fallback counts and errors matched exactly. This single run includes decode/probe, analysis and output writing; it is not a statistically stable throughput estimate or a long-footage certification.
- **13 automated QA tests passed:** original four plus network orderings, residual parity/nonmutation, quota boundaries, late evidence, module branches/clipping interval bounds, real VFR timestamps, truncated-input failure, mid-stream resolution-change failure, and tagged limited-range 10-bit YUV near-white occupancy. Tested from repository root with pytest and unittest discovery. The YUV test allows FFmpeg-dependent exact-endpoint rounding; it does not claim source-code clipping detection.
- **Compile and whitespace checks:** Python compileall and git diff --check passed.
- **Repository aggregate remains blocked:** orchestrator tests on the revised code returned 289 passed, 4 failed, 1 skipped. Failures are the existing restricted-PATH ffmpeg assumption and three missing macOS Blackmagic RAW runtime preflight failures. The exact base `9648362fb89efbe5852929c7861a5e252e97bebb`, with its pinned submodules, reproduced the same 289 passed / 4 failed / 1 skipped and the same four failing tests. These are not counted as passes. No tests were altered or skipped to conceal failures.
- DataManager/DataHelper standalone suites and macOS packaging were not run; their source and pinned submodule commits are unchanged.

The .25 threshold and channel-OR interpretation remain uncalibrated, documented behavior. No real defective-sensor corpus was available, so no accuracy/recall claim or arbitrary threshold change was made. Orchestrator/event/UI integration and optional frame sampling are outside this standalone, all-frame PR. `-v error` already suppresses ordinary FFmpeg warnings; stderr errors still cause conservative failure. The deprecated frame-sync flag was replaced with `-fps_mode passthrough` (FFmpeg 5.1+). The full main-function refactor is deferred to avoid unrelated churn.
