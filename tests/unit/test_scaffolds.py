"""Unit tests for the template-repo fetch (mock transport, no network)."""

import gzip
import io
import tarfile

import pytest

from krci_testkit.scaffolds import template_files
from tests.unit.vcs_mock import raw_transport


def _tarball(entries: dict[str, bytes], root: str = "owner-repo-abc123") -> bytes:
    """A GitHub-shaped tarball: every path nested under one '<owner>-<repo>-<sha>/' root."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for path, content in entries.items():
            info = tarfile.TarInfo(f"{root}/{path}")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return gzip.compress(buf.getvalue())


def _transport(payload: bytes):
    return raw_transport(payload, expect_path="/repos/epmd-edp/go-go-gin/tarball")


def test_template_files_strips_root_and_keeps_text_and_binary():
    payload = _tarball(
        {
            "go.mod": b"module app\n",
            "gradle/wrapper/gradle-wrapper.jar": b"\x00\x01\x02binary",
        }
    )
    files = template_files(
        "https://github.com/epmd-edp/go-go-gin.git", transport=_transport(payload)
    )
    assert files["go.mod"] == "module app\n"
    assert files["gradle/wrapper/gradle-wrapper.jar"] == b"\x00\x01\x02binary"


def test_template_files_rejects_non_github_source():
    with pytest.raises(ValueError, match="github.com"):
        template_files("https://example.com/git/repo.git")
