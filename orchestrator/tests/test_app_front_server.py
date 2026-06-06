from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orchestrator.app_front import server as app_front_server
from orchestrator.app_front.server import create_app
from orchestrator.app_front.settings import SettingsStore
from orchestrator.cli import build_parser
from orchestrator.disks import DISKUTIL, DiskUnmountError, unmount_disk


INVALID_SETTINGS_FILES = [
    ("{not json", "settings file must contain valid JSON"),
    ("[]", "settings file must contain a JSON object"),
    ("null", "settings file must contain a JSON object"),
    ('{"bind_host": ""}', "bind host must not be empty"),
    ('{"bind_host": "127.0.0.1:8765"}', "bind host must not include a port"),
    ('{"preferred_port": 80}', "preferred port must be between 1024 and 65535"),
    ('{"preferred_port": "abc"}', "preferred port must be an integer"),
    ('{"preferred_port": 9001.5}', "preferred port must be an integer"),
    ('{"preferred_port": "9001"}', "preferred port must be an integer"),
]


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(SettingsStore(tmp_path / "settings.json")))


def test_cli_has_app_command() -> None:
    args = build_parser().parse_args(["app", "--host", "127.0.0.1", "--port", "8750"])

    assert args.command == "app"
    assert args.host == "127.0.0.1"
    assert args.port == 8750


def test_cli_app_command_defaults() -> None:
    args = build_parser().parse_args(["app"])

    assert args.command == "app"
    assert args.host == "127.0.0.1"
    assert args.port == 8750


