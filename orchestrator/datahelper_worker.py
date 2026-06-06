from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from orchestrator.jsonio import read_json, write_json
from orchestrator.paths import DATA_HELPER_ROOT
from orchestrator.run_state import events_dir, load_spec, run_dir, update_state, utc_now
from orchestrator.web.progress import write_progress


def run_datahelper(run_id: str) -> dict[str, Any]:
    spec = load_spec(run_id)
    spec.validate()
    update_state(run_id, stage="datahelper", status="running")
    write_progress(
        run_dir(run_id),
        {"stage": "datahelper", "status": "running", "step": "reports"},
    )
    dm_done = read_json(events_dir(run_id) / "datamanager.done.json")
    replica_project_roots = dm_done.get("replica_project_roots", {})
    if not isinstance(replica_project_roots, dict) or not replica_project_roots:
        error = "missing replica_project_roots; DataHelper did not run Frame Proof"
        payload: dict[str, Any] = {
            "run_id": run_id,
            "stage": "datahelper",
            "status": "failed",
            "error": error,
            "reports": [],
            "finished_at": utc_now(),
        }
        write_json(events_dir(run_id) / "datahelper.done.json", payload)
        update_state(run_id, stage="datahelper", status="failed", error=error)
        write_progress(
            run_dir(run_id),
            {
                "stage": "datahelper",
                "status": "failed",
                "step": "reports",
                "current": 0,
                "total": 0,
                "completed": 0,
                "report_completed": 0,
                "report_total": 0,
                "artifacts_ready": False,
                "error": error,
            },
        )
        return payload
    labels = sorted(replica_project_roots)
    file_count = dm_done.get("file_count")
    replica_count = len(labels)
    results: list[dict[str, Any]] = []
    for label in labels:
        results.append(
            _run_one(
                label=label,
                input_path=_footage_input_path(dm_done, label),
                output_root=_report_output_root(dm_done, label),
                project_name=f"{spec.project_name} {label} replica",
            )
        )
        write_progress(
            run_dir(run_id),
            {
                "stage": "datahelper",
                "status": "running",
                "step": "reports",
                "current": len(results),
                "total": len(labels),
                "file_count": file_count,
                "replica_count": replica_count,
                "report_completed": sum(1 for result in results if result["status"] == "completed"),
                "report_total": len(labels),
                "report_count": _report_count(dm_done, results),
            },
        )
    if all(result["status"] == "completed" for result in results):
        status = "completed"
    elif any(result["exit_code"] != 0 for result in results):
        status = "failed"
    else:
        status = "review-needed"
    payload: dict[str, Any] = {
        "run_id": run_id,
        "stage": "datahelper",
        "status": status,
        "reports": results,
        "finished_at": utc_now(),
    }
    write_json(events_dir(run_id) / "datahelper.done.json", payload)
    update_state(run_id, stage="datahelper", status=status)
    write_progress(
        run_dir(run_id),
        {
            "stage": "datahelper",
            "status": status,
            "step": "reports",
            "current": len(results),
            "total": len(results),
            "completed": sum(1 for result in results if result["status"] == "completed"),
            "file_count": file_count,
            "replica_count": replica_count,
            "report_completed": sum(1 for result in results if result["status"] == "completed"),
            "report_total": len(results),
            "report_count": _report_count(dm_done, results),
            "artifacts_ready": all(result["status"] == "completed" for result in results),
        },
    )
    return payload


