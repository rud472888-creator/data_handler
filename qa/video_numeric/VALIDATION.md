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
