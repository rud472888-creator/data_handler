Local cleanup archive, 2026-10-16

The backup branch retains all four local UI commits on top of origin/main 9648362.
DataHelper and DataManager source revisions match their latest origin/main at backup time.
Unmerged remote feature branches, including qa/numeric-video-v1, remain separate.

local-work-evidence.tar.gz preserves ignored working evidence, run records, design/QA notes and agent workspace setup.
Extract at the repository root with: tar -xzf archive/local-cleanup-2026-10-16/local-work-evidence.tar.gz
evidence-manifest.json contains per-file SHA-256 values.
Git bundles preserve original branches and remote refs; git clone <name>.bundle restores each repository.
Original untracked PDFs/wheels are committed under output/ and tmp/.
DataHelper QA output files, including normally ignored PDFs/images, are preserved in its backup branch.

Excluded: generated caches, Python environments, .codegraph generated index, build/dist and reinstallable model weights.

application-state.tar.gz preserves non-model files from ~/Library/Application Support/Data Handler (logs and .pipeline). Extract it into that application support folder.
Verification: orchestrator test suite passed 293 tests, skipped 1; 2 dependency deprecation warnings.
