# PDF redesign contract - 2026-09-11

The subsequent user request for three clips per page and no appendix supersedes the
clip-layout/full-evidence requirements below. See `pdf-density-validation.md` and
`DataHelper/Docs/reports/dev/2026-09-11-pdf-density-plan.md` for that compact projection.
The checksum contract remains unchanged.

Classification: existing renderer modification and explicit visual redesign.

Reader: DIT operator, editor and production handoff recipient.
Purpose: assess recorded copy integrity and sampled clip readability, locate exceptions,
and retain the underlying evidence for handoff.
Source of truth: DataManager persisted Job/JobFile/JobFileReplica records and DataHelper
BatchReport/ReportItem/CapturePoint records. UI state is not an export source.
Scope: all records passed to each existing export, with original ordering and no new filters.
Grouping: project summary, exception index, file/clip evidence in source order.
Missing values: `미기록` (not recorded); missing evidence never counts as verified.
Debug marker: synthetic deliverables include `DEBUG DATA` in filename and document title.
Paired outputs: existing manifest JSON and DataHelper CSV/JSON retain their fields and order.

## Checksum output

Keep `00_Master/reports/checksum.pdf`, report repository registration and checksum behavior.
Show project name, job ID, generated local timestamp with UTC offset, total files and bytes,
verified/review file counts, expected destination IDs, full source-relative path, source path ID,
file ID, recorded status, size in bytes, full source SHA-256, and every destination's ID,
path, status, full SHA-256, comparison result, error code and message. Show missing configured
destinations explicitly. Equality alone is not a pass: the recorded replica must be verified,
have a destination and both valid hashes. No files is an empty result, not successful verification.
The summary may say verified only if every expected replica has evidence and the file status
is verified without recorded errors. Hash mismatch, missing, failed and unrecorded states are distinct.

## Layout and rendering

A4 portrait; 40 pt side margins, 45 pt top/bottom; white paper, graphite typography,
deep teal (#146C66) as the accent with semantic amber/red. Editorial title and compact
running header, ruled section titles, metric strip, clear status words, page X / Y footer.
ReportLab Platypus supplies measured paragraphs, tables, repeated headers and automatic
continuations; canvas is reserved for bounded page decoration. Embedded static Korean
fonts avoid machine-dependent glyph substitution. Korean prose wraps at spaces; machine
identifiers, paths and hashes are individually breakable. Escape all user-controlled text.
Images retain their full aspect ratio. Long rows and messages continue rather than truncate.

## Pressure fixtures and checks

Before renderer changes create fixtures for a long Korean project name and paths, XML-like
characters, full hashes, mixed identifiers, 0-byte files, missing checksum/path/replica,
mismatched hashes, failed recorded status with equal hashes, replica-level errors, empty
input and 40+ files forcing page breaks. Clip fixtures additionally cover all capture points,
missing/corrupt/portrait/wide images, unknown metadata and lengthy warnings.

Validate extracted text, full identifiers/hashes, record order, summary counts, embedded fonts,
page count/numbering, repeated headers, and render final pages to PNG for visual inspection.
Run both changed component suites plus orchestrator/tests. Synthetic checks do not start
a production copy run or change any source or replica data.
