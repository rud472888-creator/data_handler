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
    activeView: "workflow",
    selectedProjectId: null,
    selectedRunId: null,
    selectedRunDetail: null,
    progress: null,
    artifacts: [],
    latestPreview: null,
    activeReportPreview: null,
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
  var pathPickerRequests = {};
  var pathPickerSequence = 0;

  document.addEventListener("DOMContentLoaded", function () {
    elements = {
      appShell: document.querySelector ? document.querySelector(".app-shell") : null,
      runtimeState: byId("runtimeState"),
      workflowNav: byId("workflowNav"),
      datamanagerNav: byId("datamanagerNav"),
      datahandlerNav: byId("datahandlerNav"),
      workflowMeta: byId("workflowMeta"),
      datamanagerMeta: byId("datamanagerMeta"),
      datahandlerMeta: byId("datahandlerMeta"),
      diskSummary: byId("diskSummary"),
      diskList: byId("diskList"),
      importSourceButton: byId("importSourceButton"),
      startReplicationButton: byId("startReplicationButton"),
      primaryActionHint: byId("primaryActionHint"),
      workspaceTitle: byId("workspaceTitle"),
      workspaceSubtitle: byId("workspaceSubtitle"),
      appErrorList: byId("appErrorList"),
      reviewProjectButton: byId("reviewProjectButton"),
      viewRunsButton: byId("viewRunsButton"),
      footerSettingsButton: byId("footerSettingsButton"),
      activeSource: byId("activeSource"),
      activeReplicas: byId("activeReplicas"),
      activeProject: byId("activeProject"),
      projectReadiness: byId("projectReadiness"),
      sourceReadiness: byId("sourceReadiness"),
      replicaReadiness: byId("replicaReadiness"),
      sourceReadinessDetail: byId("sourceReadinessDetail"),
      replicaReadinessDetail: byId("replicaReadinessDetail"),
      preflightSummary: byId("preflightSummary"),
      preflightTitle: byId("preflightTitle"),
      preflightDetail: byId("preflightDetail"),
      activeProjectTitle: byId("activeProjectTitle"),
      activeProjectSubtitle: byId("activeProjectSubtitle"),
      projectSwitcher: byId("projectSwitcher"),
      recentRunsList: byId("recentRunsList"),
      progressPanel: byId("progressPanel"),
      backupPanel: byId("backupPanel"),
      overallState: byId("overallState"),
      overallTitle: byId("overallTitle"),
      overallSubtitle: byId("overallSubtitle"),
      overallPercent: byId("overallPercent"),
      overallProgressbar: byId("overallProgressbar"),
      overallBar: byId("overallBar"),
      selectedJobLabel: byId("selectedJobLabel"),
      resultCallout: byId("resultCallout"),
      resultCalloutTitle: byId("resultCalloutTitle"),
      resultCalloutDetail: byId("resultCalloutDetail"),
      resultActionButton: byId("resultActionButton"),
      copiedMetric: byId("copiedMetric"),
      verifiedMetric: byId("verifiedMetric"),
      reportsMetric: byId("reportsMetric"),
      stageTimeline: byId("stageTimeline"),
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
      startDialogTitle: byId("startDialogTitle"),
      startForm: byId("startForm"),
      startSourcePaths: byId("startSourcePaths"),
      startReplicaRoots: byId("startReplicaRoots"),
      addStartSource: byId("addStartSource"),
      addStartDestination: byId("addStartDestination"),
      previewRollButton: byId("previewRollButton"),
      startSummary: byId("startSummary"),
      startSubmitButton: byId("startSubmitButton"),
      startError: byId("startError"),
      settingsDialog: byId("settingsDialog"),
      settingsForm: byId("settingsForm"),
      bindHostInput: byId("bindHostInput"),
      preferredPortInput: byId("preferredPortInput"),
      settingsError: byId("settingsError"),
      refreshVolumesButton: byId("refreshVolumesButton"),
      volumeWorkspaceList: byId("volumeWorkspaceList"),
      reportInspector: byId("reportInspector"),
      reportPreviewTitle: byId("reportPreviewTitle"),
      reportPreviewMeta: byId("reportPreviewMeta"),
      reportPreviewFrame: byId("reportPreviewFrame"),
      closeReportPreviewButton: byId("closeReportPreviewButton")
    };

    bindEvents();
    render();
    loadAll();
  });

  window.DataHandlerPathChooser = {
    resolve: function (payload) {
      var requestId = payload && payload.requestId;
      var pending = requestId ? pathPickerRequests[requestId] : null;
      if (!pending) {
        return;
      }
      delete pathPickerRequests[requestId];
      pending.resolve(payload.path || "");
    }
  };

  function bindEvents() {
    elements.importSourceButton.addEventListener("click", loadAll);
    elements.viewRunsButton.addEventListener("click", loadAll);
    elements.refreshVolumesButton.addEventListener("click", loadAll);
    elements.reviewProjectButton.addEventListener("click", openProjectDialog);
    elements.startReplicationButton.addEventListener("click", handlePrimaryAction);
    elements.footerSettingsButton.addEventListener("click", openSettingsDialog);
    [elements.workflowNav, elements.datamanagerNav, elements.datahandlerNav].forEach(function (button) {
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
    elements.closeReportPreviewButton.addEventListener("click", closeReportPreview);
    elements.resultActionButton.addEventListener("click", handleResultAction);

    document.querySelectorAll("[data-close]").forEach(function (button) {
      button.addEventListener("click", function () {
        byId(button.dataset.close).close();
      });
    });
  }

  function loadAll() {
    state.loading = true;
    if (document.body) {
      document.body.dataset.loading = "true";
    }
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
        if (document.body) {
          document.body.dataset.loading = "false";
        }
        render();
        return loadSelectedRun();
      })
      .catch(function (error) {
        state.loading = false;
        if (document.body) {
          document.body.dataset.loading = "false";
        }
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
        if (payload.run && payload.run.run_id) {
          state.runs = state.runs.map(function (run) {
            return run.run_id === payload.run.run_id ? payload.run : run;
          });
        }
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
    renderModeMeta();
    renderModeCopy();
    renderDisks();
    renderActiveProject();
    renderRecentRuns();
    renderProgress();
    renderReports();
    renderReportPreview();
    renderCompletions();
    renderVolumeWorkspace();
    renderAppErrors();
  }

  function renderRuntime(label, serverState) {
    elements.runtimeState.textContent = label;
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
    renderModeCopy();
    if (shouldFocus) {
      focusActiveView(view);
    }
  }

  function renderView() {
    var activeView = state.activeView || "workflow";
    if (document.body) {
      document.body.dataset.view = activeView;
    }
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
      workflow: "progressPanel",
      datamanager: "activeProjectPanel",
      datahandler: "progressPanel",
      datahandler: "progressPanel"
    };
    var target = byId(targets[view] || "activeProjectPanel");
    if (target) {
      target.focus({ preventScroll: false });
    }
  }

  function renderModeMeta() {
    elements.workflowMeta.textContent = "Live";
    elements.datamanagerMeta.textContent = "Offload";
    elements.datahandlerMeta.textContent = "DIT";
  }

  function renderModeCopy() {
    var view = state.activeView || "workflow";
    var copy = modeCopy(view);
    elements.workspaceTitle.textContent = copy.title;
    elements.workspaceSubtitle.textContent = copy.subtitle;
    elements.startReplicationButton.textContent = copy.action;
    elements.activeProjectTitle.textContent = copy.inputTitle;
    elements.activeProjectSubtitle.textContent = copy.inputSubtitle;
    elements.startReplicationButton.hidden = false;
    elements.startReplicationButton.disabled = false;

    if (view === "workflow") {
      elements.primaryActionHint.textContent = "Create a verified offload Job.";
      elements.startReplicationButton.title = "Set up a new backup";
      return;
    }

    if (view === "datahandler") {
      var availablePdf = state.artifacts.find(function (artifact) {
        return artifact.url && String(artifact.kind || "").toLowerCase().indexOf("pdf") !== -1;
      });
      var offlineArtifact = state.artifacts.find(function (artifact) {
        return artifact.availability === "destination_offline";
      });
      if (availablePdf) {
        elements.startReplicationButton.textContent = "Open DIT Report";
        elements.primaryActionHint.textContent = "Open the selected Job's PDF report.";
        elements.startReplicationButton.title = "Open DIT Report";
      } else if (offlineArtifact) {
        elements.startReplicationButton.textContent = "Refresh Status";
        elements.primaryActionHint.textContent = "Reconnect the destination, then refresh.";
        elements.startReplicationButton.title = "Refresh volume and report status";
      } else {
        elements.startReplicationButton.textContent = "No Report Available";
        elements.startReplicationButton.disabled = true;
        elements.primaryActionHint.textContent = "Choose a Job with generated report artifacts.";
        elements.startReplicationButton.title = "No report artifact is available";
      }
      return;
    }

    var readiness = runReadiness();
    if (!readiness.hasProject) {
      elements.startReplicationButton.textContent = "Create Project First";
      elements.startReplicationButton.disabled = true;
      elements.startReplicationButton.title = "Create a project preset before starting.";
      elements.primaryActionHint.textContent = "Create a project preset, then connect its volumes.";
      return;
    }
    if (!readiness.ready) {
      elements.startReplicationButton.textContent = "Connect Required Volumes";
      elements.startReplicationButton.disabled = true;
      elements.startReplicationButton.title = readiness.message;
      elements.primaryActionHint.textContent = readiness.message;
      return;
    }
    elements.startReplicationButton.textContent = copy.action;
    elements.startReplicationButton.title = copy.action;
    elements.primaryActionHint.textContent = "Preflight passed. Review shoot metadata before launch.";
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
    var readiness = runReadiness();
    setReadinessState(elements.projectReadiness, readiness.hasProject ? "ready" : "missing");
    setReadinessState(elements.sourceReadiness, readiness.sourceReady ? "ready" : "missing");
    setReadinessState(elements.replicaReadiness, readiness.replicaReady ? "ready" : "missing");
    elements.sourceReadinessDetail.textContent = readiness.sourceReady
      ? "Source is mounted and available."
      : readiness.hasSource
        ? "Connect: " + readiness.missingSources.join(", ")
        : "Add a source path to this preset.";
    elements.replicaReadinessDetail.textContent = readiness.replicaReady
      ? readiness.replicaCount + " destination" + (readiness.replicaCount === 1 ? " is" : "s are") + " mounted."
      : readiness.hasReplica
        ? "Connect: " + readiness.missingReplicas.join(", ")
        : "Add at least one destination to this preset.";
    elements.preflightSummary.dataset.state = readiness.ready ? "ready" : "missing";
    elements.preflightTitle.textContent = readiness.ready ? "Preflight passed" : "Preflight blocked";
    elements.preflightDetail.textContent = readiness.ready
      ? "The configured source and every destination are connected."
      : readiness.message;
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
      button.dataset.state = normalizedJobStatus(run.status);
      button.innerHTML = "<strong></strong><span></span>";
      button.querySelector("strong").textContent = [run.shoot_date, run.camera_unit, run.roll].filter(Boolean).join(" / ");
      button.querySelector("span").textContent = stateLabelFromStatus(run.status);
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
    var hasRun = Boolean(state.selectedRunId);
    var stage = progress.stage || (hasRun ? "queued" : "standby");
    var status = progress.activity_state || progress.status || (hasRun ? "waiting" : "idle");
    var overall = overallProgressModel(progress, hasRun, stage, status);
    var clip = clipProgressModel(progress, hasRun);

    elements.overallState.dataset.state = normalizedJobStatus(status);
    elements.backupState.dataset.state = normalizedJobStatus(status);
    elements.progressPanel.dataset.state = normalizedJobStatus(status);
    elements.progressPanel.dataset.terminal = isTerminalStatus(status) ? "true" : "false";
    elements.backupPanel.dataset.clipTelemetry = clip.available ? "true" : "false";
    elements.overallState.textContent = hasRun ? stateLabelFromStatus(status) : "Standby";
    elements.backupState.textContent = hasRun ? stateLabelFromStatus(status) : "Idle";
    var selectedRun = state.selectedRunDetail && state.selectedRunDetail.run;
    elements.selectedJobLabel.textContent = selectedRun
      ? [selectedRun.shoot_date, selectedRun.camera_unit, selectedRun.roll].filter(Boolean).join(" / ")
      : "Choose a Job from history to inspect it.";
    elements.overallTitle.textContent = overall.title;
    elements.overallSubtitle.textContent = overall.subtitle;
    elements.overallPercent.textContent = overall.valueLabel;
    elements.overallProgressbar.setAttribute("aria-valuenow", String(overall.barPercent));
    elements.overallBar.style.width = overall.barPercent + "%";
    elements.copiedMetric.textContent = metricFileCount(progress);
    elements.verifiedMetric.textContent = metricReplicaCount(progress);
    elements.reportsMetric.textContent = metricReportCount(progress);
    renderStageTimeline(progress, hasRun);
    elements.activeClipCount.textContent = clip.headerLabel;
    elements.clipProgressTitle.textContent = clip.title;
    elements.clipProgressSubtitle.textContent = clip.subtitle;
    elements.clipProgressPercent.textContent = clip.valueLabel;
    elements.clipProgressbar.setAttribute("aria-valuenow", String(clip.barPercent));
    elements.clipProgressBar.style.width = clip.barPercent + "%";
    renderResultCallout(progress, hasRun);
  }

  function renderReports() {
    renderReportList(elements.checksumReportList, filterArtifacts("checksum", "manifest"), "No checksum output recorded");
    renderReportList(elements.clipReportList, filterArtifacts("clip", "validation", "datahelper"), "No media inspection output recorded");
  }

  function renderReportList(container, artifacts, emptyText) {
    clearChildren(container);
    container.dataset.empty = artifacts.length ? "false" : "true";
    if (!artifacts.length) {
      container.appendChild(reportItem(emptyText, "Not recorded", null, "missing"));
      return;
    }
    artifacts.forEach(function (artifact) {
      container.appendChild(reportItem(
        artifactDisplayName(artifact),
        artifactAvailabilityLabel(artifact),
        artifact.url,
        artifact.availability || (artifact.url ? "available" : "missing")
      ));
    });
  }

  function renderReportPreview() {
    var preview = state.activeReportPreview;
    var isOpen = Boolean(preview && preview.url);
    if (elements.appShell) {
      elements.appShell.dataset.inspectorOpen = isOpen ? "true" : "false";
    }
    elements.reportInspector.hidden = !isOpen;
    if (!isOpen) {
      elements.reportPreviewTitle.textContent = "Report Preview";
      elements.reportPreviewMeta.textContent = "No report selected.";
      elements.reportPreviewFrame.src = "";
      return;
    }
    elements.reportPreviewTitle.textContent = preview.name || "Report Preview";
    elements.reportPreviewMeta.textContent = preview.meta || "ready";
    if (elements.reportPreviewFrame.src !== preview.url) {
      elements.reportPreviewFrame.src = preview.url;
    }
  }

  function renderCompletions() {
    clearChildren(elements.completionList);
    var runs = currentProjectRuns().filter(function (run) {
      return isCompletedStatus(run.status);
    }).slice(0, 4);
    if (!runs.length) {
      var empty = document.createElement("li");
      empty.className = "completion-empty";
      empty.textContent = "No completed hand-offs";
      elements.completionList.appendChild(empty);
      return;
    }
    runs.forEach(function (run, index) {
      var item = document.createElement("li");
      item.innerHTML = "<span class=\"completion-index\"></span><span class=\"completion-copy\"></span><span class=\"completion-meta\"></span>";
      item.querySelector(".completion-index").textContent = String(index + 1).padStart(2, "0");
      item.querySelector(".completion-copy").textContent = [run.shoot_date, run.camera_unit, run.roll].filter(Boolean).join(" / ");
      item.querySelector(".completion-meta").textContent = stateLabelFromStatus(run.status);
      elements.completionList.appendChild(item);
    });
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

  function handlePrimaryAction() {
    var view = state.activeView || "workflow";
    if (view === "workflow") {
      setActiveView("datamanager", true);
      return;
    }
    if (view === "datahandler") {
      var report = state.artifacts.find(function (artifact) {
        return artifact.url && String(artifact.kind || "").toLowerCase().indexOf("pdf") !== -1;
      });
      if (report) {
        openReportPreview(report.name || "DIT Report", artifactAvailabilityLabel(report), report.url);
      } else if (state.artifacts.some(function (artifact) { return artifact.availability === "destination_offline"; })) {
        loadAll();
      }
      return;
    }
    var readiness = runReadiness();
    if (!readiness.ready) {
      return;
    }
    if (!selectedProject()) {
      openProjectDialog();
      return;
    }
    openStartDialog();
  }

  function startDataHandlerForSelectedRun() {
    var handlerState = datahandlerActionState();
    if (!handlerState.enabled) {
      state.errors.poll = handlerState.message;
      renderAppErrors();
      renderModeCopy();
      return;
    }
    showLine(elements.startError, "");
    elements.startReplicationButton.disabled = true;
    api("/api/runs/" + encodeURIComponent(state.selectedRunId) + "/datahandler", {
      method: "POST",
      body: JSON.stringify({})
    })
      .then(function () {
        return loadSelectedRun();
      })
      .catch(function (error) {
        state.errors.poll = readableError(error);
        render();
      });
  }

  function openSettingsDialog() {
    var settings = state.settings || {};
    elements.bindHostInput.value = settings.bind_host || "127.0.0.1";
    elements.preferredPortInput.value = settings.preferred_port || 8765;
    showLine(elements.settingsError, "");
    elements.settingsDialog.showModal();
  }

  function renderStartOptions() {
    var copy = modeCopy(activeMode());
    elements.startDialogTitle.textContent = copy.action;
    elements.startSubmitButton.textContent = copy.action;
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
      replica_roots: selectedValues(elements.startReplicaRoots),
      run_mode: activeMode() === "datamanager" ? "datamanager" : "workflow"
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

  function activeMode() {
    // New Backup always runs the complete copy, verification, and report sequence.
    return "workflow";
  }

  function modeCopy(view) {
    if (view === "datamanager") {
      return {
        title: "New Backup",
        subtitle: "Confirm connected media, destinations, and shoot metadata before offload.",
        action: "Review & Start",
        inputTitle: "Backup Readiness",
        inputSubtitle: "Project and connected media must be ready."
      };
    }
    if (view === "datahandler") {
      return {
        title: "Reports",
        subtitle: "Review DIT outputs, media issues, and destination availability.",
        action: "Open DIT Report",
        inputTitle: "Report Context",
        inputSubtitle: "Select a Job to inspect its outputs."
      };
    }
    return {
      title: "Jobs",
      subtitle: "Monitor backups, verification, media checks, and report handoff.",
      action: "New Backup",
      inputTitle: "Job Context",
      inputSubtitle: "Choose a recent Job or start a new backup."
    };
  }

  function datahandlerActionState() {
    if (!state.selectedRunId) {
      return { enabled: false, message: "Select a completed DataManager run." };
    }
    var progress = state.progress || {};
    if (progress.datahelper_done) {
      return { enabled: false, message: "DataHandler has already completed for the selected run." };
    }
    if (progress.datahelper_started) {
      return { enabled: false, message: "DataHandler has already started for the selected run." };
    }
    if (!progress.datamanager_done) {
      return { enabled: false, message: "The selected run has no completed DataManager output yet." };
    }
    var status = String(progress.status || "").toLowerCase();
    if (status === "failed" || status === "error") {
      return { enabled: false, message: "DataManager failed for the selected run." };
    }
    return { enabled: true, message: "Ready to run DataHandler for the selected DataManager output." };
  }

  function runReadiness() {
    var project = selectedProject();
    var sourcePaths = project && Array.isArray(project.source_paths) ? project.source_paths : [];
    var replicaRoots = project && Array.isArray(project.replica_roots) ? project.replica_roots : [];
    var missingSources = sourcePaths.filter(function (path) { return !pathIsMounted(path); });
    var missingReplicas = replicaRoots.filter(function (path) { return !pathIsMounted(path); });
    var sourceReady = sourcePaths.length > 0 && missingSources.length === 0;
    var replicaReady = replicaRoots.length > 0 && missingReplicas.length === 0;
    var message = "Select a project preset.";
    if (project && !sourcePaths.length) {
      message = "Add a source path to the selected project preset.";
    } else if (project && missingSources.length) {
      message = "Connect source: " + missingSources.join(", ");
    } else if (project && !replicaRoots.length) {
      message = "Add at least one destination to the selected project preset.";
    } else if (project && missingReplicas.length) {
      message = "Connect destination: " + missingReplicas.join(", ");
    }
    return {
      hasProject: Boolean(project),
      hasSource: sourcePaths.length > 0,
      hasReplica: replicaRoots.length > 0,
      sourceReady: sourceReady,
      replicaReady: replicaReady,
      replicaCount: replicaRoots.length,
      missingSources: missingSources,
      missingReplicas: missingReplicas,
      ready: Boolean(project && sourceReady && replicaReady),
      message: Boolean(project && sourceReady && replicaReady) ? "Preflight passed." : message
    };
  }

  function setReadinessState(element, readinessState) {
    if (!element) {
      return;
    }
    element.dataset.state = readinessState || "missing";
  }

  function pathIsMounted(path) {
    return state.disks.some(function (disk) {
      return pathBelongsToDisk(path, disk);
    });
  }

  function pathBelongsToDisk(path, disk) {
    var normalized = String(path || "").replace(/\/+$/, "");
    var mountPath = String((disk || {}).path || "").replace(/\/+$/, "");
    return Boolean(normalized && mountPath && (normalized === mountPath || normalized.indexOf(mountPath + "/") === 0));
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
    var overall = progress && progress.overall_progress;
    if (overall && typeof overall === "object") {
      var overallPercent = Number(overall.percent);
      if (Number.isFinite(overallPercent)) {
        return Math.max(0, Math.min(100, Math.round(overallPercent)));
      }
    }
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

  function overallProgressModel(progress, hasRun, stage, status) {
    if (!hasRun) {
      return progressDisplay("Pipeline waiting", "No replication run is active.", null, "0%");
    }
    var raw = progress.overall_progress && typeof progress.overall_progress === "object"
      ? progress.overall_progress
      : {};
    var title = userFacingProgressTitle(raw.title || progress.phase_label || progressTitle(stage, status));
    var subtitle = progressSubtitle(
      {
        program: progress.program,
        stage: progress.stage,
        phase_detail: raw.subtitle || progress.phase_detail,
        last_progress_at: progress.last_progress_at
      },
      status,
      state.selectedRunId
    );
    var percent = finitePercent(raw.percent);
    if (percent === null && !raw.kind && stage !== "datahelper" && stage !== "reports") {
      percent = progressPercent(progress);
    }
    if (percent !== null) {
      return progressDisplay(title, subtitle, percent, percentLabel(percent, raw.kind));
    }
    return progressDisplay(title, subtitle, null, unknownProgressLabel(progress));
  }

  function clipProgressModel(progress, hasRun) {
    if (!hasRun) {
      return {
        title: "No active backup",
        subtitle: "Clip-level progress will appear during replication.",
        valueLabel: "0%",
        barPercent: 0,
        headerLabel: "Idle",
        available: false
      };
    }
    var clip = progress.clip_progress && typeof progress.clip_progress === "object"
      ? progress.clip_progress
      : {};
    if (clip.available) {
      var percent = finitePercent(clip.percent);
      return {
        title: clip.title || clip.name || "Active clip telemetry",
        subtitle: clip.subtitle || "Current clip-level progress is being reported.",
        valueLabel: percent === null ? "Running" : percent + "%",
        barPercent: percent === null ? 0 : percent,
        headerLabel: clipHeaderLabel(clip),
        available: true
      };
    }
    return {
      title: "Not reported",
      subtitle: "Clip-level progress is unavailable for this Job.",
      valueLabel: "--",
      barPercent: 0,
      headerLabel: "No telemetry",
      available: false
    };
  }

  function progressDisplay(title, subtitle, percent, valueLabel) {
    return {
      title: title,
      subtitle: subtitle,
      valueLabel: valueLabel,
      barPercent: percent === null ? 0 : percent
    };
  }

  function renderStageTimeline(progress, hasRun) {
    clearChildren(elements.stageTimeline);
    var steps = hasRun && Array.isArray(progress.steps) && progress.steps.length
      ? progress.steps
      : defaultTimelineSteps();
    steps.forEach(function (step) {
      var item = document.createElement("li");
      var status = normalizeStepStatus(step.status);
      var name = String(step.name || "");
      item.dataset.state = status;
      item.innerHTML = "<span></span><strong></strong>";
      item.querySelector("span").textContent = stageNameLabel(name);
      item.querySelector("strong").textContent = stepStateLabel(status, hasRun);
      elements.stageTimeline.appendChild(item);
    });
  }

  function defaultTimelineSteps() {
    return ["setup", "copy", "checksum", "reports", "finalization", "done"].map(function (name) {
      return { name: name, status: "pending" };
    });
  }

  function normalizeStepStatus(status) {
    var normalized = String(status || "pending").toLowerCase();
    if (normalized === "done" || normalized === "current" || normalized === "failed" || normalized === "needs_review" || normalized === "blocked") {
      return normalized;
    }
    return "pending";
  }

  function stageNameLabel(name) {
    var labels = {
      setup: "Setup",
      copy: "Copy",
      checksum: "Verify",
      reports: "Media Check",
      finalization: "Report",
      done: "Handoff"
    };
    return labels[name] || name || "Step";
  }

  function stepStateLabel(status, hasRun) {
    if (!hasRun) {
      return "Waiting";
    }
    var labels = {
      done: "Done",
      current: "Now",
      failed: "Failed",
      needs_review: "Review",
      blocked: "Not run",
      pending: "Waiting"
    };
    return labels[status] || "Waiting";
  }

  function finitePercent(value) {
    if (value === null || value === undefined || value === "") {
      return null;
    }
    var percent = Number(value);
    if (!Number.isFinite(percent)) {
      return null;
    }
    return Math.max(0, Math.min(100, Math.round(percent)));
  }

  function percentLabel(percent, kind) {
    if (kind === "copy_bytes") {
      return percent + "% bytes observed";
    }
    if (kind === "report_jobs") {
      return percent + "% reports";
    }
    return percent + "%";
  }

  function unknownProgressLabel(progress) {
    var state = String(progress.activity_state || progress.status || "").toLowerCase();
    if (state === "waiting" || state.indexOf("spawned") === 0 || state === "starting") {
      return "Waiting";
    }
    if (state === "failed" || state === "error") {
      return "Failed";
    }
    if (state === "needs_review" || state === "warn" || state === "review-needed") {
      return "Review";
    }
    if (state === "complete" || state === "completed" || state === "done") {
      return "Complete";
    }
    return "Running";
  }

  function clipHeaderLabel(clip) {
    var active = Number(clip.active_files || clip.active_clips);
    if (Number.isFinite(active) && active > 0) {
      return active + " active";
    }
    return "Clip telemetry";
  }

  function metricFileCount(progress) {
    var copy = progress.copy_progress && typeof progress.copy_progress === "object" ? progress.copy_progress : {};
    var copiedFiles = Number(copy.copied_files);
    var totalCopyFiles = Number(copy.total_files || copy.file_count);
    if (Number.isFinite(copiedFiles) && Number.isFinite(totalCopyFiles) && totalCopyFiles > 0) {
      return String(copiedFiles) + "/" + String(totalCopyFiles);
    }
    var copied = Number(progress.copied_files);
    var total = Number(progress.total_files);
    if (Number.isFinite(copied) && Number.isFinite(total) && total > 0) {
      return String(copied) + "/" + String(total);
    }
    var fileCount = Number(progress.file_count);
    if (Number.isFinite(fileCount)) {
      return String(fileCount);
    }
    var totalFiles = Number(progress.total_files);
    return Number.isFinite(totalFiles) ? String(totalFiles) : "0";
  }

  function metricReplicaCount(progress) {
    var copy = progress.copy_progress && typeof progress.copy_progress === "object" ? progress.copy_progress : {};
    var copyReplicaCount = Number(copy.replica_count);
    if (Number.isFinite(copyReplicaCount)) {
      return String(copyReplicaCount);
    }
    var replicaCount = Number(progress.replica_count);
    if (Number.isFinite(replicaCount)) {
      return String(replicaCount);
    }
    var project = selectedProject();
    return project && Array.isArray(project.replica_roots) ? String(project.replica_roots.length) : "0";
  }

  function metricReportCount(progress) {
    var report = progress.report_progress && typeof progress.report_progress === "object" ? progress.report_progress : {};
    var artifactCount = Number(report.artifact_count);
    if (Number.isFinite(artifactCount)) {
      return String(artifactCount);
    }
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

  function artifactDisplayName(artifact) {
    var name = String(artifact.name || artifact.path || "").toLowerCase();
    var destinationMatch = name.match(/path(\d+)/);
    var destinationSuffix = destinationMatch ? " · Destination " + destinationMatch[1] : "";
    if (name.indexOf("checksum") !== -1) {
      return "Checksum Report";
    }
    if (name.indexOf("manifest") !== -1) {
      return "Copy Manifest";
    }
    if (name.indexOf("datahelper") !== -1 && name.indexOf("pdf") !== -1) {
      return "DIT Report" + destinationSuffix;
    }
    if (name.indexOf("datahelper") !== -1 && name.indexOf("csv") !== -1) {
      return "Media Inspection CSV" + destinationSuffix;
    }
    if (name.indexOf("datahelper") !== -1 && name.indexOf("json") !== -1) {
      return "Media Inspection JSON" + destinationSuffix;
    }
    return artifact.name || "Report";
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
    var browse = document.createElement("button");
    browse.type = "button";
    browse.className = "button subtle path-browse";
    browse.textContent = "Browse";
    browse.setAttribute("aria-label", fieldName === "source_paths" ? "Browse source folder" : "Browse destination folder");
    browse.addEventListener("click", function () {
      requestFolderPath(input.value)
        .then(function (path) {
          if (!path) {
            input.focus();
            return;
          }
          input.value = path;
          updateStartSummary();
        })
        .catch(function (error) {
          showLine(errorLineForPathContainer(container), readableError(error));
        });
    });
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
    row.append(input, list, browse, remove);
    container.append(row);
    updatePathRemoveStates(container);
  }

  function requestFolderPath(currentPath) {
    var handler = window.webkit
      && window.webkit.messageHandlers
      && window.webkit.messageHandlers.pathChooser;
    if (!handler || typeof handler.postMessage !== "function") {
      return Promise.resolve("");
    }
    pathPickerSequence += 1;
    var requestId = "path-" + Date.now() + "-" + pathPickerSequence;
    return new Promise(function (resolve) {
      pathPickerRequests[requestId] = { resolve: resolve };
      handler.postMessage({
        requestId: requestId,
        currentPath: currentPath || ""
      });
    });
  }

  function errorLineForPathContainer(container) {
    if (container.id === "startSourcePaths" || container.id === "startReplicaRoots") {
      return elements.startError;
    }
    return elements.projectError;
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

  function reportItem(name, meta, url, availability) {
    var item = document.createElement("li");
    var dot = document.createElement("span");
    var label = url ? document.createElement("a") : document.createElement("span");
    var time = document.createElement("time");
    dot.className = "report-dot";
    dot.dataset.state = availability === "available" ? "ready" : availability || "idle";
    label.textContent = name;
    if (url) {
      label.href = url;
      label.className = "report-link";
      if (isPdfUrl(url)) {
        label.addEventListener("click", function (event) {
          event.preventDefault();
          openReportPreview(name, meta, url);
        });
      }
    }
    time.textContent = meta;
    item.append(dot, label, time);
    return item;
  }

  function artifactAvailabilityLabel(artifact) {
    var availability = artifact && artifact.availability;
    if (availability === "destination_offline") {
      return "Drive offline";
    }
    if (availability === "missing") {
      return "Missing";
    }
    return artifact && artifact.kind ? artifact.kind : "Available";
  }

  function isPdfUrl(url) {
    return String(url || "").split("?")[0].toLowerCase().endsWith(".pdf");
  }

  function openReportPreview(name, meta, url) {
    state.activeReportPreview = {
      name: name,
      meta: meta,
      url: url
    };
    renderReportPreview();
  }

  function closeReportPreview() {
    state.activeReportPreview = null;
    renderReportPreview();
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

  function renderVolumeWorkspace() {
    clearChildren(elements.volumeWorkspaceList);
    var project = selectedProject();
    var configuredRoles = [];
    if (project) {
      (project.source_paths || []).forEach(function (path) {
        configuredRoles.push({ role: "Source", path: path });
      });
      (project.replica_roots || []).forEach(function (path) {
        configuredRoles.push({ role: "Destination", path: path });
      });
    }
    var connected = state.disks.map(function (disk) {
      var roles = configuredRoles.filter(function (item) {
        return pathBelongsToDisk(item.path, disk);
      }).map(function (item) {
        return item.role;
      });
      return {
        disk: disk,
        role: roles.length ? roles.join(", ") : (disk.disk_type === "external" ? "Unassigned" : "System")
      };
    });
    var reconnect = configuredRoles.filter(function (item) {
      return !state.disks.some(function (disk) {
        return pathBelongsToDisk(item.path, disk);
      });
    });
    if (!connected.length && !reconnect.length) {
      elements.volumeWorkspaceList.appendChild(emptyLine("No volumes", "Connect media or select a project preset."));
      return;
    }

    function appendGroup(title, detail, items, missing) {
      if (!items.length) {
        return;
      }
      var group = document.createElement("section");
      group.className = "volume-group";
      group.dataset.state = missing ? "missing" : "ready";
      var heading = document.createElement("div");
      heading.className = "volume-group-heading";
      heading.innerHTML = "<div><h3></h3><p></p></div><span class=\"volume-count\"></span>";
      heading.querySelector("h3").textContent = title;
      heading.querySelector("p").textContent = detail;
      heading.querySelector(".volume-count").textContent = String(items.length);
      group.appendChild(heading);
      var list = document.createElement("div");
      list.className = "volume-group-list";
      items.forEach(function (item) {
        var disk = item.disk || null;
        var row = document.createElement("div");
        row.className = "volume-workspace-row";
        row.dataset.state = missing ? "missing" : "ready";
        row.innerHTML = "<div><span class=\"volume-role\"></span><strong></strong><span class=\"volume-path\"></span></div><div class=\"volume-state\"><strong></strong><span></span></div>";
        row.querySelector(".volume-role").textContent = item.role;
        row.querySelector("div > strong").textContent = disk ? disk.name : volumeName(item.path);
        row.querySelector(".volume-path").textContent = disk ? disk.path : item.path;
        row.querySelector(".volume-state strong").textContent = missing ? "Not connected" : "Connected";
        row.querySelector(".volume-state span").textContent = missing ? "Required for backup" : formatBytes(disk.free_bytes) + " free";
        list.appendChild(row);
      });
      group.appendChild(list);
      elements.volumeWorkspaceList.appendChild(group);
    }

    appendGroup("Mounted Volumes", "Currently connected to this Mac.", connected, false);
    appendGroup("Reconnect Required", "Configured paths that are not currently mounted.", reconnect, true);
  }

  function volumeName(path) {
    var parts = String(path || "").split("/").filter(Boolean);
    return parts.length ? parts[parts.length - 1] : "Unknown volume";
  }

  function renderResultCallout(progress, hasRun) {
    var quality = progress.quality && typeof progress.quality === "object" ? progress.quality : null;
    var failure = progress.failure && typeof progress.failure === "object" ? progress.failure : null;
    var status = String(progress.activity_state || progress.status || "").toLowerCase();
    if (!hasRun || (!quality && !failure && status !== "failed" && status !== "error")) {
      elements.resultCallout.hidden = true;
      return;
    }
    elements.resultCallout.hidden = false;
    if (failure && Number(failure.failed_count) > 0) {
      elements.resultCallout.dataset.state = "failed";
      elements.resultCalloutTitle.textContent = "Backup failed";
      elements.resultCalloutDetail.textContent = failure.failed_count + " file failed: " + failure.failed_files[0];
      elements.resultActionButton.textContent = "Prepare retry";
      return;
    }
    if (status === "failed" || status === "error") {
      elements.resultCallout.dataset.state = "failed";
      elements.resultCalloutTitle.textContent = "Backup failed";
      elements.resultCalloutDetail.textContent = progress.phase_detail || "The Job did not reach a safe handoff state.";
      elements.resultActionButton.textContent = "Prepare retry";
      return;
    }
    if (quality && quality.status === "needs_review") {
      elements.resultCallout.dataset.state = "needs_review";
      elements.resultCalloutTitle.textContent = "Backup complete, review needed";
      elements.resultCalloutDetail.textContent = quality.issue_count + " of " + quality.total_clips + " clips need review.";
      elements.resultActionButton.textContent = "View reports";
      return;
    }
    elements.resultCallout.dataset.state = "ready";
    elements.resultCalloutTitle.textContent = "Backup verified";
    elements.resultCalloutDetail.textContent = "Copy, verification, and media inspection completed without a reported issue.";
    elements.resultActionButton.textContent = "View reports";
  }

  function handleResultAction() {
    var progress = state.progress || {};
    if (progress.failure) {
      setActiveView("datamanager", true);
      return;
    }
    setActiveView("datahandler", true);
  }

  function normalizedJobStatus(status) {
    var normalized = String(status || "").toLowerCase();
    if (normalized === "review-needed" || normalized === "warn" || normalized === "needs_review") {
      return "needs_review";
    }
    if (normalized === "failed" || normalized === "error") {
      return "failed";
    }
    if (normalized === "completed" || normalized === "done" || normalized === "complete") {
      return "ready";
    }
    if (normalized === "running" || normalized === "active") {
      return "running";
    }
    return "waiting";
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
    var program = userFacingProgramName(progress.program, progress.stage);
    var detail = progress.phase_detail || ("Status: " + status + ".");
    return [program, detail].filter(Boolean).join(" / ");
  }

  function userFacingProgressTitle(title) {
    return String(title || "")
      .replace(/DataManager/g, "Copy and verification")
      .replace(/DataHelper(?: \(Handler\))? reports/g, "Media inspection and reports")
      .replace(/DataHelper(?: \(Handler\))?/g, "Media inspection");
  }

  function userFacingProgramName(program, stage) {
    var normalized = String(program || "").toLowerCase();
    if (normalized.indexOf("datamanager") !== -1) {
      return "Copy and verification";
    }
    if (normalized.indexOf("datahelper") !== -1 || normalized.indexOf("handler") !== -1) {
      return "Media inspection and reports";
    }
    return program || stageLabel(stage || "");
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
    return normalized === "completed" || normalized === "complete" || normalized === "done" || normalized === "failed" || normalized === "error" || normalized === "warn" || normalized === "review-needed" || normalized === "needs_review";
  }

  function isCompletedStatus(status) {
    var normalized = String(status || "").toLowerCase();
    return normalized === "completed" || normalized === "done" || normalized === "warn" || normalized === "review-needed";
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
    if (normalized === "completed" || normalized === "done" || normalized === "complete" || normalized === "ready") {
      return "Complete";
    }
    if (normalized === "failed" || normalized === "error") {
      return "Failed";
    }
    if (normalized === "warn" || normalized === "review-needed" || normalized === "needs_review") {
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
