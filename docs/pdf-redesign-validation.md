# Final PDF redesign - integration record

Date: 2026-09-11
The subsequent three-clips-per-page revision replaces the clip layout described here.
See `pdf-density-validation.md` for the current no-appendix implementation and app delivery.
The checksum report remains as validated below.
Delivery status: **PASS**. Final renderer fixes, independent Re-QA, synthetic workflow
integration, local app payload installation, and bundled-runtime PDF generation passed.

## Result and source of truth

The two final application PDF outputs share a white-paper, graphite/teal visual system
and embedded Korean typefaces. Checksum PDFs use persisted Job/JobFile/JobFileReplica
records. Frame-review PDFs use the same BatchReport/ReportItem/CapturePoint input as
the existing CSV/JSON export path. No capture, probe, checksum or source-media algorithms
are replaced by presentation-derived assumptions.

Checksum pages contain meaningful overall counts, an exception index, full source and
replica hashes and paths, recorded statuses, missing configured destinations and errors.
Clip pages put preview images near their identity, include actual frame/timecode captions,
complete metadata, requested-versus-actual capture evidence, duplicate/timecode provenance
and scoped messages. Complete original metadata follows the clip reviews in an appendix.

The PDF filenames, public renderer APIs, report registration and application report URLs
remain compatible. Both old low-level content layouts were replaced by measured flowable
paragraphs/tables, wrapping, repeated headers and page continuations.

## Final checks

- DataManager: 65 tests pass; changed production modules pass Ruff and mypy.
- DataHelper: 175 tests pass (42 renderer tests); changed files pass Ruff/mypy.
- Orchestrator: 198 pass, 1 skip. The skip is the explicit external live-camera fixture
  requiring DIT_LIVE_MEDIA_PATHS; deterministic MP4/MOV workflows run and pass.
- Targeted final workflow/worker tests: 12 pass, 1 same environment-gated skip.
- Distinct full-suite total: **438 passed, 1 optional external-fixture skip**. Repeated
  targeted checks are not counted again in this total.
- Deterministic workflow creates four MP4/MOV files, verifies two copies, then generates
  both PDFs plus CSV/JSON and the completion artifacts. Stored PDF text contains all four
  clip names, embedded fonts and actual capture/timecode evidence.
- After the final renderer fix, the complete deterministic workflow passed again under
  `.pipeline/pdf-redesign-qa/final-confirmed-workflow/`.
- Both distributions build offline as wheels and include both Korean font faces and OFL.
  A checksum wheel installed outside the checkout generated a Korean PDF using the app's
  ReportLab 5.0.1 runtime. Source checkout validation uses ReportLab 4.5.x.
- Both child repositories pass `git diff --check`.

## Independent PDF gate

Initial DataHelper QA found complete data fidelity and two layout defects: stale running
section labels on section-opening pages and isolated error-detail labels at page boundaries.
Both were corrected, then a fresh independent Re-QA session returned **PASS**.

The final audit compares saved source fixtures against eight PDFs comprising **260 pages**:
60 clip instances, 144 capture/zero-capture rows, and 934 raw metadata leaves all match.
All 260 running headers and 322 message-label boundaries pass; there are no detected
out-of-bounds text elements or empty body pages. Eighteen affected full pages received a
fresh visual review after the fix. Ten pertinent regression tests were independently rerun.
All 14 frozen source/artifact hashes match before and after inspection.

Checksum QA also covers configured-but-missing replicas, mismatched hashes, warning/error
states, empty jobs, long Korean paths and complete hash/error text. Its 24-page pressure
fixture retains all 40 records and its long-value final sentinel.

## Local app delivery

The final wheels and renderer/font payload were installed into
`dist/Data Handler DIT.app`, preserving the existing native shell and unrelated app work.
All 13 deployed payload hashes match the accepted source files. Both source payload and
installed Python distributions contain the embedded Korean regular/bold fonts and license.

The app's bundled Python runtime generated three synthetic smoke PDFs through the bundled
source modules: checksum (2 pages), contact-sheet frame review (4 pages), and detail frame
review (5 pages). Extracted text verifies Korean names, complete SHA256 evidence, clip ID,
Start/End timecodes and the final raw metadata sentinel. Runtime module locations are
recorded in `app-smoke-module-paths.json`; results are in `app-smoke-results.json`.

The app was re-signed ad hoc and passed `codesign --verify --deep --strict` after runtime
verification. This is local distribution signing, not Apple notarization.
`dist/Data Handler DIT.dmg` was rebuilt from that app; `hdiutil verify` confirms its checksum
is valid. No native-shell rebuild was required for these Python renderer changes.

Accepted renderer SHA256 values:

- Checksum: `d5632168ded459b31579f74679e8eced52f563e742aa3555f969fad3764d7442`.
- Frame review: `5aa5bab5d1d33c313430d78f2f6d8a6eb60f77d966787d2c3d2dff35bbda73f3`.

## Artifact and workflow records

- User preview PDFs: `output/pdf/DEBUG-DATA-checksum-redesign.pdf` and
  `output/pdf/DEBUG-DATA-frame-review-redesign.pdf` (clearly marked synthetic data).
- Checksum contract and QA: `docs/pdf-redesign-contract.md` and
  `docs/pdf-redesign-checksum-qa.md`.
- DataHelper design, implementation, QA and subsequent Fix/Re-QA records:
  `DataHelper/Docs/reports/{dev,qa}/2026-09-11-pdf-redesign-*.md`.
- Full DataHelper pressure fixtures, sources, text, fonts, rasterized pages and independent
  evidence: `DataHelper/artifacts/qa/pdf-redesign-2026-09-11/`.
- Synthetic integration outputs and deployment evidence: `.pipeline/pdf-redesign-qa/`.

## Verification scope

The accepted source of truth is persisted verification/copy records and supplied clip,
capture, summary and metadata models. These checks establish faithful and readable PDF
presentation and deterministic workflow compatibility. No production transfer was started,
and no real-camera dataset was supplied for the optional external fixture. The PDF redesign
does not add full-stream frame validation or change the underlying media-validation scope.
