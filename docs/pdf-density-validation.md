# Compact clip-report revision - 2026-09-11

Status: **PASS**. Implementation, independent QA, workflow integration, bundled-app PDF
generation, and local app signature verification completed.

The user requested at least three clips per page, then explicitly removed appendices.
This supersedes the earlier full-evidence PDF layout for clip reports. Checksum reports
are outside this revision. The compact PDF is a deliberate projection of supplied
ReportItem/ClipInfo/CapturePoint and BatchSummary records in their original order.
The media validators and existing CSV/JSON exports are unchanged.

## Accepted scope

- Three complete clip summaries per page, including the first page.
- No separate cover, appendix, raw metadata dump, or repeated detail/index pages.
- Core normalized media metadata, clip identity, sampled frames, actual timecodes,
  capture states and visible warning/error information remain in the main body.
- Exceptional long values use visible abbreviation markers. This PDF does not promise
  to include all raw metadata or error-detail payloads. The existing companion exports
  retain their own schemas; no claim is made that they contain every omitted field.

## Reproducible comparison

`.pipeline/pdf-density-qa/compare_density.py` renders the same nine synthetic clips,
with two to five capture points each, Korean names, metadata and a warning case.
The source models are retained as `density-source-fixtures.json` in the same directory.

| Layout | Previous PDF | Revised PDF |
| --- | ---: | ---: |
| A4 portrait contact sheet | 20 pages | 3 pages |
| Landscape detail | 34 pages | 3 pages |

The previous renderer and sample PDF are preserved under `.pipeline/pdf-density-qa/`.
Fresh Plan/QA/Implement reports live in `DataHelper/Docs/reports/{dev,qa}/` with the
`2026-09-11-pdf-density-` prefix. Final inspection and app delivery evidence is recorded below.

## Completed checks

- Both nine-clip PDFs have exactly three pages and three complete clip rows per page,
  starting on page one. Ten ordinary and ten pressure clips each produce four pages.
- Independent parent extraction checks verify ordered clip IDs/names, all actual capture
  timecodes, codec/fps, minimum 8pt text, no appendix, and zero page-bounds violations.
- DataHelper renderer tests: 31 passed. Full DataHelper suite: 164 passed. Whole-source/test
  Ruff and all 43 source-file mypy checks passed. Child diff whitespace checks passed.
- An orchestration E2E test created four MP4/MOV clips, verified two replicas, and generated
  checksum/PDF/CSV/JSON and completion artifacts. Both clip PDFs are two pages, with no
  appendix. This test passed at the accepted renderer source hash below.
- Source hashes confirm models, summary builder, settings, CSV/JSON serialization and
  checksum report code were not changed by this revision.
- The final wheel builds offline and contains the matching renderer, both embedded Korean
  font faces and their license.

Pressure coverage includes 2-5 capture points, Korean titles/names/prose, normal and very
long identities, camera metadata, rational fps, requested/actual mismatches, missing/corrupt
and portrait/panorama/EXIF images, decode failure, duplicate capture, zero-capture records,
useful warning/error excerpts, escaped literal markup, path modes and disabled companions.

The parent visually reviewed all six initial comparison pages, both failure/long-text
pressure pages, and both final first pages. The implementation lane reviewed all six final
comparison pages and all eight final pressure pages at 150dpi.

Independent QA returned **PASS** in
`DataHelper/Docs/reports/qa/2026-09-11-pdf-density-qa.md`: eight PDFs, 28 pages, and 244
capture rows independently matched the frozen JSON models. All six main pages and pressure
pages 2/3/4 in both layouts received a fresh 150dpi visual inspection. All 31 renderer
tests were independently rerun. The exact source/tests/fixtures/PDF hashes were preserved.

Accepted source SHA256:
`8e2854f0740d3214ffde478a590cdf957af09d47521dff7ac404637b4fce0f9f`.

Recorded evidence: `.pipeline/pdf-density-qa/after-independent-audit.json`,
`workflow-results.json`, `unchanged-contract-files.json`, `wheel-verification.json`, and
`DataHelper/artifacts/qa/pdf-density-2026-09-11/artifact-inventory.json`.

Verification uses synthetic report models and generated MP4/MOV files. No production
transfer or new external camera-footage run was performed for this layout revision.

## App delivery and sample

The accepted renderer was installed into the existing `dist/Data Handler DIT.app` source
payload and its bundled Python distribution. Using the app's Python runtime and source
modules, both layouts generated nine clips in three pages. Their complete extracted text
matches the QA-accepted PDFs after excluding generation timestamps. All actual timecodes,
three ordered clips per page, minimum 8pt and no appendix/bounds overflow passed again.
The frozen source fixture remained unchanged. Evidence: `installed-payload.json`,
`app-module-path.txt`, `app-independent-audit.json`, and `app-content-equivalence.json`.

The app was re-signed ad hoc and passed `codesign --verify --deep --strict`. This is local
signing, not Apple notarization. The native shell and checksum renderer were preserved.
`dist/Data Handler DIT.dmg` was rebuilt from that app and passed `hdiutil verify`.

Final user sample: `output/pdf/DEBUG-DATA-frame-review-compact.pdf` (9 synthetic clips,
3 pages). The sample is a byte-for-byte copy of the visually accepted contact PDF.
