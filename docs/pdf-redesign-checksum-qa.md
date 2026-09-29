# Checksum PDF redesign - implementation and verification

Date: 2026-09-11
Status: checksum implementation checks PASS; combined DataHelper/pipeline gate recorded separately.

## Implementation

`DataManager/app/runtime/reports.py` now passes persisted Job project/expected replica IDs
and ordered JobFile rows into the new `app/runtime/checksum_pdf.py` Platypus renderer.
It retains report paths, registration, generated-PDF checksum, and manifest payloads.
The old handwritten Latin-1 PDF serializer is removed. ReportLab >=4.4 is an explicit
runtime dependency; pypdf is a development dependency. Both static Data Handler Sans
fonts and their SIL OFL/provenance files are included in the built wheel.

The A4 document uses an editorial summary, actual evidence-based counts, a problem index,
then compact complete file records. Ordinary two-destination records fit two per page.
All hashes, IDs, relative paths, bytes, stored statuses, and file/replica errors survive.
Missing configured destinations are explicit. Equal hashes cannot override failed status,
missing destinations, malformed/missing hashes or recorded errors. No files is an empty result.

Source of truth and full output contract: `docs/pdf-redesign-contract.md`.
Fixture: `DataManager/tests/runtime/checksum_pdf_fixtures.py`; synthetic records are marked
DEBUG DATA and include the long Korean title, mixed identifiers, `<>&`, 0 bytes,
mismatched hashes, and a missing configured destination.

## Verification

- DataManager `.venv/bin/python -m pytest -q`: 65 passed.
- Four dedicated PDF tests validate projection, complete Korean/hash/path extraction,
  source order, empty data, conservative verification status, embedded fonts, page numbering,
  and 40 files with a 500-sentence multi-page error. Full repeated message body and its
  final sentinel are checked after excluding running page headers/footers.
- Targeted Ruff checks and mypy for both changed production modules pass.
- Built a wheel offline with the existing app's packaging runtime; verified both TTFs,
  OFL.txt and font provenance in the archive. Installed it to an isolated directory and
  generated a Korean report with the app's ReportLab 5.0.1 runtime, using only packaged
  fonts. No host font fallback is needed.
- `output/pdf/DEBUG-DATA-checksum-redesign.pdf`: five A4 pages, eight ordered files.
  Rasterized every page and inspected all five at 1200px height. No clipping, overlap,
  glyph failure or fragmented ordinary file evidence was found.
- `.pipeline/pdf-redesign-qa/checksum/DEBUG-DATA-checksum-pressure.pdf`: 24 pages,
  40 files, 500 repeated Korean sentences plus FINAL-SENTINEL. Inspected long-text
  pages 2/3 at 1200px; extraction preserves the tail and last file.
- Poppler word bounding boxes: 625 words in the sample and 4,644 in the long fixture;
  zero words outside the document's horizontal margins or physical page bounds.

This is a renderer validation using synthetic stored evidence. It does not perform a
new live-media copy or rehash the user's existing footage. The app's end-to-end synthetic
workflow and DataHelper independent QA remain the parent's combined completion gate.
