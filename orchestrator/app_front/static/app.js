(function () {
  "use strict";

  var state = {
    runtime: null,
    settings: null,
    projects: [],
    runs: [],
    sources: [],
    destinations: [],
    disks: [],
    diskError: null,
    unmountingPath: null,
    activeView: "projects",
    selectedProjectId: null,
    selectedRunId: null,
    selectedRunDetail: null,
    progress: null,
    artifacts: [],
    latestPreview: null,
    loading: false,
    errors: {
      load: "",
      poll: "",
      settings: ""
    }
  };

  var progressPollTimer = null;
  var PROGRESS_POLL_MS = 3000;
  var elements = {};

  document.addEventListener("DOMContentLoaded", function () {
    elements = {
      runtimeState: byId("runtimeState"),
      projectsNav: byId("projectsNav"),
      sourcesNav: byId("sourcesNav"),
      runsNav: byId("runsNav"),
      runtimeNav: byId("runtimeNav"),
      sidebarStatusDot: byId("sidebarStatusDot"),
      sidebarServerState: byId("sidebarServerState"),
      projectsMeta: byId("projectsMeta"),
      sourcesMeta: byId("sourcesMeta"),
      runsMeta: byId("runsMeta"),
      diskSummary: byId("diskSummary"),
      diskList: byId("diskList"),
      importSourceButton: byId("importSourceButton"),
      startReplicationButton: byId("startReplicationButton"),
      appErrorList: byId("appErrorList"),
      reviewProjectButton: byId("reviewProjectButton"),
      viewRunsButton: byId("viewRunsButton"),
      footerSettingsButton: byId("footerSettingsButton"),
      activeSource: byId("activeSource"),
      activeReplicas: byId("activeReplicas"),
      activeProject: byId("activeProject"),
      projectSwitcher: byId("projectSwitcher"),
      recentRunsList: byId("recentRunsList"),
      overallState: byId("overallState"),
      overallTitle: byId("overallTitle"),
      overallSubtitle: byId("overallSubtitle"),
      overallPercent: byId("overallPercent"),
      overallProgressbar: byId("overallProgressbar"),
      overallBar: byId("overallBar"),
      copiedMetric: byId("copiedMetric"),
      verifiedMetric: byId("verifiedMetric"),
      reportsMetric: byId("reportsMetric"),
      checksumReportList: byId("checksumReportList"),
      clipReportList: byId("clipReportList"),
      backupState: byId("backupState"),
      activeClipCount: byId("activeClipCount"),
      clipProgressTitle: byId("clipProgressTitle"),
      clipProgressSubtitle: byId("clipProgressSubtitle"),
      clipProgressPercent: byId("clipProgressPercent"),
      clipProgressbar: byId("clipProgressbar"),
      clipProgressBar: byId("clipProgressBar"),
      completionList: byId("completionList"),
      projectDialog: byId("projectDialog"),
      projectForm: byId("projectForm"),
      projectSourcePaths: byId("projectSourcePaths"),
      projectReplicaRoots: byId("projectReplicaRoots"),
      addProjectSource: byId("addProjectSource"),
      addProjectDestination: byId("addProjectDestination"),
      projectError: byId("projectError"),
      startDialog: byId("startDialog"),
      startForm: byId("startForm"),
      startSourcePaths: byId("startSourcePaths"),
      startReplicaRoots: byId("startReplicaRoots"),
      addStartSource: byId("addStartSource"),
      addStartDestination: byId("addStartDestination"),
      previewRollButton: byId("previewRollButton"),
      startSummary: byId("startSummary"),
      startError: byId("startError"),
      settingsDialog: byId("settingsDialog"),
      settingsForm: byId("settingsForm"),
      bindHostInput: byId("bindHostInput"),
      preferredPortInput: byId("preferredPortInput"),
      settingsError: byId("settingsError")
    };

    bindEvents();
    render();
    loadAll();
  });

  function bindEvents() {
    elements.importSourceButton.addEventListener("click", loadAll);
    elements.viewRunsButton.addEventListener("click", loadAll);
    elements.reviewProjectButton.addEventListener("click", openProjectDialog);
    elements.startReplicationButton.addEventListener("click", openStartDialog);
    elements.footerSettingsButton.addEventListener("click", openSettingsDialog);
    [elements.projectsNav, elements.sourcesNav, elements.runsNav, elements.runtimeNav].forEach(function (button) {
      button.addEventListener("click", function () {
        setActiveView(button.dataset.view || "projects", true);
      });
    });
    elements.projectSwitcher.addEventListener("change", function () {
      state.selectedProjectId = elements.projectSwitcher.value || null;
      chooseSelectedRun();
      render();
      loadSelectedRun();
    });
    elements.addProjectSource.addEventListener("click", function () {
      addPathRow(elements.projectSourcePaths, "source_paths", state.sources);
    });
    elements.addProjectDestination.addEventListener("click", function () {
      addPathRow(elements.projectReplicaRoots, "replica_roots", state.destinations);
    });
    elements.addStartSource.addEventListener("click", function () {
      addPathRow(elements.startSourcePaths, "source_paths", state.sources);
      updateStartSummary();
    });
    elements.addStartDestination.addEventListener("click", function () {
      addPathRow(elements.startReplicaRoots, "replica_roots", state.destinations);
      updateStartSummary();
    });
    elements.previewRollButton.addEventListener("click", function () {
      Promise.resolve()
        .then(previewRoll)
        .catch(function (error) {
          showLine(elements.startError, readableError(error));
        });
    });
    elements.startForm.addEventListener("change", updateStartSummary);
    elements.startForm.elements.project_id.addEventListener("change", renderStartPathRows);
    elements.projectForm.addEventListener("submit", submitProject);
    elements.startForm.addEventListener("submit", submitRun);
    elements.settingsForm.addEventListener("submit", submitSettings);

    document.querySelectorAll("[data-close]").forEach(function (button) {
      button.addEventListener("click", function () {
        byId(button.dataset.close).close();
      });
    });
  }

  function loadAll() {
    state.loading = true;
    state.diskError = null;
    renderRuntime("Loading runtime", "starting");
    return Promise.all([
      api("/api/app/state"),
      api("/api/projects"),
      api("/api/sources"),
      api("/api/destinations"),
      api("/api/app/disks")
    ])
      .then(function (payloads) {
        state.errors.load = "";
        state.runtime = payloads[0].runtime || {};
        state.settings = payloads[0].settings || {};
        state.errors.settings = payloads[0].settings_error || "";
        state.projects = Array.isArray(payloads[1].projects) ? payloads[1].projects : [];
        state.runs = Array.isArray(payloads[1].runs) ? payloads[1].runs : [];
        state.sources = Array.isArray(payloads[2].sources) ? payloads[2].sources : [];
        state.destinations = Array.isArray(payloads[3].destinations) ? payloads[3].destinations : [];
        state.disks = normalizeDisks(payloads[4].disks);
        if (!state.projects.some(function (project) { return project.id === state.selectedProjectId; })) {
          state.selectedProjectId = state.projects[0] ? state.projects[0].id : null;
        }
        chooseSelectedRun();
        state.loading = false;
        render();
        return loadSelectedRun();
      })
      .catch(function (error) {
        state.loading = false;
        state.errors.load = readableError(error);
        renderRuntime(readableError(error), "failed");
        render();
      });
  }

  function loadSelectedRun() {
    if (!state.selectedRunId) {
      state.selectedRunDetail = null;
      state.progress = null;
      state.artifacts = [];
      render();
      scheduleProgressPoll();
      return Promise.resolve();
    }

    return api("/api/runs/" + encodeURIComponent(state.selectedRunId))
      .then(function (payload) {
        state.errors.poll = "";
        state.selectedRunDetail = payload;
        state.progress = payload.progress || null;
        state.artifacts = Array.isArray(payload.artifacts) ? payload.artifacts : [];
        render();
        scheduleProgressPoll();
      })
      .catch(function (error) {
        state.errors.poll = readableError(error);
        state.selectedRunDetail = null;
        state.progress = null;
        state.artifacts = [];
        render();
        scheduleProgressPoll();
      });
  }

  function refreshSelectedRunProgress() {
    var runId = state.selectedRunId;
    if (!runId) {
      scheduleProgressPoll();
      return Promise.resolve();
    }
    return Promise.all([
      api("/api/runs/" + encodeURIComponent(runId) + "/progress"),
      api("/api/runs/" + encodeURIComponent(runId) + "/artifacts")
    ])
      .then(function (payloads) {
        if (runId !== state.selectedRunId) {
          return;
        }
        state.errors.poll = "";
        state.progress = payloads[0] || null;
        state.artifacts = Array.isArray(payloads[1].artifacts) ? payloads[1].artifacts : [];
        render();
        scheduleProgressPoll();
      })
      .catch(function (error) {
        state.errors.poll = readableError(error);
        render();
        scheduleProgressPoll();
      });
  }

  function scheduleProgressPoll() {
    if (progressPollTimer) {
      window.clearTimeout(progressPollTimer);
      progressPollTimer = null;
    }
    if (!state.selectedRunId || isTerminalStatus((state.progress || {}).status)) {
      return;
    }
    progressPollTimer = window.setTimeout(refreshSelectedRunProgress, PROGRESS_POLL_MS);
  }

  function chooseSelectedRun() {
    var projectRuns = currentProjectRuns();
    if (!projectRuns.some(function (run) { return run.run_id === state.selectedRunId; })) {
      state.selectedRunId = projectRuns[0] ? projectRuns[0].run_id : null;
    }
  }

  function render() {
    renderRuntimeStatus();
    renderView();
    renderCounts();
    renderDisks();
    renderActiveProject();
    renderRecentRuns();
    renderProgress();
    renderReports();
    renderCompletions();
    renderAppErrors();
  }

  function renderRuntime(label, serverState) {
    elements.runtimeState.textContent = label;
    elements.sidebarServerState.textContent = stateLabel(serverState);
    elements.sidebarStatusDot.dataset.state = serverState;
  }

  function renderRuntimeStatus() {
    var runtime = state.runtime || null;
    if (!runtime) {
      renderRuntime("Checking runtime", "starting");
      return;
    }
    if (runtime.status === "ok" && !state.errors.settings) {
      renderRuntime("Runtime ready", "running");
      return;
    }
    var message = runtime.errors && runtime.errors.length
      ? runtime.errors[0]
      : (state.errors.settings || "Runtime unavailable");
    renderRuntime(message, "failed");
  }

  function setActiveView(view, shouldFocus) {
    state.activeView = view;
    renderView();
    if (shouldFocus) {
      focusActiveView(view);
    }
  }

  function renderView() {
    var activeView = state.activeView || "projects";
    document.querySelectorAll("[data-view]").forEach(function (button) {
      var active = button.dataset.view === activeView;
      button.classList.toggle("is-active", active);
      if (active) {
        button.setAttribute("aria-current", "page");
      } else {
        button.removeAttribute("aria-current");
      }
    });
    document.querySelectorAll("[data-view-section]").forEach(function (section) {
      var views = String(section.dataset.viewSection || "").split(/\s+/);
      section.hidden = views.indexOf(activeView) === -1;
    });
  }

  function focusActiveView(view) {
    var targets = {
      projects: "activeProjectPanel",
      sources: "activeProjectPanel",
      runs: "recentRunsPanel",
      runtime: "progressPanel"
    };
    var target = byId(targets[view] || "activeProjectPanel");
    if (target) {
      target.focus({ preventScroll: false });
    }
  }

  function renderCounts() {
    elements.projectsMeta.textContent = String(state.projects.length);
    elements.sourcesMeta.textContent = String(state.sources.length);
    elements.runsMeta.textContent = String(state.runs.length);
  }

  function renderActiveProject() {
    var project = selectedProject();
    var sourcePaths = project && Array.isArray(project.source_paths) ? project.source_paths : [];
    elements.projectSwitcher.replaceChildren();
    if (!state.projects.length) {
      elements.projectSwitcher.append(new Option("No projects", ""));
      elements.projectSwitcher.disabled = true;
    } else {
      elements.projectSwitcher.disabled = false;
      state.projects.forEach(function (item) {
        elements.projectSwitcher.append(new Option(item.name, item.id, false, item.id === state.selectedProjectId));
      });
      elements.projectSwitcher.value = state.selectedProjectId || "";
    }
    elements.activeProject.textContent = project ? project.name : "Create or select a project";
    elements.activeProject.classList.toggle("muted", !project);
    elements.activeSource.textContent = sourcePaths.length ? sourcePaths.join(" | ") : "No source selected";
    elements.activeSource.classList.toggle("muted", !sourcePaths.length);
    elements.activeReplicas.textContent = project && Array.isArray(project.replica_roots) && project.replica_roots.length
      ? project.replica_roots.join(" | ")
      : "No replica roots configured";
    elements.activeReplicas.classList.toggle("muted", !(project && project.replica_roots && project.replica_roots.length));
  }

  function renderRecentRuns() {
    clearChildren(elements.recentRunsList);
    var runs = currentProjectRuns();
    if (!runs.length) {
      elements.recentRunsList.appendChild(emptyLine("No runs yet", "Run records will appear after replication starts."));
      return;
    }

    runs.slice(0, 5).forEach(function (run) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "run-card";
      if (run.run_id === state.selectedRunId) {
        button.classList.add("is-active");
      }
      button.innerHTML = "<strong></strong><span></span>";
      button.querySelector("strong").textContent = [run.shoot_date, run.camera_unit, run.roll].filter(Boolean).join(" / ");
      button.querySelector("span").textContent = run.run_id || "";
      button.addEventListener("click", function () {
        state.selectedRunId = run.run_id;
        loadSelectedRun();
        renderRecentRuns();
      });
      elements.recentRunsList.appendChild(button);
    });
  }

  function renderProgress() {
    var progress = state.progress || {};
    var percent = progressPercent(progress);
    var hasRun = Boolean(state.selectedRunId);
    var stage = progress.stage || (hasRun ? "queued" : "standby");
    var status = progress.status || (hasRun ? "waiting" : "idle");
    var title = hasRun ? (progress.phase_label || progressTitle(stage, status)) : "Pipeline waiting";
    var subtitle = hasRun
      ? progressSubtitle(progress, status, state.selectedRunId)
      : "No replication run is active.";
    var activeFiles = Number(progress.active_files);

    elements.overallState.textContent = hasRun ? stateLabelFromStatus(status) : "Standby";
    elements.backupState.textContent = hasRun ? stateLabelFromStatus(status) : "Idle";
    elements.overallTitle.textContent = title;
    elements.overallSubtitle.textContent = subtitle;
    elements.overallPercent.textContent = percent + "%";
    elements.overallProgressbar.setAttribute("aria-valuenow", String(percent));
    elements.overallBar.style.width = percent + "%";
    elements.copiedMetric.textContent = metricFileCount(progress);
    elements.verifiedMetric.textContent = metricReplicaCount(progress);
    elements.reportsMetric.textContent = metricReportCount(progress);
    elements.activeClipCount.textContent = hasRun && Number.isFinite(activeFiles) && activeFiles > 0
      ? activeFiles + " active"
      : activityLabel(progress);
    elements.clipProgressTitle.textContent = hasRun ? title : "No active backup";
    elements.clipProgressSubtitle.textContent = hasRun ? subtitle : "Clip-level progress will appear during replication.";
    elements.clipProgressPercent.textContent = percent + "%";
    elements.clipProgressbar.setAttribute("aria-valuenow", String(percent));
    elements.clipProgressBar.style.width = percent + "%";
  }

  function renderReports() {
    renderReportList(elements.checksumReportList, filterArtifacts("checksum", "manifest"), "No checksum or manifest report yet");
    renderReportList(elements.clipReportList, filterArtifacts("clip", "validation", "datahelper"), "No clip validation report yet");
  }

  function renderReportList(container, artifacts, emptyText) {
    clearChildren(container);
    if (!artifacts.length) {
      container.appendChild(reportItem(emptyText, "--", null));
      return;
    }
    artifacts.forEach(function (artifact) {
      container.appendChild(reportItem(artifact.name || "Report", artifact.kind || "ready", artifact.url));
    });
  }

  function renderCompletions() {
    clearChildren(elements.completionList);
    var runs = currentProjectRuns().filter(function (run) {
      return isCompletedStatus(run.status);
    }).slice(0, 4);
    for (var index = 0; index < 4; index += 1) {
      var run = runs[index];
      var item = document.createElement("li");
      item.innerHTML = "<span class=\"completion-index\"></span><span class=\"completion-copy\"></span><span class=\"completion-meta\"></span>";
      item.querySelector(".completion-index").textContent = String(index + 1).padStart(2, "0");
      item.querySelector(".completion-copy").textContent = run
        ? [run.shoot_date, run.camera_unit, run.roll].filter(Boolean).join(" / ")
        : "Waiting for completed clip";
      item.querySelector(".completion-meta").textContent = run ? "recorded" : "--";
      elements.completionList.appendChild(item);
    }
  }

  function renderDisks() {
    clearChildren(elements.diskList);
    if (!state.disks.length) {
      elements.diskSummary.textContent = state.loading ? "Checking" : "No volumes";
      elements.diskList.appendChild(diskEmpty(state.diskError || (state.loading ? "Checking mounted volumes..." : "No mounted volumes found.")));
      return;
    }
    elements.diskSummary.textContent = state.unmountingPath ? "Ejecting" : state.disks.length + " mounted";
    state.disks.slice(0, 3).forEach(function (disk) {
      elements.diskList.appendChild(diskRow(disk));
    });
    if (state.diskError) {
      var error = document.createElement("div");
      error.className = "disk-error";
      error.textContent = state.diskError;
      elements.diskList.appendChild(error);
    }
  }

  function renderAppErrors() {
    clearChildren(elements.appErrorList);
    var messages = [];
    if (state.errors.load) {
      messages.push("Load error: " + state.errors.load);
    }
    if (state.errors.poll) {
      messages.push("Progress error: " + state.errors.poll);
    }
    if (state.errors.settings) {
      messages.push("Settings error: " + state.errors.settings);
    }
    elements.appErrorList.hidden = messages.length === 0;
    messages.forEach(function (message) {
      var item = document.createElement("div");
      item.className = "app-alert";
      item.textContent = message;
      elements.appErrorList.appendChild(item);
    });
  }

  function openProjectDialog() {
    showLine(elements.projectError, "");
    elements.projectForm.reset();
    elements.projectSourcePaths.replaceChildren();
    elements.projectReplicaRoots.replaceChildren();
    addPathRow(elements.projectSourcePaths, "source_paths", state.sources);
    addPathRow(elements.projectReplicaRoots, "replica_roots", state.destinations);
    elements.projectDialog.showModal();
  }

  function openStartDialog() {
    showLine(elements.startError, "");
    state.latestPreview = null;
    renderStartOptions();
    elements.startDialog.showModal();
  }

  function openSettingsDialog() {
    var settings = state.settings || {};
    elements.bindHostInput.value = settings.bind_host || "127.0.0.1";
    elements.preferredPortInput.value = settings.preferred_port || 8765;
    showLine(elements.settingsError, "");
    elements.settingsDialog.showModal();
  }

  function renderStartOptions() {
    var projectSelect = elements.startForm.elements.project_id;
    projectSelect.replaceChildren();
    state.projects.forEach(function (project) {
      projectSelect.append(new Option(project.name, project.id, false, project.id === state.selectedProjectId));
    });
    renderStartPathRows();
    updateStartSummary();
  }

  function renderStartPathRows() {
    var project = state.projects.find(function (item) {
      return item.id === elements.startForm.elements.project_id.value;
    });
    var sourceValues = project && project.source_paths && project.source_paths.length ? project.source_paths : [];
    var replicaValues = project && project.replica_roots && project.replica_roots.length ? project.replica_roots : [];
    replacePathRows(elements.startSourcePaths, "source_paths", state.sources, sourceValues);
    replacePathRows(elements.startReplicaRoots, "replica_roots", state.destinations, replicaValues);
    updateStartSummary();
  }

  function updateStartSummary() {
    state.latestPreview = null;
    var projectId = elements.startForm.elements.project_id.value;
    var sources = selectedValues(elements.startSourcePaths);
    var destinations = selectedValues(elements.startReplicaRoots);
    var project = state.projects.find(function (item) { return item.id === projectId; });
    elements.startSummary.textContent = project
      ? "Project: " + project.name + " / Sources: " + (sources.join(" | ") || "none") + " / Destinations: " + (destinations.join(" | ") || "none")
      : "Create a project before starting replication.";
  }

  function previewRoll() {
    var form = elements.startForm;
    var payload = startPayload();
    if (!payload.project_id || !payload.source_paths.length || !payload.replica_roots.length || !payload.shoot_date || !payload.camera_unit) {
      throw new Error("Choose project, source, destination, shoot date, and camera before preview.");
    }
    return api("/api/roll-preview", {
      method: "POST",
      body: JSON.stringify({
        project_id: payload.project_id,
        shoot_date: payload.shoot_date,
        camera_unit: payload.camera_unit,
        replica_roots: payload.replica_roots
      })
    }).then(function (preview) {
      state.latestPreview = preview;
      elements.startSummary.textContent = "Roll: " + preview.roll + " / Destinations: " + (preview.replica_destinations || []).join(" | ");
      return form;
    });
  }

  function submitProject(event) {
    event.preventDefault();
    showLine(elements.projectError, "");
    api("/api/projects", {
      method: "POST",
      body: JSON.stringify({
        name: String(new FormData(elements.projectForm).get("name") || ""),
        source_paths: selectedValues(elements.projectSourcePaths),
        replica_roots: selectedValues(elements.projectReplicaRoots)
      })
    })
      .then(function (payload) {
        if (payload.project) {
          upsertProject(payload.project);
          state.selectedProjectId = payload.project.id;
          chooseSelectedRun();
          render();
        }
        elements.projectDialog.close();
        return loadAll();
      })
      .catch(function (error) {
        showLine(elements.projectError, readableError(error));
      });
  }

  function submitRun(event) {
    event.preventDefault();
    showLine(elements.startError, "");
    var payload = startPayload();
    if (!payload.project_id || !payload.source_paths.length || !payload.replica_roots.length) {
      showLine(elements.startError, "Choose a project, source, and destination.");
      return;
    }
    api("/api/runs", {
      method: "POST",
      body: JSON.stringify(payload)
    })
      .then(function (result) {
        state.selectedRunId = result.run_id;
        elements.startDialog.close();
        return loadAll();
      })
      .catch(function (error) {
        showLine(elements.startError, readableError(error));
      });
  }

  function submitSettings(event) {
    event.preventDefault();
    showLine(elements.settingsError, "");
    var preferredPort = Number(elements.preferredPortInput.value);
    if (!Number.isInteger(preferredPort) || preferredPort < 1024 || preferredPort > 65535) {
      showLine(elements.settingsError, "Preferred port must be between 1024 and 65535.");
      return;
    }
    api("/api/app/settings", {
      method: "PUT",
      body: JSON.stringify({
        bind_host: String(elements.bindHostInput.value || "").trim(),
        preferred_port: preferredPort
      })
      })
      .then(function (payload) {
        state.settings = payload.settings || state.settings;
        state.errors.settings = payload.settings_error || "";
        elements.settingsDialog.close();
        render();
      })
      .catch(function (error) {
        showLine(elements.settingsError, readableError(error));
      });
  }

  function startPayload() {
    var formData = new FormData(elements.startForm);
    var sourcePaths = selectedValues(elements.startSourcePaths);
    return {
      project_id: String(formData.get("project_id") || ""),
      shoot_date: String(formData.get("shoot_date") || ""),
      camera_unit: String(formData.get("camera_unit") || ""),
      source_path: sourcePaths[0] || "",
      source_paths: sourcePaths,
      replica_roots: selectedValues(elements.startReplicaRoots)
    };
  }

  function api(path, options) {
    return fetch(path, {
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      ...(options || {})
    }).then(function (response) {
      return response.text().then(function (text) {
        var payload = {};
        if (text) {
          try {
            payload = JSON.parse(text);
          } catch (_error) {
            throw new Error("Server returned a non-JSON response.");
          }
        }
        if (!response.ok) {
          throw new Error(payload.detail || response.statusText || "Request failed.");
        }
        return payload;
      });
    });
  }

  function selectedProject() {
    return state.projects.find(function (project) {
      return project.id === state.selectedProjectId;
    }) || null;
  }

  function upsertProject(project) {
    var replaced = false;
    state.projects = state.projects.map(function (existing) {
      if (existing.id === project.id) {
        replaced = true;
        return project;
      }
      return existing;
    });
    if (!replaced) {
      state.projects = [project].concat(state.projects);
    }
  }

  function currentProjectRuns() {
    return state.runs
      .filter(function (run) {
        return !state.selectedProjectId || run.project_id === state.selectedProjectId;
      })
      .slice()
      .sort(function (a, b) {
        return String(b.created_at || "").localeCompare(String(a.created_at || ""));
      });
  }

  function progressPercent(progress) {
    var explicitPercent = Number(progress.percent);
    if (Number.isFinite(explicitPercent)) {
      return Math.max(0, Math.min(100, Math.round(explicitPercent)));
    }
    var current = Number(progress.current);
    var currentTotal = Number(progress.total);
    if (Number.isFinite(current) && Number.isFinite(currentTotal) && currentTotal > 0) {
      return Math.max(0, Math.min(100, Math.round((current / currentTotal) * 100)));
    }
    var completed = Number(progress.completed);
    var total = Number(progress.total);
    if (Number.isFinite(completed) && Number.isFinite(total) && total > 0) {
      return Math.max(0, Math.min(100, Math.round((completed / total) * 100)));
    }
    var steps = Array.isArray(progress.steps) ? progress.steps : [];
    if (steps.length) {
      var done = steps.filter(function (step) { return step.status === "done"; }).length;
      return Math.round((done / steps.length) * 100);
    }
    return 0;
  }

  function metricFileCount(progress) {
    var fileCount = Number(progress.file_count);
    if (Number.isFinite(fileCount)) {
      return String(fileCount);
    }
    var totalFiles = Number(progress.total_files);
    return Number.isFinite(totalFiles) ? String(totalFiles) : "0";
  }

  function metricReplicaCount(progress) {
    var replicaCount = Number(progress.replica_count);
    if (Number.isFinite(replicaCount)) {
      return String(replicaCount);
    }
    var project = selectedProject();
    return project && Array.isArray(project.replica_roots) ? String(project.replica_roots.length) : "0";
  }

  function metricReportCount(progress) {
    var reportCount = Number(progress.report_count);
    if (Number.isFinite(reportCount)) {
      return String(reportCount);
    }
    return String(state.artifacts.length);
  }

  function filterArtifacts() {
    var terms = Array.prototype.slice.call(arguments).map(function (term) { return term.toLowerCase(); });
    return state.artifacts.filter(function (artifact) {
      var name = String(artifact.name || artifact.path || "").toLowerCase();
      return terms.some(function (term) { return name.indexOf(term) !== -1; });
    });
  }

  function replacePathRows(container, fieldName, candidates, values) {
    container.replaceChildren();
    values.forEach(function (value) {
      addPathRow(container, fieldName, candidates, value);
    });
    if (!values.length) {
      addPathRow(container, fieldName, candidates);
    }
  }

  function addPathRow(container, fieldName, candidates, value) {
    var row = document.createElement("div");
    row.className = "path-row";
    var input = document.createElement("input");
    var list = document.createElement("datalist");
    var listId = fieldName + "-" + Math.random().toString(16).slice(2);
    input.name = fieldName;
    input.required = true;
    input.placeholder = "Type or paste folder path";
    input.setAttribute("data-path-input", "true");
    input.setAttribute("list", listId);
    input.setAttribute("aria-label", fieldName === "source_paths" ? "Folder source path" : "Replica destination path");
    input.setAttribute("aria-describedby", pathHintId(fieldName, container));
    list.id = listId;
    candidates.forEach(function (candidate) {
      var option = document.createElement("option");
      option.value = candidate.path;
      option.label = candidate.name || candidate.path;
      list.appendChild(option);
    });
    if (value) {
      input.value = value;
    }
    var remove = document.createElement("button");
    remove.type = "button";
    remove.className = "icon-button path-remove";
    remove.title = "Remove path";
    remove.setAttribute("aria-label", "Remove path");
    remove.textContent = "-";
    remove.addEventListener("click", function () {
      if (container.children.length > 1) {
        row.remove();
        updatePathRemoveStates(container);
        updateStartSummary();
      }
    });
    row.append(input, list, remove);
    container.append(row);
    updatePathRemoveStates(container);
  }

  function pathHintId(fieldName, container) {
    if (fieldName === "source_paths") {
      return container.id === "startSourcePaths" ? "startSourceHint" : "projectSourceHint";
    }
    return container.id === "startReplicaRoots" ? "startReplicaHint" : "projectReplicaHint";
  }

  function updatePathRemoveStates(container) {
    var rows = Array.from(container.querySelectorAll(".path-row"));
    rows.forEach(function (row) {
      var button = row.querySelector(".path-remove");
      if (button) {
        button.disabled = rows.length <= 1;
        button.setAttribute("aria-disabled", rows.length <= 1 ? "true" : "false");
      }
    });
  }

  function selectedValues(container) {
    return Array.from(container.querySelectorAll("select, input[data-path-input]"))
      .map(function (field) { return field.value.trim(); })
      .filter(Boolean);
  }

  function diskRow(disk) {
    var row = document.createElement("div");
    row.className = "disk-row";
    row.title = disk.path;
    row.innerHTML = "<div class=\"disk-row-top\"><span class=\"disk-name\"></span><div class=\"disk-row-actions\"></div></div><div class=\"disk-track\" aria-hidden=\"true\"><span></span><strong></strong></div>";
    row.querySelector(".disk-name").textContent = disk.name;
    row.querySelector(".disk-track span").style.width = disk.used_percent + "%";
    row.querySelector(".disk-track strong").textContent = formatCapacityRatio(disk.free_bytes, disk.total_bytes);
    if (disk.disk_type === "external") {
      row.querySelector(".disk-row-actions").appendChild(unmountButton(disk));
    }
    return row;
  }

  function unmountButton(disk) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "disk-unmount-button";
    button.title = "Unmount " + disk.name;
    button.setAttribute("aria-label", "Unmount " + disk.name);
    button.disabled = state.unmountingPath === disk.path;
    if (button.disabled) {
      button.title = "Unmounting " + disk.name;
      button.setAttribute("aria-label", "Unmounting " + disk.name);
    }
    button.innerHTML = "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M12 4l5 6H7l5-6z\"></path><path d=\"M5 14h14\"></path><path d=\"M7 19h10\"></path></svg>";
    button.addEventListener("click", function () {
      unmountDisk(disk);
    });
    return button;
  }

  function unmountDisk(disk) {
    state.unmountingPath = disk.path;
    state.diskError = null;
    renderDisks();
    api("/api/app/disks/unmount", {
      method: "POST",
      body: JSON.stringify({ path: disk.path })
    })
      .then(function (payload) {
        state.disks = normalizeDisks(payload.disks);
        state.unmountingPath = null;
        renderDisks();
      })
      .catch(function (error) {
        state.diskError = readableError(error);
        state.unmountingPath = null;
        renderDisks();
      });
  }

  function diskEmpty(message) {
    var empty = document.createElement("div");
    empty.className = "disk-empty";
    empty.textContent = message;
    return empty;
  }

  function emptyLine(title, copy) {
    var fragment = document.createDocumentFragment();
    var titleNode = document.createElement("span");
    var copyNode = document.createElement("span");
    titleNode.className = "empty-title";
    copyNode.className = "empty-copy";
    titleNode.textContent = title;
    copyNode.textContent = copy;
    fragment.append(titleNode, copyNode);
    return fragment;
  }

  function reportItem(name, meta, url) {
    var item = document.createElement("li");
    var dot = document.createElement("span");
    var label = url ? document.createElement("a") : document.createElement("span");
    var time = document.createElement("time");
    dot.className = "report-dot";
    dot.dataset.state = url ? "ready" : "idle";
    label.textContent = name;
    if (url) {
      label.href = url;
      label.className = "report-link";
    }
    time.textContent = meta;
    item.append(dot, label, time);
    return item;
  }

  function normalizeDisks(disks) {
    if (!Array.isArray(disks)) {
      return [];
    }
    return disks.map(function (disk) {
      var freeBytes = Number(disk.free_bytes);
      var usedPercent = Number(disk.used_percent);
      return {
        name: typeof disk.name === "string" && disk.name ? disk.name : "Untitled",
        path: typeof disk.path === "string" && disk.path ? disk.path : "-",
        total_bytes: Number.isFinite(Number(disk.total_bytes)) && Number(disk.total_bytes) > 0 ? Number(disk.total_bytes) : 0,
        free_bytes: Number.isFinite(freeBytes) && freeBytes >= 0 ? freeBytes : 0,
        used_percent: Number.isFinite(usedPercent) ? Math.max(0, Math.min(100, usedPercent)) : 0,
        disk_type: disk.disk_type === "external" ? "external" : "internal"
      };
    }).filter(function (disk) {
      return disk.path !== "-";
    });
  }

  function stageLabel(stage) {
    var labels = {
      datamanager: "Copy in progress",
      datahelper: "Report generation",
      done: "Run completed",
      setup: "Preparing run",
      queued: "Run queued",
      standby: "Pipeline waiting"
    };
    return labels[stage] || stage;
  }

  function progressTitle(stage, status) {
    var normalized = String(status || "").toLowerCase();
    if (normalized === "failed" || normalized === "error") {
      return "Run failed";
    }
    if (normalized === "warn" || normalized === "review-needed") {
      return "Needs review";
    }
    if (normalized === "completed" || normalized === "done") {
      return "Run completed";
    }
    return stageLabel(stage);
  }

  function progressSubtitle(progress, status, runId) {
    var program = progress.program || stageLabel(progress.stage || "");
    var detail = progress.phase_detail || ("Status: " + status + ".");
    var updated = progress.last_progress_at ? "Last update: " + progress.last_progress_at : "";
    return [program, detail, updated, "Run ID: " + runId].filter(Boolean).join(" / ");
  }

  function activityLabel(progress) {
    var labels = {
      running: "Running",
      waiting: "Waiting",
      complete: "Complete",
      failed: "Failed",
      needs_review: "Review",
      unknown: "Unknown"
    };
    return labels[progress.activity_state] || "0 active";
  }

  function isTerminalStatus(status) {
    var normalized = String(status || "").toLowerCase();
    return normalized === "completed" || normalized === "done" || normalized === "failed" || normalized === "error" || normalized === "warn" || normalized === "review-needed";
  }

  function isCompletedStatus(status) {
    var normalized = String(status || "").toLowerCase();
    return normalized === "completed" || normalized === "done";
  }

  function stateLabel(serverState) {
    var labels = {
      stopped: "Stopped",
      starting: "Starting",
      running: "Running",
      failed: "Failed"
    };
    return labels[serverState] || "Running";
  }

  function stateLabelFromStatus(status) {
    var normalized = String(status || "").toLowerCase();
    if (normalized === "completed" || normalized === "done") {
      return "Complete";
    }
    if (normalized === "failed" || normalized === "error") {
      return "Failed";
    }
    if (normalized === "warn" || normalized === "review-needed") {
      return "Needs review";
    }
    return "Active";
  }

  function readableError(error) {
    return error && error.message ? error.message : "Request failed.";
  }

  function showLine(element, message) {
    element.textContent = message || "";
    element.hidden = !message;
  }

  function clearChildren(element) {
    while (element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function formatBytes(bytes) {
    var units = ["B", "KB", "MB", "GB", "TB", "PB"];
    var value = Number(bytes) || 0;
    var unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
      value = value / 1024;
      unit += 1;
    }
    if (unit === 0) {
      return Math.round(value) + " " + units[unit];
    }
    return value.toFixed(value >= 10 ? 0 : 1) + " " + units[unit];
  }

  function formatCapacityRatio(freeBytes, totalBytes) {
    var free = formatBytes(freeBytes).replace(" ", "");
    var total = totalBytes > 0 ? formatBytes(totalBytes).replace(" ", "") : "--";
    return free + "/" + total;
  }

  function byId(id) {
    return document.getElementById(id);
  }
})();