def _run_one(label: str, input_path: Path, output_root: Path, project_name: str) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    pdf_path = output_root / f"datahelper-{label}.pdf"
    csv_path = output_root / f"datahelper-{label}.csv"
    json_path = output_root / f"datahelper-{label}.json"
    if not input_path.exists():
        return {
            "label": label,
            "input_path": str(input_path),
            "exit_code": 2,
            "status": "missing_input",
            "stdout": "",
            "stderr": f"input path does not exist: {input_path}",
            "pdf_path": str(pdf_path),
            "csv_path": str(csv_path),
            "json_path": str(json_path),
            **_artifact_readiness(pdf_path, csv_path, json_path),
        }
    command = build_frameproof_command(
        input_path=input_path,
        pdf_path=pdf_path,
        csv_path=csv_path,
        json_path=json_path,
        project_name=project_name,
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = _prepend_pythonpath(str(DATA_HELPER_ROOT / "src"), env.get("PYTHONPATH"))
    completed = subprocess.run(
        command,
        cwd=str(DATA_HELPER_ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    readiness = _artifact_readiness(pdf_path, csv_path, json_path)
    status = "completed" if completed.returncode == 0 and not readiness["missing_artifacts"] else "failed"
    if completed.returncode == 0 and readiness["missing_artifacts"]:
        status = "review-needed"
    return {
        "label": label,
        "input_path": str(input_path),
        "exit_code": completed.returncode,
        "status": status,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "pdf_path": str(pdf_path),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        **readiness,
    }


def _report_count(dm_done: dict[str, Any], results: list[dict[str, Any]]) -> int:
    datamanager_reports = dm_done.get("reports", {})
    count = 0
    if isinstance(datamanager_reports, dict):
        count += sum(1 for path in datamanager_reports.values() if Path(str(path)).is_file())
    for result in results:
        for key in ("pdf_path", "csv_path", "json_path"):
            path = Path(str(result.get(key, "")))
            if path.is_file() and path.stat().st_size > 0:
                count += 1
    return count


def _artifact_readiness(pdf_path: Path, csv_path: Path, json_path: Path) -> dict[str, Any]:
    paths = {
        "pdf": pdf_path,
        "csv": csv_path,
        "json": json_path,
    }
    checks: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for label, path in paths.items():
        exists = path.is_file()
        size = path.stat().st_size if exists else 0
        ready = exists and size > 0
        checks[label] = {"path": str(path), "exists": exists, "size_bytes": size, "ready": ready}
        if not ready:
            missing.append(label)
    return {
        "pdf_ready": checks["pdf"]["ready"],
        "csv_ready": checks["csv"]["ready"],
        "json_ready": checks["json"]["ready"],
        "artifact_checks": checks,
        "missing_artifacts": missing,
    }


def build_frameproof_command(
    *,
    input_path: Path,
    pdf_path: Path,
    csv_path: Path,
    json_path: Path,
    project_name: str,
) -> list[str]:
    python = DATA_HELPER_ROOT / ".venv" / "bin" / "python"
    executable = str(python if python.exists() else Path(sys.executable))
    command = [
        executable,
        "-m",
        "frameproof",
        "--input",
        str(input_path),
        "--output",
        str(pdf_path),
        "--csv",
        str(csv_path),
        "--json",
        str(json_path),
        "--layout",
        "contact_sheet",
        "--middle-count",
        "1",
        "--project-name",
        project_name,
    ]
    braw_adapter = DATA_HELPER_ROOT / "tools" / "braw_adapter"
    if braw_adapter.exists():
        command.extend(["--braw-adapter-path", str(braw_adapter)])
    return command


def _prepend_pythonpath(path: str, current: str | None) -> str:
    if not current:
        return path
    return f"{path}{os.pathsep}{current}"


def _footage_input_path(dm_done: dict[str, Any], label: str) -> Path:
    footage_roots = dm_done.get("replica_footage_roots", {})
    if isinstance(footage_roots, dict) and footage_roots.get(label):
        return Path(str(footage_roots[label]))
    project_roots = dm_done.get("replica_project_roots", {})
    if isinstance(project_roots, dict) and project_roots.get(label):
        return Path(str(project_roots[label])) / "01_Footage"
    raise KeyError(f"replica path not found: {label}")


def _report_output_root(dm_done: dict[str, Any], label: str) -> Path:
    project_roots = dm_done.get("replica_project_roots", {})
    if isinstance(project_roots, dict) and project_roots.get(label):
        return Path(str(project_roots[label])) / "00_Master" / "reports"
    return _footage_input_path(dm_done, label).parents[1] / "00_Master" / "reports"


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m orchestrator.datahelper_worker RUN_ID", file=sys.stderr)
        return 2
    run_datahelper(args[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
