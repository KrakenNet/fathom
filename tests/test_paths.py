"""Tests for ruleset path jailing."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from fathom.integrations.paths import PathJailError, resolve_ruleset

if TYPE_CHECKING:
    from pathlib import Path


class TestResolveRuleset:
    def test_relative_inside_root(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        target = rules_dir / "ok.yaml"
        target.write_text("")
        result = resolve_ruleset(str(rules_dir), "ok.yaml")
        assert result == target.resolve()

    def test_subdirectory(self, tmp_path: Path) -> None:
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "b.yaml").write_text("")
        result = resolve_ruleset(str(tmp_path), "a/b.yaml")
        assert result == (tmp_path / "a" / "b.yaml").resolve()

    def test_rejects_parent_traversal(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        with pytest.raises(PathJailError, match="invalid ruleset path"):
            resolve_ruleset(str(rules_dir), "../etc/passwd")

    def test_rejects_absolute_path(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        with pytest.raises(PathJailError, match="invalid ruleset path"):
            resolve_ruleset(str(rules_dir), "/etc/passwd")

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="drive-relative paths are Windows-specific",
    )
    def test_rejects_drive_relative_windows(self, tmp_path: Path) -> None:
        """On Windows, ``Path('C:foo').is_absolute()`` is False — must still be rejected."""
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        with pytest.raises(PathJailError, match="invalid ruleset path"):
            resolve_ruleset(str(rules_dir), "C:foo")

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="drive-relative paths are Windows-specific",
    )
    def test_rejects_drive_relative_with_traversal(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        with pytest.raises(PathJailError, match="invalid ruleset path"):
            resolve_ruleset(str(rules_dir), "C:..\\secrets.yaml")

    def test_rejects_deep_parent_traversal(self, tmp_path: Path) -> None:
        """Verifies relative_to containment reliably blocks '..' escape (Windows-reachable)."""
        rules_dir = tmp_path / "rules" / "nested"
        rules_dir.mkdir(parents=True)
        with pytest.raises(PathJailError, match="invalid ruleset path"):
            resolve_ruleset(str(rules_dir), "../../outside.yaml")

    def test_rejects_symlink_escape(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        outside = tmp_path / "outside.yaml"
        outside.write_text("")
        link = rules_dir / "link.yaml"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")
        with pytest.raises(PathJailError, match="invalid ruleset path"):
            resolve_ruleset(str(rules_dir), "link.yaml")

    def test_missing_root_raises(self, tmp_path: Path) -> None:
        with pytest.raises(PathJailError, match="ruleset root"):
            resolve_ruleset(str(tmp_path / "missing"), "x.yaml")
