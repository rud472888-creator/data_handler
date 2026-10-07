# DIT workspace design contract

## Source

Blurssism 1.5.0, upstream commit `f87d4d5708cc9ebd88b715d40f4f3cee97515010`, retrieved 2026-10-07 from https://github.com/leeuc10/blurssism. The Codex adapter is installed at `~/.codex/skills/blurssism/SKILL.md`; upstream ships a package and brand book rather than an agent skill. This contract replaces the previous dark instrument theme.

The checked-in framework-independent distribution is `static/vendor/blurssism/`, including its MIT license and exact source hashes in `source.json`. Only remote font imports are removed from the application copies. Pretendard 1.3.9 and Gowun Batang are bundled in `static/fonts/`, with SIL OFL licenses and source hashes, so screen rendering does not require a network.

## Tokens and typography

Load local fonts, upstream tokens, upstream component styles, existing feature styles, and finally `design-system.css`. The adapter maps existing `--bg`, `--surface`, `--raised`, `--border`, `--text`, `--muted`, `--selected`, and `--good` names to Blurssism tokens. Avoid introducing feature-specific hardcoded colors.

Use paper, paper-raised, paper-sunken and ink for at least 90% of the visible screen. Espresso is the initial palette; all 13 upstream palettes and system/light/dark themes are selectable. Status retains both its actual label and semantic color. Selected modes and projects include a dot; selected rows include a left rule and aria-pressed on the card button.

Pretendard is the UI face, 14px/1.6 body and 12–13px metadata. Large project names, the app name and empty-state headings use Gowun Batang. Paths stay 12px monospace, break safely, and never become serif. Numerical records use tabular figures. Keep Korean prose in 해요체, with word-level wrapping and concrete recovery instructions.

## Layout and components

The permanent project sidebar preserves project → shooting day → card navigation. At lg (1120px) and above, the sidebar is 248px, the review pane is 304px, and library/review/queue panels remain independently scrollable in a viewport-locked workspace. At xl (1440px), sidebar/review widths become 264/336px. The working surfaces are opaque paper-raised with a 24px radius and a fine line.

Below lg, reviews stack beneath the library. Below md (768px), mode navigation becomes a fixed bottom capsule, card rows become labeled stacked cells, and dialogs become bottom sheets capped at 90dvh. The source breakpoints are xs below 600px, sm from 600px, md from 768px, lg from 1120px, xl from 1440px. Use the upstream grid margins on narrow screens. No horizontal clipping at 320px and above.

Buttons use capsule corners; inputs/selects/textareas use 16px corners; panels/dialogs use 24px or larger. Desktop controls are at least 40px, touch controls at least 44px. Use 4px-unit spacing. Focus is a 2px focus-ring with a 3px offset. Controls use line-strong borders, never decorative low-contrast borders. Disabled controls use paper-sunken/ink-subtle instead of fading the whole element.

Keep one primary action in the active view. The library uses its empty-state CTA until it contains cards, then the toolbar import action. In agent chat, the latest available approval takes priority over Send; earlier approvals remain secondary. Confirmation dialogs have their own primary action.

## Material, effects and appearance

Only the mode navigation, library tabs and dialogs use crema. Lists, rows, status chips, fields, review prose and conversation content are opaque. Do not nest crema or add blur to repeated rows. Default mode has at most three visible crema surfaces, rich desktop mode at most six, off mode zero. Use the 1.5 crema names rather than the deprecated glass names.

Appearance settings live in a small labeled dialog reachable from every mode. Persist validated choices in `dit-appearance`. Apply saved colors before the first paint. System theme follows OS color-scheme changes. Storage failure leaves the current settings applied and reports that they cannot persist; project/chat storage also fails gracefully.

Use the upstream device-aware crema helper. Hardware/data-saving/reduced-transparency fallback overrides effects, and changes to reduced transparency or connection settings are handled while the app is open. Rich mode can adapt to desktop width. Pointer-following lights are disabled for this operational workspace. No simulated progress, blur-radius animation, decorative movement or background motion. Reduced motion disables animation and transitions.

## Operational invariants

Card import remains a form followed by explicit confirmation of project, original source and every final destination. Destinations are ordered and unlimited, start with one row, preserve a minimum of one, and retain a labeled native folder picker where available. Fields/review lists scroll, and the confirmation footer stays visible. Editing a 100-path plan must retain every path. Appearance changes never start a run or alter the copy/reporting engines.

Verification is derived only from durable completion events. PDF failures remain separate from checksum results. Missing or offline artifacts retain their reason. Do not add fabricated percentages, speeds, ETA or per-replica progress. The queue and review panes report actual states and completion evidence.

Project removal still requires confirmation, preserves original/backup/PDF files and workflow records, and offers undo. Busy/unconfirmed projects remain protected by the existing API. PDF previews remain native dialogs with opaque frames and a reachable close action.

Agent mode remains a peer workspace with a scrollable transcript, inline path review and an anchored composer. Blackmagician retains project context, connection state, shooting details, questions, recent entries and the shared agent. Inputs must survive background record updates. Neither mode is a floating widget.

## Verification

Run `python -m pytest orchestrator/tests` with the app's dependency-complete Python environment. `script/verify_ui_design.mjs` uses Playwright and a local test server with fixture-only API responses; it checks actual browser interaction, palette/state contrast, saved settings, breakpoint geometry, 100-path confirmations, touch sheets, errors, storage failure and low-end effects. It never starts a copy job. Screenshots and `result.json` go to `.pipeline/uiux-qa/` by default.

Rebuild and launch the macOS app with `script/build_and_run.sh`, then verify the packaged static resources and native WebKit screen. The Run action remains connected to this script.
