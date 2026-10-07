# Black Blurssism refinement

2026-10-07. Keeps the accepted DIT panel responsibilities and replaces the color/material styling after operator feedback. The requested palette is **black, gray and white throughout**, including status icons, focus rings, shadows and crema texture. There are no beige, blue, green, amber or red interface accents.

## Applied skill rules

Read the installed Blurssism 1.5.0 skill and upstream brand book. The checked-in 1.5 distribution and utilities are used directly. The operator's black-only request overrides the brand book's warm paper/ink colors. The graphite palette identifier is kept, with explicit neutral application overrides documented in `orchestrator/dit_app/DESIGN.md`.

- **90/10:** quiet black paper and neutral ink; one primary action per active view.
- **Floating surfaces only:** thin `.bl-crema` on mode navigation and library tabs, thick `.bl-crema-thick` on dialogs. Reading panels, lists and fields remain opaque; no nested crema.
- **Capsules and corners:** capsule controls, 16px fields, 24px panels/dialogs. The former full-width frosted toolbar is removed; material belongs to the floating control groups.
- **Type and copy:** local Pretendard UI, Gowun Batang for large project names and empty headings, monospace paths, Korean word-level wrapping and 해요체 empty-state copy.
- **Effects:** maximum two persistent crema surfaces, three with a dialog. Rich/pointer effects disabled; user-off and device/accessibility preferences produce opaque surfaces.
- **Accessibility:** preserve keyboard navigation, focus containment/restoration, explicit labels and state words/icons. Status meaning remains clear without colored badges.

The Silverstack, Resolve, Premiere and Final Cut reference research remains in `uiux-dit-redesign.md`. The layout continues to use a project/day navigator, table, metadata inspector and recorded jobs, without adding a media viewer or timeline.

## Verification evidence

Evidence is saved under `.pipeline/uiux-black/`. Browser checks use the isolated synthetic server; real copies are blocked. Screenshots with populated cards contain verification data, not the operator's media.

- `monochrome.json`: 534 visible workspace elements checked for non-neutral foreground/background/border/outline channels; none found.
- `responsive.json`: actual document, toolbar and navigation widths at 320, 390, 767, 768, 1024 and 1200px; no page overflow.
- `effects-off.json`: all three visible material surfaces become blur-free; the off preference survives reload.
- `axe-workspace.json`, `axe-settings.json`, `axe-import-100.json`: zero automated violations in all three views. Glass gradients and some select/keyboard text required manual contrast review; these results are not a blanket accessibility certification.
- `contrast.json`: sampled text passes 4.5:1, with conservative glass-background bounds. Minimum dark/light text ratios are 6.00:1 and 5.44:1; minimum field-border ratios are 4.35:1 and 3.88:1.
- `appearance-api-checks.json`: all nine checks pass. These exercise the real appearance modules with mocked browser APIs for low hardware, data saving, live reduced-transparency changes, validated settings and storage failure.
- `dialog-focus.json`: Tab remains inside the import dialog and Escape restores focus to the import button. The rebuilt native app also restores focus to that button after Escape.
- `import-100.json`: all 100 synthetic backup paths remain in the confirmation view; the last path is present and the action footer stays within the 720px viewport. The final copy-start action was not submitted.
- `orchestrator-tests.log`: 293 passed, one skipped, two dependency deprecation warnings.
- `build.log`, `signature.log`, `package-static-check.json`: the macOS app and DMG were rebuilt and the app relaunched. The app passes code-signature verification; all 48 packaged static files match the source hashes.

`script/verify_ui_design.mjs` was updated and syntax-checked, but its standalone browser runner was not executed. Browser interactions used CUA. No end-to-end VoiceOver session or media-copy run is claimed.
