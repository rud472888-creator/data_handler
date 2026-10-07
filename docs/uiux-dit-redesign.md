# DIT workspace redesign

2026-10-07. Replaces the visual direction in `uiux-blurssism-update.md` after operator feedback. The previous Blurssism installation and upstream provenance remain available, but the app no longer loads its palettes, crema effects or serif heading styles.

## Reference research

Official interface screenshots were inspected before implementation, not inferred from product names.

| Source | Observed pattern | Application here |
| --- | --- | --- |
| [Silverstack UI overview](https://kb.pomfort.com/silverstack/reference/library/user-interface-overview/) | Library hierarchy, compact toolbar, metadata inspector and job area | Project/day navigator, card table, inspector and durable job records |
| [DaVinci Resolve Media](https://www.blackmagicdesign.com/products/davinciresolve/media) | Dedicated media browser and metadata workspace; multi-destination clone workflow | Separate card selection from source/destination details |
| [Premiere ingestion workflow](https://helpx.adobe.com/premiere/desktop/organize-media/ingest-proxy-workflow/migrate-existing-prelude-workflows-to-premiere.html) | Neutral dark panels, bin/list metadata and adjustable panel workspace | Opaque surfaces, compact rows and resizable separators |
| [Final Cut Pro interface](https://support.apple.com/en-mk/guide/final-cut-pro/ver92bd100a/mac) | Library/sidebar hierarchy and clear divisions between browser and inspector | Stable panel responsibilities with collapsible details |

These are design adaptations to a card-level copy/verification tool. This app has no clip preview or timeline, so it does not add decorative viewers, fake thumbnails, transfer speed, ETA or invented per-destination verification results.

## Existing-flow audit

The reviewed flow was project selection → card library → source/backup confirmation → verification review. The prior native screenshot is `.pipeline/uiux-dit/01-before-native.png`.

1. Large rounded surfaces and serif headings consumed space needed for card metadata. Replace them with compact neutral panels and local Pretendard UI text.
2. Source/destination details were unavailable in the main workspace. Add a metadata inspector using existing API fields.
3. The primary import action disappeared on an empty project. Keep it in the toolbar whenever a project is selected, with one primary action per state.

## Design and interaction contract

- Default theme: opaque dark. Light and system appearance remain available; density is 40px or 32px per table row. Old color/effect preferences do not override this new direction.
- Toolbar: library, agent and shooting modes. Navigator: projects, shooting days and attached volumes. Main: card table or reports. Inspector: card details and agent review. Bottom: recorded job states.
- Navigator widths: 180–320px; inspector widths: 240–420px. Pointer dragging and keyboard Left/Right, Shift+Left/Right, Home/End are supported. Width and visibility preferences are saved when local storage is available.
- At 1099px or less the inspector becomes an overlay. Below 768px the navigator becomes an off-canvas panel and the table reflows. Native window minimum is 1000×700.
- Card rows expose roll, date, camera, completed file count, phase and source folder. Missing completion counts are shown as unknown. Full paths, checksum evidence, errors and report availability appear in the inspector.
- Search/day filtering selects a visible card. Selecting a job record restores its card in the library. Selection, review and report links retain existing server semantics.
- Actual copies still require the operator to confirm project, source and final replica paths. UI verification uses a separate synthetic server with `/api/runs` blocked.

## Accessibility skill and checks

Read the expanded [web-accessibility skill](https://www.skills.sh/supercent-io/skills-template/web-accessibility), including its semantic HTML, keyboard, focus, contrast and dynamic-announcement requirements. The registry identifies it as v1.0.0. Its linked GitHub repository/raw file returned 404 at research time; no claim is made that a newer GitHub version was installed.

Applied native buttons, labels, table headers, proper inspector tabs, named adjustable separators, skip navigation, visible focus, textual status indicators and polite selection announcements. Native dialogs contain focus, support Escape and restore the opener. Scrollable path/review/chat regions are keyboard focusable. The macOS wrapper enables `WKPreferences.tabFocusesLinks` and matches the titlebar to the selected appearance.

QA evidence is under `.pipeline/uiux-dit/`: before/after screenshots, browser interaction records, axe reports, Python results and build logs. Browser checks use the computer-use tool against a synthetic FastAPI fixture. Responsive widths were measured in same-origin iframes because this host's in-app browser viewport override did not change its actual viewport. The standalone regression runner was updated and syntax-checked; it was not used for this session's browser interactions.

Automatic checks and keyboard checks do not establish complete screen-reader conformance. No end-to-end VoiceOver session or real media copy was performed for this redesign.

## Assets

Icons are unmodified Lucide Static 1.52.0 SVGs from the official npm registry. `static/icons/source.json` records per-file SHA-256 and source; `LICENSE` preserves ISC and Feather-derived MIT notices. Fonts remain local for offline use. No third-party script, analytics or remote font is loaded by the shipped workspace.

## Verification result

- Orchestrator suite: **293 passed, 1 skipped**. Two existing Starlette/httpx deprecation warnings; no engine source changes.
- axe-core 4.14.0: dark/light library, 100-path import review, appearance dialog and mobile agent checks returned **0 violations**. The appearance dialog requested manual review for two select backgrounds (arrow gradients) and a keyboard glyph; their opaque background/text colors were checked separately.
- Sampled text/action contrast: dark minimum **5.25:1**, light minimum **5.78:1**; the primary import action measured 5.35:1 and 6.36:1 respectively. These are sampled controls, not a blanket certification.
- Manual interaction: card Up/Down selection, inspector Left/Right tabs, splitter keys, search shortcut, day filtering, job-to-card selection, dialog Tab/Shift+Tab containment, Escape restoration, mobile navigator selection and inspector dismissal passed.
- Responsive library widths: **320, 390, 767, 768, 1024, 1200px**; document/body widths matched the frame at every size.
- 100 final backup paths remained reviewable and editable, with the confirmation footer inside the window. The isolated fixture recorded **0 copy-start requests**.
- Final macOS build and launch passed, minimum OS **13.0**. Strict deep code-signature verification passed. **48 static files** in the bundle matched source SHA-256 exactly.
- `script/verify_ui_design.mjs` was brought up to date and syntax-checked. This session's browser validation used CUA; the standalone Playwright runner was not executed.

The attempted read of the running app's state API was rejected by automatic approval review under the workspace's prohibition on live progress monitoring. That query was abandoned. UI QA stayed on the isolated fixture; packaging and launch proceeded under the user's app-update authorization.
