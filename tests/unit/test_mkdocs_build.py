"""MkDocs build runner against a throwaway git repository (no real MkDocs)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from opentrons_knowledge.docs.mkdocs_build import build_environment, build_site
from opentrons_knowledge.errors import DocsBuildError
from opentrons_knowledge.models.manifest import RenderedDocsConfig

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("make") is None, reason="needs git and make"
)

MAKEFILE = """\
.PHONY: build
build:
\tmkdir -p site
\tprintf '%s|%s|%s|%s' "$$(cat VERSION)" "$$CI" "$$UV_PYTHON" \\
\t\t"$${VIRTUAL_ENV:-none}" > site/index.html

.PHONY: fail
fail:
\t@echo "mkdocs exploded: Config value 'nav' is invalid"
\t@exit 3

.PHONY: dirty
dirty: build
\techo changed >> mkdocs.yml
"""


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "opentrons"
    (root / "docs").mkdir(parents=True)
    (root / "other").mkdir()
    (root / "docs" / "Makefile").write_text(MAKEFILE, encoding="utf-8")
    (root / "docs" / "mkdocs.yml").write_text("site_name: Fixture\n", encoding="utf-8")
    (root / "docs" / "VERSION").write_text("v1", encoding="utf-8")
    (root / "other" / "big.txt").write_text("not needed by docs", encoding="utf-8")
    _git(root, "init", "--quiet", "--initial-branch=main")
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "v1")
    _git(root, "tag", "docs-v1")
    (root / "docs" / "VERSION").write_text("v2", encoding="utf-8")
    _git(root, "commit", "--quiet", "-am", "v2")
    return root


def _settings(**overrides: object) -> RenderedDocsConfig:
    values: dict[str, object] = {
        "setup_command": ["sh", "-c", "echo setup"],
        "sparse_paths": ["docs"],
        "allowed_modifications": [],
        **overrides,
    }
    return RenderedDocsConfig.model_validate(values)


def test_pinned_build_renders_requested_revision_in_isolation(repo: Path, tmp_path: Path) -> None:
    site = build_site(
        repository="https://github.com/Opentrons/opentrons",
        ref="docs-v1",
        settings=_settings(),
        work_root=tmp_path / "work",
        local_repo=repo,
    )
    assert site.commit == _git(repo, "rev-parse", "docs-v1")
    assert site.ref == "docs-v1"
    assert not site.dirty and not site.reused
    assert (site.site_dir / "index.html").read_text(encoding="utf-8") == "v1|true|3.12|none"
    assert site.checkout != repo
    assert not (site.checkout / "other").exists(), "sparse checkout should only include docs/"
    assert not (repo / "docs" / "site").exists(), "developer checkout must not be touched"
    assert _git(repo, "status", "--porcelain") == ""
    assert site.log_path is not None and "make build" in site.log_path.read_text(encoding="utf-8")


def test_build_reuses_matching_stamp_and_rebuilds_on_request(repo: Path, tmp_path: Path) -> None:
    kwargs = {
        "repository": "https://github.com/Opentrons/opentrons",
        "ref": "main",
        "settings": _settings(),
        "work_root": tmp_path / "work",
        "local_repo": repo,
    }
    first = build_site(**kwargs)  # type: ignore[arg-type]
    assert (first.site_dir / "index.html").read_text(encoding="utf-8").startswith("v2|")
    second = build_site(**kwargs)  # type: ignore[arg-type]
    assert second.reused and second.commit == first.commit
    third = build_site(**kwargs, rebuild=True)  # type: ignore[arg-type]
    assert not third.reused


def test_build_failure_reports_command_and_log_tail(repo: Path, tmp_path: Path) -> None:
    with pytest.raises(DocsBuildError) as info:
        build_site(
            repository="https://github.com/Opentrons/opentrons",
            ref="main",
            settings=_settings(build_command=["make", "fail"]),
            work_root=tmp_path / "work",
            local_repo=repo,
        )
    message = str(info.value)
    assert "exit 2" in message or "exit 3" in message
    assert "make fail" in message
    assert "Config value 'nav' is invalid" in message


def test_unknown_revision_fails_clearly(repo: Path, tmp_path: Path) -> None:
    with pytest.raises(DocsBuildError, match="not found"):
        build_site(
            repository="https://github.com/Opentrons/opentrons",
            ref="mkdocs-does-not-exist",
            settings=_settings(),
            work_root=tmp_path / "work",
            local_repo=repo,
        )


def test_missing_tool_fails_clearly(repo: Path, tmp_path: Path) -> None:
    with pytest.raises(DocsBuildError, match="not found on PATH"):
        build_site(
            repository="https://github.com/Opentrons/opentrons",
            ref="main",
            settings=_settings(setup_command=["definitely-not-a-real-tool"]),
            work_root=tmp_path / "work",
            local_repo=repo,
        )


def test_unexpected_source_modification_fails(repo: Path, tmp_path: Path) -> None:
    with pytest.raises(DocsBuildError, match=r"modified tracked files.*docs/mkdocs\.yml"):
        build_site(
            repository="https://github.com/Opentrons/opentrons",
            ref="main",
            settings=_settings(build_command=["make", "dirty"]),
            work_root=tmp_path / "work",
            local_repo=repo,
        )


def test_allowed_modification_is_recorded(repo: Path, tmp_path: Path) -> None:
    site = build_site(
        repository="https://github.com/Opentrons/opentrons",
        ref="main",
        settings=_settings(
            build_command=["make", "dirty"], allowed_modifications=["docs/mkdocs.yml"]
        ),
        work_root=tmp_path / "work",
        local_repo=repo,
    )
    assert site.modified_files == ("docs/mkdocs.yml",)


def test_in_place_build_uses_checkout_head(repo: Path, tmp_path: Path) -> None:
    (repo / "docs" / "VERSION").write_text("local edit", encoding="utf-8")
    site = build_site(
        repository="https://github.com/Opentrons/opentrons",
        ref=None,
        settings=_settings(),
        work_root=tmp_path / "work",
        local_repo=repo,
        in_place=True,
    )
    assert site.checkout == repo.resolve()
    assert site.dirty
    assert (site.site_dir / "index.html").read_text(encoding="utf-8").startswith("local edit|")


def test_in_place_rejects_other_ref(repo: Path, tmp_path: Path) -> None:
    with pytest.raises(DocsBuildError, match="--in-place builds the checkout's HEAD"):
        build_site(
            repository="https://github.com/Opentrons/opentrons",
            ref="docs-v1",
            settings=_settings(),
            work_root=tmp_path / "work",
            local_repo=repo,
            in_place=True,
        )


def test_environment_mirrors_ci_and_scrubs_caller_venv() -> None:
    env = build_environment(
        RenderedDocsConfig(),
        {"PATH": "/bin", "VIRTUAL_ENV": "/knowledge/.venv", "PYTHONPATH": "x"},
    )
    assert env == {"PATH": "/bin", "UV_PYTHON": "3.12", "CI": "true"}
    assert "CI" not in build_environment(RenderedDocsConfig(strict=False), {"PATH": "/bin"})
