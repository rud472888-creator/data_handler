# Data Pipeline Orchestrator

This top-level orchestrator coordinates `DataManager` and `DataHelper` without
modifying either cloned program.

## Start an Approved Run

Run this after Hermes has confirmed the source path, replica paths, and project
name with the operator:

```sh
cd /Users/ijaegyeong/Documents/data_handler
python -m orchestrator.cli start \
  --source /path/to/source \
  --replica-path /path/to/path1 \
  --replica-path /path/to/path2 \
  --replica-path /path/to/path3 \
  --project-name "Project Name" \
  --profile macbook-dit-agent
```

The command writes `request.json` and starts DataManager in the background.
When DataManager writes `events/datamanager.done.json`, the worker immediately
starts DataHelper once and records `events/datahelper.started.json` as the
durable guard against duplicate starts. Durable state lives under
`.pipeline/runs/<run_id>/`.

## Watcher

The launchd plist at `launchd/ai.hermes.data-pipeline-watcher.plist` runs one
watch pass every 60 seconds. A pass only reacts to new `*.done.json` artifacts:

- `datamanager.done.json` wakes Hermes to verify replica completion. If
  DataHelper has not already been started, this path starts it once.
- `datahelper.done.json` wakes Hermes to create `final-report.md` and attempt
  final delivery.

For deterministic local testing without Hermes:

```sh
python -m orchestrator.cli watch-once --direct
```

## App Front

The app front is the local operator shell for creating projects, reviewing
mounted sources and destinations, and starting Data Manager replication runs.

```sh
python -m orchestrator.cli app --host 127.0.0.1 --port 8750
```

Open `http://127.0.0.1:8750` to use the same Data Handler interface that is
bundled into the macOS app. The legacy `console` command is kept only as a
compatibility entrypoint for the same API and UI.

## macOS Package

Build the local macOS app bundle and DMG:

```sh
./script/package_macos_app.sh
```

The outputs are `dist/Data Handler.app` and `dist/Data Handler.dmg`. The bundle
contains the app-front WebView launcher, the orchestrator, DataManager,
DataHelper, and an app-local Python environment. Runtime state is written to
`~/Library/Application Support/Data Handler/.pipeline` instead of the signed app
bundle.

For the Codex app Run action:

```sh
./script/build_and_run.sh
```

The package is ad-hoc signed for local use. Developer ID signing and notarization
are still required before broad external distribution.

## Delivery

Delivery uses the configured Hermes profile and gateway. If `hermes gateway
status` reports that the gateway is stopped or unconfigured, the orchestrator
does not fail the media work. It writes `delivery.<phase>.pending.json` beside
the run artifacts with a retry hint.
