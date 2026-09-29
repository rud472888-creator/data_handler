#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
APP_NAME="Data Handler DIT"
BUNDLE_ID="com.dit.data-handler.workspace"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_BUNDLE="$ROOT_DIR/dist/$APP_NAME.app"
APP_BINARY="$APP_BUNDLE/Contents/MacOS/$APP_NAME"
APP_ROOT="$APP_BUNDLE/Contents/Resources/app"

usage() {
  echo "usage: $0 [run|--debug|--logs|--telemetry|--verify|--package]" >&2
}

stop_running_app() {
  local running_pids
  running_pids="$(/usr/bin/osascript -l JavaScript - "$BUNDLE_ID" "$APP_BINARY" <<'JXA'
ObjC.import('AppKit')

function run(argv) {
  const bundleIdentifier = argv[0]
  const executablePath = argv[1]
  const pids = []

  for (const application of $.NSWorkspace.sharedWorkspace.runningApplications.js) {
    const identifier = application.bundleIdentifier
    const executableURL = application.executableURL
    if (!identifier || !executableURL) {
      continue
    }
    if (ObjC.unwrap(identifier) !== bundleIdentifier || ObjC.unwrap(executableURL.path) !== executablePath) {
      continue
    }

    pids.push(String(application.processIdentifier))
    // JXA invokes zero-argument Objective-C methods through property access.
    application.terminate
  }

  return pids.join(' ')
}
JXA
)"

  if [[ -n "$running_pids" ]]; then
    local attempts=0
    local app_is_running
    local pid
    while (( attempts < 50 )); do
      app_is_running=0
      for pid in $running_pids; do
        if kill -0 "$pid" >/dev/null 2>&1; then
          app_is_running=1
          break
        fi
      done
      if (( app_is_running == 0 )); then
        break
      fi
      sleep 0.1
      attempts=$((attempts + 1))
    done

    for pid in $running_pids; do
      if [[ "$(/bin/ps -p "$pid" -o command= 2>/dev/null || true)" == "$APP_BINARY" ]]; then
        echo "$APP_NAME did not quit within 5 seconds; forcing PID $pid to exit." >&2
        kill -KILL "$pid" >/dev/null 2>&1 || true
      fi
    done
  fi

  stop_orphaned_backends
}

is_bundle_backend() {
  local pid="$1"
  local command
  local cwd
  command="$(/bin/ps -p "$pid" -o command= 2>/dev/null || true)"
  case "$command" in
    *" -m orchestrator.cli app --host 127.0.0.1 --port "*) ;;
    *) return 1 ;;
  esac
  cwd="$(/usr/sbin/lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | /usr/bin/sed -n 's/^n//p')"
  [[ "$cwd" == "$APP_ROOT" ]]
}

stop_orphaned_backends() {
  local backend_pids=""
  local pid
  for pid in $(/usr/bin/pgrep -f 'orchestrator\.cli app --host 127\.0\.0\.1 --port' 2>/dev/null || true); do
    if is_bundle_backend "$pid"; then
      backend_pids="$backend_pids $pid"
      kill -TERM "$pid" >/dev/null 2>&1 || true
    fi
  done

  if [[ -z "$backend_pids" ]]; then
    return
  fi

  local attempts=0
  local backend_is_running
  while (( attempts < 50 )); do
    backend_is_running=0
    for pid in $backend_pids; do
      if is_bundle_backend "$pid"; then
        backend_is_running=1
        break
      fi
    done
    if (( backend_is_running == 0 )); then
      return
    fi
    sleep 0.1
    attempts=$((attempts + 1))
  done

  for pid in $backend_pids; do
    if is_bundle_backend "$pid"; then
      echo "$APP_NAME backend did not quit within 5 seconds; forcing PID $pid to exit." >&2
      kill -KILL "$pid" >/dev/null 2>&1 || true
    fi
  done
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
