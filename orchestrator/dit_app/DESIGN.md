# DIT workspace design contract

## Atmosphere
Dense, dark, native desktop instrument for on-set data managers. Project library is the permanent context; a card is the unit of work. Variance 3, motion 1, density 8. The generated target is `.superloopy/evidence/frontend/dit-rebuild/target.png`. Translate its sidebar / library / review / queue arrangement, excluding fictional telemetry, decorative icons, version labels and unsupported pause controls. Korean UI copy. No marketing imagery is appropriate to an empty media library.

## Color
`--bg: #191c20`, `--surface: #20242a`, `--raised: #292f37`, `--border: #363c44`, `--text: #edf0f3`, `--muted: #a8b0bc`, `--accent: #70aaff`, `--selected: #263b56`, `--good: #89d4ac`, `--warning: #f0c278`, `--danger: #ffaba7`. Muted and primary text exceed 4.5:1 against their surfaces. Accent buttons use background-colored text.

## Typography
Deliberate native stack: -apple-system, BlinkMacSystemFont, sans-serif. Body 13px / 1.5 / 400; secondary 12px; headings 18px / 600; empty-state title 24px / 600. Paths use ui-monospace, monospace at 12px. Tabular numerals. No tracked uppercase labels.

## Spacing
Base unit: 4px. Spacing scale: 4, 8, 12, 16, 20, 24, 32, 40, 48px. Hairlines 1px. Sidebar 220px, review panel 300px, queue 120px minimum, 180px maximum with scrolling. Desktop is viewport-locked with independently scrolling library and review panel so the queue stays visible. Controls 36px desktop, 44px touch. Dialog max 640px. PDF preview max 1100px, viewport minus 32px, header allowance 64px. Desktop breakpoint 1100px, compact 700px. Radius 4px controls, 8px dialog. Body minimum width 320px.

## Components
Continuous three-pane workspace separated by borders; no dashboard cards. Project row and card row use selected background with accent text. Table columns collapse into labeled stacked rows on narrow screens. The review panel sits below the library below 1100px. Project sidebar stacks above below 700px. Explicit empty, loading, persistent error states. Focus outline 2px accent, offset 2px. Disabled opacity .5; hover raised surface. Card import is a form followed by an explicit review of project, original path and exact destinations before starting. Search and date filter remain visible. PDF links are available only for declared nonempty files, and unavailable artifacts retain their reason.

## Motion
Card import destinations are an ordered, unlimited list starting with one row. Each row has a numbered label, path input, optional native folder picker and a remove action. Keep at least one row; disable its remove action. Add destinations with a labeled secondary button and announce the destination count. Use existing 8/12/16px spacing, hairlines, native controls and colors. The import form has a viewport-bound height (viewport minus 80px: 32px outer clearance plus 48px dialog padding); fields and the complete review list scroll while the confirmation footer remains available. The narrow footer wraps instead of clipping. No new visual theme or motion.

No decorative motion or animated progress. Native focus and hover only. No simulated percentages or estimated time. Reduced-motion is respected by default.

## Depth
Borders and tonal surfaces only. Dialog backdrop uses background at 80% opacity. No shadows, gradients, glow or glass.

Project removal uses a secondary toolbar action and existing 640px confirmation dialog. Explicitly name the project and state that original, replica and report files stay on disk. Destructive text uses --danger. A compact removable-state banner offers undo. No new visual tokens.

## Agent mode extension
Target: `.superloopy/evidence/frontend/agent-chat/target.png`. Preserve the existing sidebar, tonal borders and native type. Translate the target conversation, inline path review and anchored composer; exclude its synthetic window controls, decorative icons, gradient button and uppercase subtitle. Agent mode is a peer to workspace mode, not a floating widget. Variance 3, motion 1, density 7. No illustrative imagery is appropriate inside an operational transcript; the generated target is a design reference only.

Additional named CSS tokens: `--space-1:4px`, `--space-2:8px`, `--space-3:12px`, `--space-4:16px`, `--space-5:20px`, `--space-6:24px`, `--space-8:32px`, `--space-12:48px`; `--radius-control:4px`, `--radius-panel:8px`; `--text-small:12px`, `--text-body:13px`, `--text-heading:18px`, `--text-empty:24px`; `--chat-width:880px`, `--chat-control:36px`, `--chat-touch:44px`, `--chat-composer:96px`, `--chat-min:400px`, `--chat-context:220px`, `--chat-stroke:1px`, `--chat-focus:2px`. Reuse original colors, weights 400/600 and line height 1.5.

