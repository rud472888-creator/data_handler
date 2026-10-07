# UI/UX update — 2026-10-07

The DIT workspace now uses Blurssism's paper/ink surfaces, Korean typography and crema navigation across the library, agent and Blackmagician views. Appearance settings offer system/light/dark brightness, all 13 upstream palettes and adaptive/off transparency. Fonts and design assets are bundled locally.

## Sources

- Application: latest fetched `origin/main`, `9648362fb89efbe5852929c7861a5e252e97bebb`.
- DataManager: the main branch's pinned submodule, `84e9b16f3c9e095388bbf14e90e12b67d70f8154`.
- DataHelper: the main branch's pinned submodule, `fa15452bda4645881125ef62a3f8530745734f4d`.
- [Blurssism](https://github.com/leeuc10/blurssism): version 1.5.0, `f87d4d5708cc9ebd88b715d40f4f3cee97515010`.

Upstream provides a package and brand book, without `SKILL.md`. A Codex adapter based on that brand book is installed at `/Users/ijaegyeong/.codex/skills/blurssism/SKILL.md`, with the original reference, distribution, license and source metadata. The application vendors the original distribution, removing only remote font imports. Font licenses, source URLs and hashes are recorded with the bundled files.

## Behavior

- The working library, review text and editable paths remain opaque; floating navigation, tabs and dialogs use crema. Reduced transparency and constrained devices disable effects. Reduced motion disables transitions.
- Large project names use Gowun Batang; controls use Pretendard and paths use monospace. Status chips retain readable labels. Selection and focus remain visible without relying on color alone.
- Empty views expose one primary action. Agent approval takes priority over Send. Card selection preserves keyboard focus when the library rerenders.
- Desktop panels retain their scroll areas. Smaller windows stack the review pane; mobile layouts provide a bottom mode bar, 44px controls and bounded sheets.
- Import confirmation retains every final destination, including a 100-path plan, and requires an explicit start. Refresh errors preserve the library; removal and undo still work. Unavailable local storage leaves both the workspace and chat usable.
- The app compiler now targets the same minimum macOS version (13.0) declared in the bundle. This fixes launch failure when the development SDK's default deployment target is newer than the installed OS.

No DataManager or DataHelper source was edited. UI verification uses fixture responses and starts no copy/reporting run.

## Verification

| Check | Result |
| --- | --- |
| Orchestrator, app dependency environment | 293 passed, 1 skipped |
| DataManager, project virtual environment | 71 passed |
| DataHelper, offscreen Qt | 183 passed |
| Browser interactions and responsive layouts | 13 checks passed |
| 13 palettes × 2 themes | Primary/status text ≥4.5:1; minimum primary 6.04:1 |
| Fixture browser requests | No script errors, external font requests or production runs |
| macOS package | Built and launched; native WebKit workspace/settings inspected |
| Packaged static assets | All 24 files match source hashes; none missing |
| macOS signature / deployment | Strict signature verification passed; binary and plist both target 13.0 |

The orchestrator run has two dependency deprecation warnings. Tests ran with `.pipeline/agent-venv` because the shell's Anaconda Python lacks the app's ReportLab dependency.

Reproduce UI verification with a local app server on port 8876 and Playwright available to Node, then run `node script/verify_ui_design.mjs`. The runner mocks every API request. Results and synthetic screenshots are in `.pipeline/uiux-qa/`; they verify the UI rather than real media replication. Python/build logs are preserved there as well.

The rebuilt app and installer are `dist/Data Handler DIT.app` and `dist/Data Handler DIT.dmg`. The design contract is maintained in `orchestrator/dit_app/DESIGN.md`.
