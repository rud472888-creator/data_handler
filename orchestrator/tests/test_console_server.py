from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from orchestrator.jsonio import write_json
from orchestrator.app_front.settings import SettingsStore
from orchestrator.web.server import create_app


def _client(tmp_path: Path) -> TestClient:
    source_root = tmp_path / "sources"
    runs_root = tmp_path / "runs"
    source_root.mkdir()
    runs_root.mkdir()
    app = create_app(
        registry_path=tmp_path / "console-registry.json",
        source_roots=(source_root,),
        runs_root=runs_root,
    )
    return TestClient(app)


def _replica_paths(tmp_path: Path) -> tuple[Path, Path]:
    path1 = tmp_path / "path1"
    path2 = tmp_path / "path2"
    path1.mkdir()
    path2.mkdir()
    return path1, path2


def _create_project(client: TestClient, path1: Path, path2: Path) -> dict[str, object]:
    return client.post(
        "/api/projects",
        json={
            "name": "No Perfect Movie",
            "replica_roots": [str(path1), str(path2)],
        },
    ).json()["project"]


def test_console_health(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/console/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_console_home_is_data_handler_app(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert "Data Handler" in response.text


def test_console_disks_endpoint(tmp_path: Path) -> None:
    disk_root = tmp_path / "Volumes"
    disk_root.mkdir()
    (disk_root / ".timemachine").mkdir()
    (disk_root / "DIT_RAID").mkdir()
    app = create_app(
        registry_path=tmp_path / "console-registry.json",
        source_roots=(tmp_path / "sources",),
        runs_root=tmp_path / "runs",
        disk_root=disk_root,
    )
    client = TestClient(app)

    response = client.get("/api/disks")

    assert response.status_code == 200
    assert [disk["name"] for disk in response.json()["disks"]] == ["DIT_RAID"]


def test_console_unmount_endpoint_returns_refreshed_disks(monkeypatch, tmp_path: Path) -> None:
    disk_root = tmp_path / "Volumes"
    volume = disk_root / "DIT_RAID"
    volume.mkdir(parents=True)

    def fake_unmount(path: str, *, mount_root: Path) -> dict[str, str]:
        volume.rmdir()
        return {"path": path, "status": "ejected"}

    monkeypatch.setattr("orchestrator.web.server.unmount_disk", fake_unmount)
    app = create_app(
        registry_path=tmp_path / "console-registry.json",
        source_roots=(tmp_path / "sources",),
        runs_root=tmp_path / "runs",
        disk_root=disk_root,
    )
    client = TestClient(app)

    response = client.post("/api/disks/unmount", json={"path": str(volume)})

    assert response.status_code == 200
    assert response.json()["status"] == "ejected"
    assert response.json()["disks"] == []


def test_console_settings_round_trip(tmp_path: Path) -> None:
    app = create_app(
        registry_path=tmp_path / "console-registry.json",
        source_roots=(tmp_path / "sources",),
        runs_root=tmp_path / "runs",
        settings_store=SettingsStore(tmp_path / "settings.json"),
    )
    client = TestClient(app, base_url="http://127.0.0.1:9010")

    response = client.put(
        "/api/console/settings",
        json={"preferred_port": 9020},
    )
    read_response = client.get("/api/console/settings")

    assert response.status_code == 200
    assert response.json()["settings"] == {
        "preferred_port": 9020,
    }
    assert response.json()["server"]["port"] == 9010
    assert response.json()["server"]["restart_required"] is True
    assert read_response.json()["settings"]["preferred_port"] == 9020


def test_source_listing(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    runs_root = tmp_path / "runs"
    card = source_root / "CARD_A"
    card.mkdir(parents=True)
    runs_root.mkdir()
    client = TestClient(
        create_app(
            registry_path=tmp_path / "console-registry.json",
            source_roots=(source_root,),
            runs_root=runs_root,
        )
    )

    response = client.get("/api/sources")

    assert response.status_code == 200
    assert response.json()["sources"][0]["path"] == str(card)


def test_destination_listing(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    runs_root = tmp_path / "runs"
    disk = source_root / "RAID_A"
    disk.mkdir(parents=True)
    runs_root.mkdir()
    client = TestClient(
        create_app(
            registry_path=tmp_path / "console-registry.json",
            source_roots=(source_root,),
            runs_root=runs_root,
        )
    )

    response = client.get("/api/destinations")

    assert response.status_code == 200
    assert response.json()["destinations"][0]["path"] == str(disk)


def test_artifact_serving(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run-test"
    run_dir.mkdir(parents=True)
    artifact = run_dir / "final-report.md"
    artifact.write_text("# Report\n", encoding="utf-8")
    client = TestClient(
        create_app(
            registry_path=tmp_path / "console-registry.json",
            source_roots=(tmp_path / "sources",),
            runs_root=runs_root,
        )
    )

    list_response = client.get("/api/runs/run-test/artifacts")
    file_response = client.get("/artifacts/run-test/final-report.md")

    assert list_response.status_code == 200
    assert list_response.json()["artifacts"][0]["url"] == "/artifacts/run-test/final-report.md"
    assert file_response.status_code == 200
    assert file_response.text == "# Report\n"


def test_project_create_response(tmp_path: Path) -> None:
    client = _client(tmp_path)
    path1, path2 = _replica_paths(tmp_path)

    response = client.post(
        "/api/projects",
        json={
            "name": "No Perfect Movie",
            "replica_roots": [str(path1), str(path2)],
        },
    )

    assert response.status_code == 200
    project = response.json()["project"]
    assert project["name"] == "No Perfect Movie"
    assert project["replica_roots"] == [str(path1), str(path2)]
    assert (path1 / "No Perfect Movie" / "01_Footage").is_dir()


def test_project_create_rejects_source_outside_allowed_root(tmp_path: Path) -> None:
    client = _client(tmp_path)
    path1, path2 = _replica_paths(tmp_path)
    source = tmp_path / "not-mounted"
    source.mkdir()

    response = client.post(
        "/api/projects",
        json={
            "name": "No Perfect Movie",
            "source_paths": [str(source)],
            "replica_roots": [str(path1), str(path2)],
        },
    )

    assert response.status_code == 400


def test_project_create_rejects_source_that_resolves_outside_allowed_root(tmp_path: Path) -> None:
    client = _client(tmp_path)
    path1, path2 = _replica_paths(tmp_path)
    outside = tmp_path / "not-mounted"
    outside.mkdir()
    symlink = tmp_path / "sources" / "LINK_TO_OUTSIDE"
    symlink.symlink_to(outside, target_is_directory=True)

    response = client.post(
        "/api/projects",
        json={
            "name": "No Perfect Movie",
            "source_paths": [str(symlink)],
            "replica_roots": [str(path1), str(path2)],
        },
    )

    assert response.status_code == 400


def test_project_create_accepts_source_inside_allowed_root(tmp_path: Path) -> None:
    client = _client(tmp_path)
    source_root = tmp_path / "sources"
    source = source_root / "CARD_A"
    source.mkdir()
    path1, path2 = _replica_paths(tmp_path)

    response = client.post(
        "/api/projects",
        json={
            "name": "No Perfect Movie",
            "source_paths": [str(source)],
            "replica_roots": [str(path1), str(path2)],
        },
    )

    assert response.status_code == 200
    assert response.json()["project"]["source_paths"] == [str(source)]


def test_project_create_rejects_path_traversal_name(tmp_path: Path) -> None:
    client = _client(tmp_path)
    path1, path2 = _replica_paths(tmp_path)

    response = client.post(
        "/api/projects",
        json={
            "name": "../outside",
            "replica_roots": [str(path1), str(path2)],
        },
    )

    assert response.status_code == 400
    assert not (tmp_path / "outside").exists()


def test_run_create_passes_shoot_camera_roll_path(monkeypatch, tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    runs_root = tmp_path / "runs"
    source = source_root / "CARD_A"
    source.mkdir(parents=True)
    runs_root.mkdir()
    client = TestClient(
        create_app(
            registry_path=tmp_path / "console-registry.json",
            source_roots=(source_root,),
            runs_root=runs_root,
        )
    )
    path1, path2 = _replica_paths(tmp_path)
    project = _create_project(client, path1, path2)
    starts: list[dict[str, object]] = []

    def fake_start_run(**kwargs: object) -> str:
        starts.append(kwargs)
        return "run-test"

    monkeypatch.setattr("orchestrator.web.server.start_run", fake_start_run)

    response = client.post(
        "/api/runs",
        json={
            "project_id": project["id"],
            "shoot_date": "260528",
            "camera_unit": "A-cam",
            "source_path": str(source),
        },
    )

    assert response.status_code == 200
    assert response.json()["roll"] == "R#1"
    assert starts[0]["run_id"] == response.json()["run_id"]
    assert starts[0]["footage_run_name"] == "260528/A-cam/R#1"
    assert starts[0]["replica_paths"] == (path1, path2)
    assert len(client.get("/api/projects").json()["runs"]) == 1


def test_run_create_accepts_multiple_sources_and_destinations(monkeypatch, tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    runs_root = tmp_path / "runs"
    source1 = source_root / "CARD_A"
    source2 = source_root / "CARD_B"
    source1.mkdir(parents=True)
    source2.mkdir(parents=True)
    runs_root.mkdir()
    client = TestClient(
        create_app(
            registry_path=tmp_path / "console-registry.json",
            source_roots=(source_root,),
            runs_root=runs_root,
        )
    )
    path1, path2 = _replica_paths(tmp_path)
    project = _create_project(client, path1, path2)
    starts: list[dict[str, object]] = []
    monkeypatch.setattr(
        "orchestrator.web.server.start_run",
        lambda **kwargs: starts.append(kwargs) or str(kwargs["run_id"]),
    )

    response = client.post(
        "/api/runs",
        json={
            "project_id": project["id"],
            "shoot_date": "260528",
            "camera_unit": "A-cam",
            "source_paths": [str(source1), str(source2)],
            "replica_roots": [str(path2)],
        },
    )

    assert response.status_code == 200
    assert starts[0]["source_paths"] == (source1, source2)
    assert starts[0]["replica_paths"] == (path2,)
    run = client.get("/api/projects").json()["runs"][0]
    assert run["source_paths"] == [str(source1), str(source2)]


def test_roll_preview_shows_replica_destinations(tmp_path: Path) -> None:
    client = _client(tmp_path)
    path1, path2 = _replica_paths(tmp_path)
    project = _create_project(client, path1, path2)
    (path1 / "No Perfect Movie" / "01_Footage" / "260528" / "A-cam" / "R#1").mkdir(
        parents=True
    )

    response = client.post(
        "/api/roll-preview",
        json={"project_id": project["id"], "shoot_date": "260528", "camera_unit": "A-cam"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["roll"] == "R#2"
    assert payload["replica_destinations"] == [
        str(path1 / "No Perfect Movie" / "01_Footage" / "260528" / "A-cam" / "R#2"),
        str(path2 / "No Perfect Movie" / "01_Footage" / "260528" / "A-cam" / "R#2"),
    ]


def test_run_create_rejects_existing_manual_source_outside_allowed_root(
    monkeypatch, tmp_path: Path
) -> None:
    client = _client(tmp_path)
    path1, path2 = _replica_paths(tmp_path)
    source = tmp_path / "not-mounted"
    source.mkdir()
    project = _create_project(client, path1, path2)
    starts: list[dict[str, object]] = []
    monkeypatch.setattr(
        "orchestrator.web.server.start_run",
        lambda **kwargs: starts.append(kwargs) or str(kwargs["run_id"]),
    )

    response = client.post(
        "/api/runs",
        json={
            "project_id": project["id"],
            "shoot_date": "260528",
            "camera_unit": "A-cam",
            "source_path": str(source),
        },
    )

    assert response.status_code == 400
    assert starts == []


def test_run_create_rejects_missing_manual_source(tmp_path: Path) -> None:
    client = _client(tmp_path)
    path1, path2 = _replica_paths(tmp_path)
    project = _create_project(client, path1, path2)

    response = client.post(
        "/api/runs",
        json={
            "project_id": project["id"],
            "shoot_date": "260528",
            "camera_unit": "A-cam",
            "source_path": str(tmp_path / "missing"),
        },
    )

    assert response.status_code == 400


def test_artifact_serving_rejects_event_path_outside_allowed_roots(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run-test"
    events = run_dir / "events"
    events.mkdir(parents=True)
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    write_json(
        events / "datahelper.done.json",
        {"reports": [{"label": "path1", "json_path": str(secret)}]},
    )
    client = TestClient(
        create_app(
            registry_path=tmp_path / "console-registry.json",
            source_roots=(tmp_path / "sources",),
            runs_root=runs_root,
        )
    )

    list_response = client.get("/api/runs/run-test/artifacts")
    file_response = client.get("/artifacts/run-test/secret.txt")

    assert list_response.status_code == 200
    assert list_response.json()["artifacts"] == []
    assert file_response.status_code == 404
