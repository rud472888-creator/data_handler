# DIT workspace design contract

## Atmosphere
Dense, dark, native desktop instrument for on-set data managers. Project library is the permanent context; a card is the unit of work. Variance 3, motion 1, density 8. The generated target is `.superloopy/evidence/frontend/dit-rebuild/target.png`. Translate its sidebar / library / inspector / queue arrangement, excluding fictional telemetry, decorative icons, version labels and unsupported pause controls. Korean UI copy. No marketing imagery is appropriate to an empty media library.

## Color
`--bg: #191c20`, `--surface: #20242a`, `--raised: #292f37`, `--border: #363c44`, `--text: #edf0f3`, `--muted: #a8b0bc`, `--accent: #70aaff`, `--selected: #263b56`, `--good: #89d4ac`, `--warning: #f0c278`, `--danger: #ffaba7`. Muted and primary text exceed 4.5:1 against their surfaces. Accent buttons use background-colored text.

## Typography
Deliberate native stack: -apple-system, BlinkMacSystemFont, sans-serif. Body 13px / 1.5 / 400; secondary 12px; headings 18px / 600; empty-state title 24px / 600. Paths use ui-monospace, monospace at 12px. Tabular numerals. No tracked uppercase labels.

## Spacing
Base unit: 4px. Spacing scale: 4, 8, 12, 16, 20, 24, 32, 40, 48px. Hairlines 1px. Sidebar 220px, inspector 300px, queue 120px minimum, 180px maximum with scrolling. Desktop is viewport-locked with independently scrolling library and inspector so the queue stays visible. Controls 36px desktop, 44px touch. Dialog max 640px. PDF preview max 1100px, viewport minus 32px, header allowance 64px. Desktop breakpoint 1100px, compact 700px. Radius 4px controls, 8px dialog. Body minimum width 320px.

## Components
Continuous three-pane workspace separated by borders; no dashboard cards. Project row and card row use selected background with accent text. Table columns collapse into labeled stacked rows on narrow screens. Inspector sits below library below 1100px. Project sidebar stacks above below 700px. Explicit empty, loading, persistent error states. Focus outline 2px accent, offset 2px. Disabled opacity .5; hover raised surface. Card import is a form followed by an explicit review of project, original path and exact destinations before starting. Search and date filter remain visible. PDF links are available only for declared nonempty files, and unavailable artifacts retain their reason.

## Motion
No decorative motion or animated progress. Native focus and hover only. No simulated percentages or estimated time. Reduced-motion is respected by default.

## Depth
Borders and tonal surfaces only. Dialog backdrop uses background at 80% opacity. No shadows, gradients, glow or glass.

Project removal uses a secondary toolbar action and existing 640px confirmation dialog. Explicitly name the project and state that original, replica and report files stay on disk. Destructive text uses --danger. A compact removable-state banner offers undo. No new visual tokens.