def test_home_returns_data_handler_app(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Data Handler" in response.text
    assert "(pending)" not in response.text


def test_app_front_exposes_manual_path_project_switcher_and_persistent_errors() -> None:
    html = (app_front_server.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    js = (app_front_server.STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="projectSwitcher"' in html
    assert 'id="appErrorList"' in html
    assert 'data-view="sources"' in html
    assert 'aria-labelledby="projectDialogTitle"' in html
    assert 'role="progressbar"' in html
    assert 'role="alert"' in html
    assert "Type or paste a local folder path" in html
    assert 'document.createElement("input")' in js
    assert "state.errors.load" in js
    assert "setActiveView" in js
    assert "aria-valuenow" in js
    assert '"1 active"' not in js


def test_preview_roll_validation_error_renders_inline_without_throwing() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the app.js validation harness")
    script = r"""
const fs = require("fs");
const vm = require("vm");
const appPath = process.argv[1];
const elements = {};

function makeElement(id) {
  const element = {
    id,
    children: [],
    dataset: {},
    style: {},
    listeners: {},
    textContent: "",
    hidden: false,
    value: "",
    classList: {
      add: function () {},
      remove: function () {},
      toggle: function () {}
    },
    addEventListener: function (type, callback) {
      this.listeners[type] = callback;
    },
    appendChild: function (child) {
      this.children.push(child);
      return child;
    },
    append: function () {
      this.children.push.apply(this.children, Array.prototype.slice.call(arguments));
    },
    replaceChildren: function () {
      this.children = [];
    },
    removeChild: function (child) {
      this.children = this.children.filter(function (item) { return item !== child; });
    },
    get firstChild() {
      return this.children[0] || null;
    },
    querySelector: function (selector) {
      return makeElement(id + selector);
    },
    querySelectorAll: function () {
      return [];
    },
    setAttribute: function () {},
    showModal: function () {},
    close: function () {},
    reset: function () {},
    remove: function () {}
  };
  return element;
}

global.window = {
  setTimeout: setTimeout,
  clearTimeout: clearTimeout
};
global.document = {
  listeners: {},
  addEventListener: function (type, callback) {
    this.listeners[type] = callback;
  },
  getElementById: function (id) {
    if (!elements[id]) {
      elements[id] = makeElement(id);
    }
    return elements[id];
  },
  querySelectorAll: function () {
    return [];
  },
  createElement: function (tag) {
    return makeElement(tag);
  },
  createDocumentFragment: function () {
    return makeElement("fragment");
  }
};
global.Option = function (text, value) {
  return { text: text, value: value };
};
global.FormData = function () {
  return {
    get: function () {
      return "";
    }
  };
};
global.fetch = function (path) {
  const payloads = {
    "/api/app/state": { runtime: {}, settings: {} },
    "/api/projects": { projects: [], runs: [] },
    "/api/sources": { sources: [] },
    "/api/destinations": { destinations: [] },
    "/api/app/disks": { disks: [] }
  };
  return Promise.resolve({
    ok: true,
    text: function () {
      return Promise.resolve(JSON.stringify(payloads[path] || {}));
    }
  });
};

elements.startForm = makeElement("startForm");
elements.startForm.elements = {
  project_id: makeElement("project_id")
};
elements.projectForm = makeElement("projectForm");
elements.settingsForm = makeElement("settingsForm");

vm.runInThisContext(fs.readFileSync(appPath, "utf8"), { filename: appPath });
document.listeners.DOMContentLoaded();

let thrown = "";
try {
  elements.previewRollButton.listeners.click();
} catch (error) {
  thrown = error.message;
}

setTimeout(function () {
  const startError = elements.startError;
  if (thrown) {
    console.error("preview click threw: " + thrown);
    process.exit(1);
  }
  if (startError.textContent !== "Choose project, source, destination, shoot date, and camera before preview.") {
    console.error("unexpected startError text: " + startError.textContent);
    process.exit(1);
  }
  if (startError.hidden !== false) {
    console.error("startError should be visible");
    process.exit(1);
  }
  process.exit(0);
}, 0);
"""

    result = subprocess.run(
        [node, "-e", script, str(app_front_server.STATIC_DIR / "app.js")],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr + result.stdout


def test_project_create_updates_active_project_without_waiting_for_reload() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the app.js project creation harness")
    script = r"""
const fs = require("fs");
const vm = require("vm");
const appPath = process.argv[1];
const elements = {};

function makeElement(id) {
  const element = {
    id,
    children: [],
    dataset: {},
    style: {},
    listeners: {},
    textContent: "",
    hidden: false,
    value: "",
    classList: {
      add: function () {},
      remove: function () {},
      toggle: function () {}
    },
    addEventListener: function (type, callback) {
      this.listeners[type] = callback;
    },
    appendChild: function (child) {
      this.children.push(child);
      return child;
    },
    append: function () {
      this.children.push.apply(this.children, Array.prototype.slice.call(arguments));
    },
    replaceChildren: function () {
      this.children = [];
    },
    removeChild: function (child) {
      this.children = this.children.filter(function (item) { return item !== child; });
    },
    get firstChild() {
      return this.children[0] || null;
    },
    querySelector: function (selector) {
      return makeElement(id + selector);
    },
    querySelectorAll: function () {
      return [];
    },
    setAttribute: function () {},
    showModal: function () {},
    close: function () {},
    reset: function () {},
    remove: function () {}
  };
  return element;
}

global.window = {
  setTimeout: setTimeout,
  clearTimeout: clearTimeout
};
global.document = {
  listeners: {},
  addEventListener: function (type, callback) {
    this.listeners[type] = callback;
  },
  getElementById: function (id) {
    if (!elements[id]) {
      elements[id] = makeElement(id);
    }
    return elements[id];
  },
  querySelectorAll: function () {
    return [];
  },
  createElement: function (tag) {
    return makeElement(tag);
  },
  createDocumentFragment: function () {
    return makeElement("fragment");
  }
};
global.Option = function (text, value) {
  return { text: text, value: value };
};
global.FormData = function () {
  return {
    get: function (name) {
      return name === "name" ? "No Perfect Movie" : "";
    }
  };
};
global.fetch = function (path, options) {
  if (path === "/api/projects" && options && options.method === "POST") {
    return Promise.resolve({
      ok: true,
      text: function () {
        return Promise.resolve(JSON.stringify({
          project: {
            id: "project-1",
            name: "No Perfect Movie",
            source_paths: ["/sources/CARD_A"],
            replica_roots: ["/replicas/path1", "/replicas/path2"]
          }
        }));
      }
    });
  }
  return new Promise(function () {});
};

elements.startForm = makeElement("startForm");
elements.startForm.elements = {
  project_id: makeElement("project_id")
};
elements.projectForm = makeElement("projectForm");
elements.settingsForm = makeElement("settingsForm");

vm.runInThisContext(fs.readFileSync(appPath, "utf8"), { filename: appPath });
document.listeners.DOMContentLoaded();

elements.projectSourcePaths.querySelectorAll = function () {
  return [{ value: "/sources/CARD_A" }];
};
elements.projectReplicaRoots.querySelectorAll = function () {
  return [{ value: "/replicas/path1" }, { value: "/replicas/path2" }];
};
elements.projectForm.listeners.submit({ preventDefault: function () {} });

setTimeout(function () {
  if (elements.projectsMeta.textContent !== "1") {
    console.error("project count did not update: " + elements.projectsMeta.textContent);
    process.exit(1);
  }
  if (elements.activeProject.textContent !== "No Perfect Movie") {
    console.error("active project did not update: " + elements.activeProject.textContent);
    process.exit(1);
  }
  if (elements.activeSource.textContent !== "/sources/CARD_A") {
    console.error("active source did not update: " + elements.activeSource.textContent);
    process.exit(1);
  }
  if (elements.activeReplicas.textContent !== "/replicas/path1 | /replicas/path2") {
    console.error("active replicas did not update: " + elements.activeReplicas.textContent);
    process.exit(1);
  }
  process.exit(0);
}, 0);
"""

    result = subprocess.run(
        [node, "-e", script, str(app_front_server.STATIC_DIR / "app.js")],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr + result.stdout


def test_app_js_metrics_and_reports_show_files_replicas_manifest_and_path2() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the app.js metrics harness")
    script = r"""
const fs = require("fs");
const vm = require("vm");
const appPath = process.argv[1];
const elements = {};

function makeElement(id) {
  const element = {
    id,
    children: [],
    dataset: {},
    style: {},
    listeners: {},
    textContent: "",
    hidden: false,
    value: "",
    classList: {
      add: function () {},
      remove: function () {},
      toggle: function () {}
    },
    addEventListener: function (type, callback) {
      this.listeners[type] = callback;
    },
    appendChild: function (child) {
      this.children.push(child);
      return child;
    },
    append: function () {
      this.children.push.apply(this.children, Array.prototype.slice.call(arguments));
    },
    replaceChildren: function () {
      this.children = [];
    },
    removeChild: function (child) {
      this.children = this.children.filter(function (item) { return item !== child; });
    },
    get firstChild() {
      return this.children[0] || null;
    },
    querySelector: function (selector) {
      return makeElement(id + selector);
    },
    querySelectorAll: function () {
      return [];
    },
    setAttribute: function () {},
    showModal: function () {},
    close: function () {},
    reset: function () {},
    remove: function () {}
  };
  return element;
}

global.window = {
  setTimeout: setTimeout,
  clearTimeout: clearTimeout
};
global.document = {
  listeners: {},
  addEventListener: function (type, callback) {
    this.listeners[type] = callback;
  },
  getElementById: function (id) {
    if (!elements[id]) {
      elements[id] = makeElement(id);
    }
    return elements[id];
  },
  querySelectorAll: function () {
    return [];
  },
  createElement: function (tag) {
    return makeElement(tag);
  },
  createDocumentFragment: function () {
    return makeElement("fragment");
  }
};
global.Option = function (text, value) {
  return { text: text, value: value };
};
global.FormData = function () {
  return {
    get: function () {
      return "";
    }
  };
};

const project = {
  id: "project-1",
  name: "No Perfect Movie",
  source_paths: ["/sources/CARD_A"],
  replica_roots: ["/replicas/path1", "/replicas/path2"]
};
const run = {
  project_id: "project-1",
  run_id: "run-1",
  shoot_date: "260601",
  camera_unit: "A-cam",
  roll: "R#1",
  created_at: "2026-06-01T00:00:00Z"
};
const artifacts = [
  { name: "checksum pdf", kind: "checksum_pdf", url: "/artifacts/run-1/checksum.pdf" },
  { name: "manifest json", kind: "manifest_json", url: "/artifacts/run-1/manifest.json" },
  { name: "datahelper-path1 pdf", kind: "pdf", url: "/artifacts/run-1/datahelper-path1.pdf" },
  { name: "datahelper-path1 json", kind: "json", url: "/artifacts/run-1/datahelper-path1.json" },
  { name: "datahelper-path2 pdf", kind: "pdf", url: "/artifacts/run-1/datahelper-path2.pdf" },
  { name: "datahelper-path2 json", kind: "json", url: "/artifacts/run-1/datahelper-path2.json" }
];

global.fetch = function (path) {
  const payloads = {
    "/api/app/state": { runtime: {}, settings: {} },
    "/api/projects": { projects: [project], runs: [run] },
    "/api/sources": { sources: [] },
    "/api/destinations": { destinations: [] },
    "/api/app/disks": { disks: [] },
    "/api/runs/run-1": {
      run: run,
      project: project,
      progress: {
        stage: "done",
        status: "completed",
        file_count: 4,
        replica_count: 2,
        report_count: 6,
        percent: 100,
        program: "DataHelper (Handler)",
        phase_label: "DataHelper reports complete",
        phase_detail: "2 of 2 replica report jobs complete; 6 report artifacts available.",
        activity_state: "complete",
        last_progress_at: "2026-06-01T00:00:00+00:00"
      },
      artifacts: artifacts
    }
  };
  return Promise.resolve({
    ok: true,
    text: function () {
      return Promise.resolve(JSON.stringify(payloads[path] || {}));
    }
  });
};

elements.startForm = makeElement("startForm");
elements.startForm.elements = {
  project_id: makeElement("project_id")
};
elements.projectForm = makeElement("projectForm");
elements.settingsForm = makeElement("settingsForm");

vm.runInThisContext(fs.readFileSync(appPath, "utf8"), { filename: appPath });
document.listeners.DOMContentLoaded();

setTimeout(function () {
  if (elements.copiedMetric.textContent !== "4") {
    console.error("file metric should be 4, got " + elements.copiedMetric.textContent);
    process.exit(1);
  }
  if (elements.verifiedMetric.textContent !== "2") {
    console.error("replica metric should be 2, got " + elements.verifiedMetric.textContent);
    process.exit(1);
  }
  if (elements.reportsMetric.textContent !== "6") {
    console.error("report metric should be 6, got " + elements.reportsMetric.textContent);
    process.exit(1);
  }
  if (elements.overallTitle.textContent !== "DataHelper reports complete") {
    console.error("overall title did not show phase: " + elements.overallTitle.textContent);
    process.exit(1);
  }
  if (elements.overallSubtitle.textContent.indexOf("DataHelper (Handler)") === -1 ||
      elements.overallSubtitle.textContent.indexOf("2 of 2 replica report jobs complete") === -1 ||
      elements.overallSubtitle.textContent.indexOf("Run ID: run-1") === -1) {
    console.error("overall subtitle did not show program/detail/run id: " + elements.overallSubtitle.textContent);
    process.exit(1);
  }
  if (elements.activeClipCount.textContent !== "Complete") {
    console.error("activity chip should show complete, got " + elements.activeClipCount.textContent);
    process.exit(1);
  }
  const checksumText = elements.checksumReportList.children.map(function (item) {
    return item.children.map(function (child) { return child.textContent; }).join(" ");
  }).join(" | ");
  const clipText = elements.clipReportList.children.map(function (item) {
    return item.children.map(function (child) { return child.textContent; }).join(" ");
  }).join(" | ");
  if (checksumText.indexOf("manifest json") === -1) {
    console.error("manifest was not rendered: " + checksumText);
    process.exit(1);
  }
  if (clipText.indexOf("datahelper-path2 pdf") === -1 || clipText.indexOf("datahelper-path2 json") === -1) {
    console.error("path2 reports were not rendered: " + clipText);
    process.exit(1);
  }
  process.exit(0);
}, 20);
"""

    result = subprocess.run(
        [node, "-e", script, str(app_front_server.STATIC_DIR / "app.js")],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr + result.stdout


def test_app_js_failed_run_is_not_rendered_as_recorded_completion() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the app.js completion harness")
    script = r"""
const fs = require("fs");
const vm = require("vm");
const appPath = process.argv[1];
const elements = {};

function makeElement(id) {
  const queries = {};
  const element = {
    id,
    children: [],
    dataset: {},
    style: {},
    listeners: {},
    textContent: "",
    hidden: false,
    value: "",
    classList: {
      add: function () {},
      remove: function () {},
      toggle: function () {}
    },
    addEventListener: function (type, callback) {
      this.listeners[type] = callback;
    },
    appendChild: function (child) {
      this.children.push(child);
      return child;
    },
    append: function () {
      this.children.push.apply(this.children, Array.prototype.slice.call(arguments));
    },
    replaceChildren: function () {
      this.children = [];
    },
    removeChild: function (child) {
      this.children = this.children.filter(function (item) { return item !== child; });
    },
    get firstChild() {
      return this.children[0] || null;
    },
    querySelector: function (selector) {
      if (!queries[selector]) {
        queries[selector] = makeElement(id + selector);
      }
      return queries[selector];
    },
    querySelectorAll: function () {
      return [];
    },
    setAttribute: function () {},
    showModal: function () {},
    close: function () {},
    reset: function () {},
    remove: function () {}
  };
  return element;
}

global.window = {
  setTimeout: setTimeout,
  clearTimeout: clearTimeout
};
global.document = {
  listeners: {},
  addEventListener: function (type, callback) {
    this.listeners[type] = callback;
  },
  getElementById: function (id) {
    if (!elements[id]) {
      elements[id] = makeElement(id);
    }
    return elements[id];
  },
  querySelectorAll: function () {
    return [];
  },
  createElement: function (tag) {
    return makeElement(tag);
  },
  createDocumentFragment: function () {
    return makeElement("fragment");
  }
};
global.Option = function (text, value) {
  return { text: text, value: value };
};
global.FormData = function () {
  return {
    get: function () {
      return "";
    }
  };
};

const project = {
  id: "project-1",
  name: "No Perfect Movie",
  source_paths: ["/sources/CARD_A"],
  replica_roots: ["/replicas/path1", "/replicas/path2"]
};
const completedRun = {
  project_id: "project-1",
  run_id: "run-completed",
  shoot_date: "260601",
  camera_unit: "A-cam",
  roll: "R#1",
  status: "completed",
  created_at: "2026-06-01T00:00:00Z"
};
const failedRun = {
  project_id: "project-1",
  run_id: "run-failed",
  shoot_date: "260602",
  camera_unit: "A-cam",
  roll: "R#2",
  status: "failed",
  created_at: "2026-06-02T00:00:00Z"
};

global.fetch = function (path) {
  const payloads = {
    "/api/app/state": { runtime: {}, settings: {} },
    "/api/projects": { projects: [project], runs: [failedRun, completedRun] },
    "/api/sources": { sources: [] },
    "/api/destinations": { destinations: [] },
    "/api/app/disks": { disks: [] },
    "/api/runs/run-failed": {
      run: failedRun,
      project: project,
      progress: { stage: "datahelper", status: "failed" },
      artifacts: []
    }
  };
  return Promise.resolve({
    ok: true,
    text: function () {
      return Promise.resolve(JSON.stringify(payloads[path] || {}));
    }
  });
};

elements.startForm = makeElement("startForm");
elements.startForm.elements = {
  project_id: makeElement("project_id")
};
elements.projectForm = makeElement("projectForm");
elements.settingsForm = makeElement("settingsForm");

vm.runInThisContext(fs.readFileSync(appPath, "utf8"), { filename: appPath });
document.listeners.DOMContentLoaded();

setTimeout(function () {
  const rows = elements.completionList.children.map(function (item) {
    return {
      copy: item.querySelector(".completion-copy").textContent,
      meta: item.querySelector(".completion-meta").textContent
    };
  });
  const failed = rows.find(function (row) { return row.copy.indexOf("260602") !== -1; });
  const completed = rows.find(function (row) { return row.copy.indexOf("260601") !== -1; });
  if (failed && failed.meta === "recorded") {
    console.error("failed run should not render as recorded: " + JSON.stringify(rows));
    process.exit(1);
  }
  if (!completed || completed.meta !== "recorded") {
    console.error("completed run should render as recorded: " + JSON.stringify(rows));
    process.exit(1);
  }
  process.exit(0);
}, 20);
"""

    result = subprocess.run(
        [node, "-e", script, str(app_front_server.STATIC_DIR / "app.js")],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr + result.stdout


def test_project_and_source_apis_are_available_in_app_front(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    runs_root = tmp_path / "runs"
    source = source_root / "CARD_A"
    source.mkdir(parents=True)
    path1, path2 = tmp_path / "path1", tmp_path / "path2"
    path1.mkdir()
    path2.mkdir()
    app = create_app(
        settings_store=SettingsStore(tmp_path / "settings.json"),
        registry_path=tmp_path / "registry.json",
        source_roots=(source_root,),
        runs_root=runs_root,
    )
    client = TestClient(app)

    source_response = client.get("/api/sources")
    project_response = client.post(
        "/api/projects",
        json={
            "name": "No Perfect Movie",
            "source_paths": [str(source)],
            "replica_roots": [str(path1), str(path2)],
        },
    )
    projects_response = client.get("/api/projects")

    assert source_response.status_code == 200
    assert source_response.json()["sources"][0]["path"] == str(source)
    assert project_response.status_code == 200
    assert project_response.json()["project"]["name"] == "No Perfect Movie"
    assert project_response.json()["project"]["source_paths"] == [str(source)]
    assert projects_response.json()["projects"][0]["name"] == "No Perfect Movie"


def test_source_and_destination_candidates_can_use_separate_roots(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    destination_root = tmp_path / "destinations"
    source = source_root / "CARD_A"
    destination = destination_root / "RAID_A"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    app = create_app(
        settings_store=SettingsStore(tmp_path / "settings.json"),
        registry_path=tmp_path / "registry.json",
        source_roots=(source_root,),
        destination_roots=(destination_root,),
        runs_root=tmp_path / "runs",
    )
    client = TestClient(app)

    sources_response = client.get("/api/sources")
    destinations_response = client.get("/api/destinations")

    assert sources_response.status_code == 200
    assert destinations_response.status_code == 200
    assert [item["path"] for item in sources_response.json()["sources"]] == [str(source)]
    assert [item["path"] for item in destinations_response.json()["destinations"]] == [
        str(destination)
    ]


def test_app_front_run_create_uses_real_orchestrator_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    runs_root = tmp_path / "runs"
    source = source_root / "CARD_A"
    source.mkdir(parents=True)
    runs_root.mkdir()
    path1, path2 = tmp_path / "path1", tmp_path / "path2"
    path1.mkdir()
    path2.mkdir()
    app = create_app(
        settings_store=SettingsStore(tmp_path / "settings.json"),
        registry_path=tmp_path / "registry.json",
        source_roots=(source_root,),
        runs_root=runs_root,
    )
    client = TestClient(app)
    project = client.post(
        "/api/projects",
        json={"name": "No Perfect Movie", "replica_roots": [str(path1), str(path2)]},
    ).json()["project"]
    starts: list[dict[str, object]] = []
    monkeypatch.setattr("orchestrator.app_front.server.start_run", lambda **kwargs: starts.append(kwargs) or "run-test")

    response = client.post(
        "/api/runs",
        json={
            "project_id": project["id"],
            "shoot_date": "260528",
            "camera_unit": "A-cam",
            "source_paths": [str(source)],
            "replica_roots": [str(path1), str(path2)],
        },
    )

    assert response.status_code == 200
    assert response.json()["roll"] == "R#1"
    assert starts[0]["project_name"] == "No Perfect Movie"
    assert starts[0]["source_paths"] == (source,)
    assert starts[0]["replica_paths"] == (path1, path2)


def test_app_front_run_create_writes_real_run_artifacts_in_isolated_pipeline_root(
    tmp_path: Path,
) -> None:
    pipeline_root = tmp_path / "pipeline"
    source_root = tmp_path / "sources"
    destination_root = tmp_path / "destinations"
    script = r"""
import json
import sys
from pathlib import Path

import orchestrator.cli as cli
from fastapi.testclient import TestClient
from orchestrator import paths
from orchestrator.app_front.settings import SettingsStore
from orchestrator.processes import spawn_python_module as real_spawn_python_module


def spawn_boundary(run_id: str, module: str, *args: str) -> int:
    if module != "orchestrator.datamanager_worker":
        raise RuntimeError(f"unexpected module: {module}")
    return real_spawn_python_module(run_id, "orchestrator.web.progress")


cli.spawn_python_module = spawn_boundary

from orchestrator.app_front.server import create_app

pipeline_root = Path(sys.argv[1])
source_root = Path(sys.argv[2])
destination_root = Path(sys.argv[3])
source_a = source_root / "CARD_A"
source_b = source_root / "CARD_B"
dest_a = destination_root / "RAID_A"
dest_b = destination_root / "RAID_B"
for path in (source_a, source_b, dest_a, dest_b):
    path.mkdir(parents=True, exist_ok=True)

app = create_app(
    settings_store=SettingsStore(pipeline_root / "settings.json"),
    registry_path=pipeline_root / "registry.json",
    source_roots=(source_root,),
    destination_roots=(destination_root,),
    runs_root=paths.RUNS_ROOT,
)
client = TestClient(app)
project_response = client.post(
    "/api/projects",
    json={
        "name": "No Perfect Movie",
        "source_paths": [str(source_a), str(source_b)],
        "replica_roots": [str(dest_a), str(dest_b)],
    },
)
assert project_response.status_code == 200, project_response.text
project = project_response.json()["project"]
run_response = client.post(
    "/api/runs",
    json={
        "project_id": project["id"],
        "shoot_date": "260528",
        "camera_unit": "A-cam",
        "source_paths": [str(source_a), str(source_b)],
        "replica_roots": [str(dest_a), str(dest_b)],
    },
)
assert run_response.status_code == 200, run_response.text
run_id = run_response.json()["run_id"]
run_dir = paths.RUNS_ROOT / run_id
request_path = run_dir / "request.json"
state_path = run_dir / "state.json"
stdout_log = paths.LOG_ROOT / f"{run_id}.progress.out.log"
stderr_log = paths.LOG_ROOT / f"{run_id}.progress.err.log"
request_payload = json.loads(request_path.read_text(encoding="utf-8"))
state_payload = json.loads(state_path.read_text(encoding="utf-8"))
registry_payload = json.loads((pipeline_root / "registry.json").read_text(encoding="utf-8"))
assert request_payload["source_paths"] == [str(source_a.resolve()), str(source_b.resolve())]
assert request_payload["replica_roots"] == [str(dest_a.resolve()), str(dest_b.resolve())]
assert state_payload["stage"] == "datamanager"
assert state_payload["status"] == "spawned"
assert stdout_log.is_file()
assert stderr_log.is_file()
assert registry_payload["runs"][0]["status"] == "started"
print(json.dumps({
    "run_id": run_id,
    "request_path": str(request_path),
    "state_path": str(state_path),
    "stdout_log": str(stdout_log),
    "stderr_log": str(stderr_log),
}))
"""

    env = os.environ.copy()
    env["DATA_HANDLER_PIPELINE_ROOT"] = str(pipeline_root)
    result = subprocess.run(
        [sys.executable, "-c", script, str(pipeline_root), str(source_root), str(destination_root)],
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
        env=env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert Path(payload["request_path"]).is_file()
    assert Path(payload["state_path"]).is_file()
    assert Path(payload["stdout_log"]).is_file()
    assert Path(payload["stderr_log"]).is_file()


def test_app_front_run_start_failure_marks_registry_run_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "sources"
    source = source_root / "CARD_A"
    source.mkdir(parents=True)
    path1, path2 = tmp_path / "path1", tmp_path / "path2"
    path1.mkdir()
    path2.mkdir()
    app = create_app(
        settings_store=SettingsStore(tmp_path / "settings.json"),
        registry_path=tmp_path / "registry.json",
        source_roots=(source_root,),
        runs_root=tmp_path / "runs",
    )
    client = TestClient(app)
    project = client.post(
        "/api/projects",
        json={"name": "No Perfect Movie", "replica_roots": [str(path1), str(path2)]},
    ).json()["project"]

    def fail_start(**_kwargs: object) -> str:
        raise RuntimeError("spawn failed")

    monkeypatch.setattr("orchestrator.app_front.server.start_run", fail_start)

    response = client.post(
        "/api/runs",
        json={
            "project_id": project["id"],
            "shoot_date": "260528",
            "camera_unit": "A-cam",
            "source_paths": [str(source)],
            "replica_roots": [str(path1), str(path2)],
        },
    )

    assert response.status_code == 500
    run = client.get("/api/projects").json()["runs"][0]
    assert run["status"] == "failed"
    assert "spawn failed" in run["error"]


def test_run_detail_syncs_completed_progress_to_registry_status(tmp_path: Path) -> None:
    from orchestrator.jsonio import write_json
    from orchestrator.web.registry import ConsoleRegistry

    source_root = tmp_path / "sources"
    source = source_root / "CARD_A"
    source.mkdir(parents=True)
    path1, path2 = tmp_path / "path1", tmp_path / "path2"
    path1.mkdir()
    path2.mkdir()
    registry_path = tmp_path / "registry.json"
    runs_root = tmp_path / "runs"
    app = create_app(
        settings_store=SettingsStore(tmp_path / "settings.json"),
        registry_path=registry_path,
        source_roots=(source_root,),
        runs_root=runs_root,
    )
    client = TestClient(app)
    project = client.post(
        "/api/projects",
        json={"name": "No Perfect Movie", "replica_roots": [str(path1), str(path2)]},
    ).json()["project"]
    registry = ConsoleRegistry(registry_path)
    registry.reserve_run(
        project_id=project["id"],
        shoot_date="260528",
        camera_unit="A-cam",
        run_id="run-finished",
        source_path=str(source),
    )
    registry.mark_run_started("run-finished")
    run_dir = runs_root / "run-finished"
    run_dir.mkdir(parents=True)
    write_json(
        run_dir / "state.json",
        {"run_id": "run-finished", "stage": "done", "status": "completed"},
    )

    response = client.get("/api/runs/run-finished")

    assert response.status_code == 200
    assert response.json()["run"]["status"] == "completed"
    assert ConsoleRegistry(registry_path).load()["runs"][0]["status"] == "completed"


def test_run_detail_syncs_completed_datahelper_progress_to_registry_status(tmp_path: Path) -> None:
    from orchestrator.jsonio import write_json
    from orchestrator.web.registry import ConsoleRegistry

    source_root = tmp_path / "sources"
    source = source_root / "CARD_A"
    source.mkdir(parents=True)
    path1, path2 = tmp_path / "path1", tmp_path / "path2"
    path1.mkdir()
    path2.mkdir()
    registry_path = tmp_path / "registry.json"
    runs_root = tmp_path / "runs"
    app = create_app(
        settings_store=SettingsStore(tmp_path / "settings.json"),
        registry_path=registry_path,
        source_roots=(source_root,),
        runs_root=runs_root,
    )
    client = TestClient(app)
    project = client.post(
        "/api/projects",
        json={"name": "No Perfect Movie", "replica_roots": [str(path1), str(path2)]},
    ).json()["project"]
    registry = ConsoleRegistry(registry_path)
    registry.reserve_run(
        project_id=project["id"],
        shoot_date="260528",
        camera_unit="A-cam",
        run_id="run-datahelper-finished",
        source_path=str(source),
    )
    registry.mark_run_started("run-datahelper-finished")
    run_dir = runs_root / "run-datahelper-finished"
    run_dir.mkdir(parents=True)
    write_json(
        run_dir / "progress.json",
        {
            "run_id": "run-datahelper-finished",
            "stage": "datahelper",
            "status": "completed",
            "current": 2,
            "total": 2,
        },
    )

    response = client.get("/api/runs/run-datahelper-finished")

    assert response.status_code == 200
    assert response.json()["progress"]["status"] == "completed"
    assert response.json()["run"]["status"] == "completed"
    assert ConsoleRegistry(registry_path).load()["runs"][0]["status"] == "completed"


def test_settings_round_trip(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.put(
        "/api/app/settings",
        json={"bind_host": "100.64.0.12", "preferred_port": 9001},
    )

    assert response.status_code == 200
    assert response.json()["settings"] == {
        "bind_host": "100.64.0.12",
        "preferred_port": 9001,
    }
    assert client.get("/api/app/settings").json()["settings"]["bind_host"] == "100.64.0.12"
    assert client.get("/api/app/settings").json()["settings"]["preferred_port"] == 9001


def test_disks_returns_mounted_volume_usage(tmp_path: Path) -> None:
    mount_root = tmp_path / "Volumes"
    mount_root.mkdir()
    (mount_root / "DIT_CARD_A").mkdir()
    (mount_root / "not-a-volume.txt").write_text("skip", encoding="utf-8")
    client = TestClient(create_app(SettingsStore(tmp_path / "settings.json"), disk_root=mount_root))

    response = client.get("/api/app/disks")

    assert response.status_code == 200
    assert [disk["name"] for disk in response.json()["disks"]] == ["DIT_CARD_A"]
    disk = response.json()["disks"][0]
    assert disk["path"].endswith("DIT_CARD_A")
    assert disk["total_bytes"] > 0
    assert disk["free_bytes"] >= 0
    assert 0 <= disk["used_percent"] <= 100
    assert disk["disk_type"] == "internal"


def test_disks_excludes_hidden_volumes_and_prefers_external_disks(tmp_path: Path) -> None:
    mount_root = tmp_path / "Volumes"
    mount_root.mkdir()
    for name in [".timemachine", "Internal_A", "External_A", "External_B", "External_C"]:
        (mount_root / name).mkdir()

    def classify(path: Path) -> str:
        return "external" if path.name.startswith("External") or path.name.startswith(".") else "internal"

    client = TestClient(
        create_app(
            SettingsStore(tmp_path / "settings.json"),
            disk_root=mount_root,
            disk_classifier=classify,
        )
    )

    response = client.get("/api/app/disks")

    assert response.status_code == 200
    assert [disk["name"] for disk in response.json()["disks"]] == ["External_A", "External_B", "External_C"]
    assert {disk["disk_type"] for disk in response.json()["disks"]} == {"external"}


def test_disks_fills_with_internal_disks_when_external_count_is_below_three(tmp_path: Path) -> None:
    mount_root = tmp_path / "Volumes"
    mount_root.mkdir()
    for name in ["External_A", "Internal_A", "Internal_B", "Internal_C"]:
        (mount_root / name).mkdir()

    def classify(path: Path) -> str:
        return "external" if path.name.startswith("External") else "internal"

    client = TestClient(
        create_app(
            SettingsStore(tmp_path / "settings.json"),
            disk_root=mount_root,
            disk_classifier=classify,
        )
    )

    response = client.get("/api/app/disks")

    assert response.status_code == 200
    assert [disk["name"] for disk in response.json()["disks"]] == ["External_A", "Internal_A", "Internal_B"]
    assert [disk["disk_type"] for disk in response.json()["disks"]] == ["external", "internal", "internal"]


def test_disks_returns_empty_list_when_mount_root_is_missing(tmp_path: Path) -> None:
    client = TestClient(create_app(SettingsStore(tmp_path / "settings.json"), disk_root=tmp_path / "missing"))

    response = client.get("/api/app/disks")

    assert response.status_code == 200
    assert response.json() == {"disks": []}


def test_unmount_disk_runs_diskutil_for_external_volume(tmp_path: Path) -> None:
    mount_root = tmp_path / "Volumes"
    volume = mount_root / "DIT_RAID"
    volume.mkdir(parents=True)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = unmount_disk(
        volume,
        mount_root=mount_root,
        disk_classifier=lambda _path: "external",
        runner=runner,
    )

    assert result == {"path": str(volume), "status": "ejected"}
    assert calls == [
        (
            [str(DISKUTIL), "eject", str(volume)],
            {"check": True, "capture_output": True, "text": True, "timeout": 15},
        )
    ]


def test_unmount_disk_rejects_internal_or_outside_volume(tmp_path: Path) -> None:
    mount_root = tmp_path / "Volumes"
    internal = mount_root / "Macintosh HD"
    outside = tmp_path / "outside"
    internal.mkdir(parents=True)
    outside.mkdir()

    with pytest.raises(DiskUnmountError, match="only external"):
        unmount_disk(internal, mount_root=mount_root, disk_classifier=lambda _path: "internal")
    with pytest.raises(DiskUnmountError, match="under"):
        unmount_disk(outside, mount_root=mount_root, disk_classifier=lambda _path: "external")


def test_app_front_unmount_endpoint_returns_refreshed_disks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mount_root = tmp_path / "Volumes"
    volume = mount_root / "DIT_RAID"
    volume.mkdir(parents=True)
    calls: list[tuple[str, Path]] = []

    def fake_unmount(path: str, *, mount_root: Path, disk_classifier: object) -> dict[str, str]:
        calls.append((path, mount_root))
        volume.rmdir()
        return {"path": path, "status": "ejected"}

    monkeypatch.setattr("orchestrator.app_front.server.unmount_disk", fake_unmount)
    client = TestClient(create_app(SettingsStore(tmp_path / "settings.json"), disk_root=mount_root))

    response = client.post("/api/app/disks/unmount", json={"path": str(volume)})

    assert response.status_code == 200
    assert response.json()["status"] == "ejected"
    assert response.json()["disks"] == []
    assert calls == [(str(volume), mount_root)]


def test_rejects_invalid_port(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.put(
        "/api/app/settings",
        json={"bind_host": "127.0.0.1", "preferred_port": 80},
    )

    assert response.status_code == 400


def test_state_returns_runtime_payload(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            SettingsStore(tmp_path / "settings.json"),
            registry_path=tmp_path / "registry.json",
            runs_root=tmp_path / "runs",
        )
    )

    response = client.get("/api/app/state")

    assert response.status_code == 200
    assert response.json()["server"]["state"] == "running"
    assert response.json()["runtime"]["status"] == "ok"
    assert response.json()["runtime"]["registry_path"] == str(tmp_path / "registry.json")
    assert response.json()["runtime"]["runs_root"] == str(tmp_path / "runs")
    assert response.json()["runtime"]["pid"] > 0
    assert all(check["status"] == "ok" for check in response.json()["runtime"]["checks"])


def test_state_reports_runtime_error_when_registry_is_invalid(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text("[]", encoding="utf-8")
    client = TestClient(
        create_app(
            SettingsStore(tmp_path / "settings.json"),
            registry_path=registry_path,
            runs_root=tmp_path / "runs",
        )
    )

    response = client.get("/api/app/state")

    assert response.status_code == 200
    assert response.json()["runtime"]["status"] == "error"
    assert "registry file must contain a JSON object" in response.json()["runtime"]["errors"][0]


def test_state_reports_runtime_error_when_runs_root_is_unavailable(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.write_text("not a directory", encoding="utf-8")
    client = TestClient(
        create_app(
            SettingsStore(tmp_path / "settings.json"),
            registry_path=tmp_path / "registry.json",
            runs_root=runs_root,
        )
    )

    response = client.get("/api/app/state")

    assert response.status_code == 200
    assert response.json()["runtime"]["status"] == "error"
    assert any("runs_root unavailable" in error for error in response.json()["runtime"]["errors"])


def test_state_returns_default_settings_and_error_when_persisted_settings_invalid(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{"preferred_port": 80}', encoding="utf-8")
    client = TestClient(create_app(SettingsStore(settings_path)))

    response = client.get("/api/app/state")

    assert response.status_code == 200
    assert response.json()["settings"] == {
        "bind_host": "127.0.0.1",
        "preferred_port": 8765,
    }
    assert "preferred port must be between 1024 and 65535" in response.json()["settings_error"]
    assert response.json()["server"]["state"] == "running"


def test_state_returns_default_settings_and_error_when_settings_shape_invalid(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("[]", encoding="utf-8")
    client = TestClient(create_app(SettingsStore(settings_path)))

    response = client.get("/api/app/state")

    assert response.status_code == 200
    assert response.json()["settings"] == {
        "bind_host": "127.0.0.1",
        "preferred_port": 8765,
    }
    assert "settings file must contain a JSON object" in response.json()["settings_error"]


def test_settings_returns_default_settings_and_error_when_persisted_settings_invalid(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{"preferred_port": 80}', encoding="utf-8")
    client = TestClient(create_app(SettingsStore(settings_path)))

    response = client.get("/api/app/settings")

    assert response.status_code == 200
    assert response.json()["settings"] == {
        "bind_host": "127.0.0.1",
        "preferred_port": 8765,
    }
    assert "preferred port must be between 1024 and 65535" in response.json()["settings_error"]


def test_valid_settings_update_clears_invalid_persisted_state(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{"preferred_port": 80}', encoding="utf-8")
    client = TestClient(create_app(SettingsStore(settings_path)))

    response = client.put(
        "/api/app/settings",
        json={"bind_host": "100.64.0.12", "preferred_port": 9001},
    )
    settings_response = client.get("/api/app/settings")

    assert response.status_code == 200
    assert settings_response.status_code == 200
    assert settings_response.json() == {
        "settings": {
            "bind_host": "100.64.0.12",
            "preferred_port": 9001,
        }
    }


@pytest.mark.parametrize(("content", "message"), INVALID_SETTINGS_FILES)
def test_api_can_report_and_repair_invalid_existing_settings(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(content, encoding="utf-8")
    client = TestClient(create_app(SettingsStore(settings_path)))

    state_response = client.get("/api/app/state")
    settings_response = client.get("/api/app/settings")
    repair_response = client.put(
        "/api/app/settings",
        json={"bind_host": "100.64.0.12", "preferred_port": 9001},
    )
    repaired_settings_response = client.get("/api/app/settings")

    assert state_response.status_code == 200
    assert state_response.json()["settings"] == {
        "bind_host": "127.0.0.1",
        "preferred_port": 8765,
    }
    assert message in state_response.json()["settings_error"]
    assert state_response.json()["server"]["state"] == "running"
    assert state_response.json()["runtime"]["status"] == "error"

    assert settings_response.status_code == 200
    assert settings_response.json()["settings"] == {
        "bind_host": "127.0.0.1",
        "preferred_port": 8765,
    }
    assert message in settings_response.json()["settings_error"]

    assert repair_response.status_code == 200
    assert repaired_settings_response.status_code == 200
    assert repaired_settings_response.json() == {
        "settings": {
            "bind_host": "100.64.0.12",
            "preferred_port": 9001,
        }
    }
