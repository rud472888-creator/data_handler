#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
APP_NAME="Data Handler"
BUNDLE_ID="com.dit.data-handler"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_BUNDLE="$ROOT_DIR/dist/$APP_NAME.app"
APP_BINARY="$APP_BUNDLE/Contents/MacOS/$APP_NAME"

usage() {
  echo "usage: $0 [run|--debug|--logs|--telemetry|--verify|--package]" >&2
}

stop_running_app() {
  pkill -x "$APP_NAME" >/dev/null 2>&1 || true
  pkill -f "$APP_BUNDLE/Contents/Resources/venv/bin/python -m orchestrator.cli" >/dev/null 2>&1 || true
}

package_app() {
  "$ROOT_DIR/script/package_macos_app.sh"
}

open_app() {
  /usr/bin/open -n "$APP_BUNDLE"
}

stop_running_app

case "$MODE" in
  run)
    package_app
    open_app
    ;;
  --package|package)
    package_app
    ;;
  --debug|debug)
    package_app
    lldb -- "$APP_BINARY"
    ;;
  --logs|logs)
    package_app
    open_app
    /usr/bin/log stream --info --style compact --predicate "process == \"$APP_NAME\""
    ;;
  --telemetry|telemetry)
    package_app
    open_app
    /usr/bin/log stream --info --style compact --predicate "subsystem == \"$BUNDLE_ID\""
    ;;
  --verify|verify)
    package_app
    open_app
    sleep 4
    pgrep -x "$APP_NAME" >/dev/null
    ;;
  *)
    usage
    exit 2
    ;;
esac