Agent header includes title, actual connection text, conversation selector and 새 대화. Transcript is a single scrollable column max 880px. User messages align right against raised surface; assistant replies align left without avatars. Plans use bordered definition-list rows, readable wrapping monospace paths, one primary confirmation button and a secondary edit action. Completion has evidence-derived status and real PDF links. Composer remains below the transcript with project selector, labeled multiline textarea and 전송. Enter sends; Shift+Enter inserts a newline; composition events must never send Korean text prematurely. Pending, disconnected, error, restored conversation and expired approval states are explicit. No invented activity or model token stream.

Below 700px the mode switch stays visible while redundant library project/volume sections collapse in agent mode; project context remains available in the composer. Controls are 44px, conversation controls wrap, and plan rows become stacked. Agent main remains viewport-locked with internal transcript scrolling at all breakpoints. The token inspector permits structural percentages, flex factors and viewport units. No animation is introduced.

## Blackmagician session extension
Blackmagician is a project-scoped operational dialog launched from the workspace toolbar. It uses the existing dark native colors, native type, 4px spacing scale, 4px controls and 8px panels. No new colors, imagery, glow, gradient, shadow or decorative icons are introduced. Variance 3, motion 1, density 8.

The dialog contains a compact connection form for invite code or session ID, optional Blackmagician project ID for duplicate session resolution, explicit Connect, Refresh, Review, Agent and Disconnect commands, plus persistent error text. Long-running connect, refresh and review actions show button loading text and leave refresh manual. Credentials and tokens are never visible.

Session output is organized as bordered data panels for connection metadata, current camera, current Script, entries, snapshot conflicts and backup review results. Empty, loading, error, stale and ended states are text states inside those panels. Entries and clips render as separated rows with wrapped metadata, not nested cards. The Agent command switches to agent mode, selects the same Data Handler project when available and preloads `/backup-review` without sending it.

## Blackmagician live mode
Reading: a shooting desk for an on-set script supervisor, using the existing native dark instrument direction. Variance 3, motion 1, density 8. This extends the existing operational surface; no illustrative imagery or new visual theme is appropriate.

Blackmagician becomes the third persistent mode. Successful connection opens it. A header names the local project and session and states transport, freshness, pause, reconnect or expiry. The left column holds current camera and Script, open questions, operator confirmations and recent takes. The right column reuses the existing agent conversation and composer. On compact screens the data column stacks above the conversation with independent scrolling. Questions use inline labeled text fields with an explicit save button; local confirmations are labeled as waiting for remote support. Full historical records and backup review remain accessible in connection details.

All values reuse the existing color, type, spacing, control and border tokens. Additional structural tokens: `--shooting-details:400px`, `--shooting-compact-height:40dvh`. Desktop layout columns are minmax(0, 400px) / minmax(0, 1fr), stacked below 1100px. All controls have 44px touch targets below 700px. No animation, simulated telemetry or progress is introduced.

At 700px and below, explicit 촬영 정보 / 에이전트 대화 tabs give each surface a usable full-height scroll area. Both remain available without leaving the mode. A compact project dropdown replaces the sidebar project list. The composer omits its duplicate project selector; the visible dropdown retains project context. The mobile textarea uses the existing 48px spacing token. No data or action is removed.

## Workspace completion reviews
Reading: an on-set operator's completion review log in the existing dark native instrument. Variance 3, motion 1, density 8. Use the existing palette, font, spacing and border tokens. The agent review panel replaces the card inspector in the right-hand 300px workspace column. The separate card-detail panel is removed. The library uses the entire available height, with its summary at the bottom. Review header and status shortcuts stay above an independently scrolling message log. Below 1100px the review panel stacks beneath the library, with the existing 400px chat-min token limiting its message log. No imagery or decorative motion is appropriate to this evidence transcript.

The heading names the selected card. Three sequential review messages have textual states (waiting, reviewing, checked, attention, disconnected) and completion time, separated with hairlines. Facts are followed by optional model explanation and expandable evidence, cause, and recommended action. Full JSON evidence is downloadable. Retry is explicit and starts a fresh session. Empty and persistent error text are visible. A changing result uses polite live announcement without replacing focused controls. Every model fallback is labeled. Review findings promote the card to 확인 필요 while keeping its original checksum state intact.

On compact screens, reserve one 44px filter row for shooting dates and 60px (44px control + 16px spacing) for the volume list while data loads, so receiving these records does not move the workspace down. Additional rows remain fully available and can expand naturally.
