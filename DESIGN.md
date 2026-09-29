# Data Handler Design System

## Atmosphere / Signature

Data Handler is a quiet Job Console for DIT operators moving camera media into verified backups and reports. The signature is a compact command bar above border-led work lists: a light canvas, one restrained blue action color, semantic status color only where action is required, and no decorative chrome. The first screen is the Jobs view. It must answer what is running, whether the copies are safe, what needs review, and where the report can be opened.

Design dials:
- DESIGN_VARIANCE: 3
- MOTION_INTENSITY: 2
- VISUAL_DENSITY: 7

Information architecture:
- Jobs is the default screen and owns current status, recovery, and recent history.
- New Backup owns project preset, source, destinations, mounted-volume status, preflight checks, and the live process strip.
- Reports owns artifact availability, inspection results, and report actions.
- Mounted volumes remain visible in the sidebar on desktop and inside New Backup at every viewport. They are not a standalone destination.
- Mounted Volumes contains only disks reported as currently connected. Configured paths that are unavailable live under a separate Reconnect Required heading.
- DataManager and DataHandler are internal Job stages, never primary navigation labels.

Lazyweb references used as pattern evidence:
- Document360 dashboard: overview metrics, search-oriented operational layout.
- Mage Legal Tabular dashboard: searchable file table and compact data-room context.
- Apprentice Health workflow dashboard: visual workflow path plus status-coded table.
- Bitrix24 task dashboard: completion statistics and status breakdown.
- Symbium project creation: focused project setup inputs.

## Color

Core tokens:
- `#f4f6f9` / `--bg` / application background.
- `#ffffff` / `--surface` / panels, dialogs, controls.
- `#f6f8fb` / `--surface-muted` / quiet nested surfaces.
- `#172033` / `--text` / primary text, near-black.
- `#667085` / `--muted` / secondary copy.
- `#667085` / `--faint` / low-emphasis labels that still meet body-text contrast.
- `#e4e8ef` / `--border` / standard separators.
- `#cbd2dc` / `--border-strong` / inputs and stronger dividers.
- `#3568d4` / `--accent` / primary command and progress.
- `#2854b4` / `--accent-strong` / primary hover and active text.
- `#eef4ff` / `--accent-soft` / the active navigation row only.
- `#16825d` / `--running` / successful and active runtime state.
- `#b85c00` / `--starting` / queued or starting state.
- `#b3261e` / `--danger` and `--failed` / errors.
- `#fff4f2` / `--danger-bg` / error surfaces.
- `#fff8eb` / `--warning-bg` / completed-with-review and reconnect surfaces.
- `#edf8f3` / `--success-bg` / verified completion surfaces.

Supporting declared colors already present in the app shell:
- `#fff` / white shorthand in legacy declarations.
- `#36527e` / callout text.
- `#edf1f7` / progress track.
- `#edf0f4` / list separators.
- `#f0c4bd` / alert border.
- `#edc4bf` / danger button border.
- `#f7f7f5` / macOS failure page background.
- `#1f2328` / macOS failure page foreground.
- `#e5e2dd` / macOS failure page border.
- `#68707a` / macOS failure page copy.
- `#000000` / PDF frame outline alpha base only.

Contrast notes: `--text` on `--bg` and `--surface` exceeds 4.5:1. `--accent` on white is used for text sparingly; primary buttons use white text on `--accent`.

## Typography

Font stack: `ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`. The app intentionally uses the native macOS/system stack for an operator tool feel.

Ramp:
- App title: 24px, weight 700, line-height 1.2.
- Panel title: 16px, weight 700, line-height 1.25.
- Body: 14px, weight 400, line-height 1.45.
- Control: 13px, weight 600, line-height 1.4.
- Metadata: 12px, weight 400-700, line-height 1.4.
- Label: 11px, weight 700, uppercase, letter-spacing 0.
- Numerals: tabular when displaying percent, counts, capacity, and step index.

## Spacing

Base unit: 2px. Most layout spacing should still land on 4px multiples, but 2px is allowed for dense desktop controls and optical alignment. Common tokens:
- `--space-1`: 2px.
- `--space-2`: 4px.
- `--space-3`: 6px.
- `--space-4`: 8px.
- `--space-5`: 10px.
- `--space-6`: 12px.
- `--space-7`: 14px.
- `--space-8`: 16px.
- `--space-9`: 18px.
- `--space-10`: 20px.
- `--space-11`: 22px.
- `--space-12`: 24px.
- `--space-14`: 28px.
- `--space-16`: 32px.

Do not add new off-scale spacing values unless they are a 1px hairline.

## Components

App shell:
- Fixed left navigation at 216px desktop, icon rail or stacked header on narrow screens.
- Workspace padding: 24px desktop, 18px/16px mobile.
- Default macOS content size is 1200px by 800px; minimum desktop size is 1100px by 760px.
- Sections are full app regions, not nested cards inside cards.
- The workspace toolbar is a compact command bar with a bottom hairline, not a floating card. Its project selector and right action occupy fixed columns across every page.
- Desktop toolbar helper copy is hidden because the active card repeats the same guidance.

Panels:
- Background `--surface`, radius 8px, one-pixel `--border` outline, no default shadow.
- Hover may use a quiet tonal shift only; no layout movement or elevation change.
- Panel body density should favor scan speed over large empty marketing space.
- The desktop workspace is viewport-locked. The content grid consumes the exact remaining height after toolbar and padding, with no page scrollbar.
- Each view's left and right panel columns share one top and bottom edge. Stacked cards use the same combined height as the opposite primary card.
- Enlarged panels redistribute height to real rows, stage cells, output groups, history entries, and volume groups instead of leaving an unstructured blank region.
- New Backup readiness rows use the compact 8px internal rhythm so readiness plus Selected Job fit the default viewport.
- Repeated operational data uses rows and separators instead of individually tinted cards.
- Empty history slots are omitted instead of rendering placeholder rows.

Primary action:
- Background `--accent`, hover `--accent-strong`, text white.
- Minimum height 44px, 8px radius, clear disabled state.

Inputs:
- 44px minimum height, border `--border-strong`, 8px radius.
- Focus ring uses accent with 16% alpha.

Progress:
- Overall progress owns the primary `--accent` bar.
- Stage timeline uses `done`, `current`, `pending`, `needs-review`, `blocked`, and `failed` states.
- Current stage must have text and shape, not only color.
- New Backup reuses the live Job progress strip and timeline; it does not display a decorative or simulated progress value.
- Unknown progress is shown as unknown, never as zero percent.
- Process result, verification result, and artifact availability remain separate state fields.

Status language:
- `Verified` means copy and checksum passed and no media review issue is known.
- `Needs review` means the process finished but one or more media checks need attention.
- `Failed` means the Job did not reach a safe handoff state.
- `Drive offline` means an artifact is recorded but its destination volume is disconnected.

Dialogs:
- Width min(560px, viewport - 32px), max-height viewport - 32px.
- Forms group related fields with visible labels and short hints.

## Motion

Motion is functional only. Durations should stay between 150ms and 300ms, using transform, opacity, color, or width only. Respect reduced motion by collapsing transitions.

## Depth

Depth is border-led with a single overlay shadow:
- `--shadow-border`: legacy control elevation only, not for page panels.
- `--shadow-border-hover`: legacy control hover only.
- `--shadow`: modal and overlay elevation.

Do not introduce glow, glassmorphism, or decorative gradients. The brand mark is a flat accent surface.
