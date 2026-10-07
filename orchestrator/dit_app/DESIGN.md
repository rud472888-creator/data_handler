# DIT workspace design contract

## Source and direction

The layout follows the professional media workspaces documented in `docs/uiux-dit-redesign.md`: project/day navigator, card library, inspector and durable job records. The operator requested a completely achromatic black interface and selective Blurssism styling. Black, gray and white therefore replace the upstream warm paper and colored status palette.

Use Blurssism **1.5.0**, upstream commit `f87d4d5708cc9ebd88b715d40f4f3cee97515010`. Its distribution, MIT license and source hashes are in `static/vendor/blurssism/`. Application copies remove remote font imports; the vendor files remain unchanged by the black adaptation. Local Pretendard and Gowun Batang include SIL OFL licenses. No external font or analytics request is required.

Load local fonts, upstream tokens and bundle, feature styles, then `design-system.css`. The app uses the real `.bl-crema`, `.bl-crema-thick`, `setTheme`, `setPalette` and `applyCremaPreference` APIs. The graphite identifier is retained, with explicitly achromatic application token overrides; this is not the unmodified warm graphite palette.

## Color, typography and shape

At least 90% of the screen is paper/ink. Default paper is black `#090909`, raised reading surfaces are `#131313`, and text uses neutral white/gray. Every foreground, surface, state, focus and material tint is achromatic. Successful, waiting, active, warning and failed states remain distinguishable by their words and icons. State color is not required to understand a record.

Pretendard is used for controls, tables and metadata. Large user-created project names and empty-state headings use Gowun Batang at 20px. Paths and card identifiers remain monospace; counts use tabular figures. The compact desktop typography intentionally preserves the operator's accepted DIT density. Korean text uses `keep-all`; long filesystem paths explicitly allow wrapping. New interface copy uses 해요체.

Buttons and tabs are capsules. Fields have 16px corners, reading panels and dialogs 24px. General desktop controls are 40px, touch controls 44px. Inline card/job controls retain their compact target within the 40/32px rows. Focus is a visible 2px neutral ring; input boundaries meet 3:1. A selected mode/tab also has a visible dot, and selected cards/projects have a leading rule.

## Layout and materials

Navigator width defaults to 216px and supports 180–320px. Inspector width defaults to 304px and supports 240–420px. Dragging and Left/Right, Shift+Left/Right, Home/End adjust separators. Below 1100px the inspector is an overlay; below 768px the navigator is off-canvas and card cells reflow. The native window minimum remains 1000×700.

Only floating mode navigation, library tabs and modal dialogs use crema. The navbar and tabs use thin crema; dialogs use thick crema. Library rows, inspector prose, path fields and chat content remain opaque. There is no nested crema or blur in repeated records. Neutral static washes behind the floating controls provide a backdrop; the upstream stationary grain/band/edge stack is reduced in strength and made achromatic.

The normal workspace has two visible crema surfaces; an open dialog makes three. Agent/shooting modes have one before a dialog opens. Rich mode and pointer-following lights are disabled. Manual effect-off, reduced transparency, low hardware capacity or data saving resolve to opaque surfaces. Changes to reduced transparency/data saving are handled while open. Reduced motion removes transitions and animation; blur radius is never animated.

## Appearance and accessibility

Validate and persist theme, density and `crema: auto|off` in `dit-workspace-appearance`. Apply theme and density before first paint; material starts opaque until the upstream helper resolves device preferences. Black is the default. The optional white/system views use the same achromatic rules. Storage failure keeps the applied setting and reports that it cannot be saved.

Keep semantic native buttons, labels, table headers, inspector tabs, named keyboard-adjustable separators, skip navigation and polite announcements. Native dialogs contain Tab/Shift+Tab, support Escape and restore their captured opener, including macOS AX activation. Scrollable path/review/chat regions remain keyboard-focusable. Automatic contrast reports on glass gradients require a separate manual/composited contrast check.

Keep one primary action in the active view. Import remains available in the toolbar for an empty or populated selected project. Confirmation dialogs have their own primary action.

## Operational invariants

Card import is a form followed by explicit confirmation of project, source and every final backup path. Replica lists are ordered and unlimited, maintain at least one row and retain native folder pickers. Fields/review lists scroll while the import footer stays visible. Appearance changes never start a run or change the copy/report engines.

Verification comes from durable completion events. Missing counts, offline reports and failures retain their real meaning. Do not invent transfer speed, ETA, thumbnails or per-destination progress. Project removal preserves originals, backups, reports and workflow records, and retains confirmation/undo. Agent and shooting modes retain their existing workflow and project context.

## Verification

Run `python -m pytest orchestrator/tests` in the dependency-complete environment. Use an isolated fixture for UI checks, with real-copy requests blocked. `script/verify_ui_design.mjs` is the standalone regression runner; this session's actual browser interactions use CUA, and the runner is syntax-checked rather than executed.

Rebuild and launch through `script/build_and_run.sh --verify`. Check the actual native screen, strict code signature and packaged static-file hashes. Current work evidence lives in `.pipeline/uiux-black/` and is described in `docs/uiux-black-blurssism.md`.
