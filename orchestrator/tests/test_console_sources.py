from __future__ import annotations

from pathlib import Path

from orchestrator.web.sources import list_source_candidates


def test_list_source_candidates_returns_directories(tmp_path: Path) -> None:
    card = tmp_path / "CARD_A001"
    card.mkdir()
    (tmp_path / ".timemachine").mkdir()
    (tmp_path / "Macintosh HD").mkdir()
    (tmp_path / "not-a-card.txt").write_text("x", encoding="utf-8")

    candidates = list_source_candidates((tmp_path,))

    assert len(candidates) == 1
    assert candidates[0]["name"] == "CARD_A001"
    assert candidates[0]["path"] == str(card)
    assert candidates[0]["available"] is True
    assert isinstance(candidates[0]["total_bytes"], int)
    assert isinstance(candidates[0]["free_bytes"], int)


def test_list_source_candidates_ignores_missing_roots(tmp_path: Path) -> None:
    candidates = list_source_candidates((tmp_path / "missing",))

    assert candidates == []
