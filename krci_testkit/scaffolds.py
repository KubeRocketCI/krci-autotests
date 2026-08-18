"""Fetch a public source repo's file tree as {path: content} — the provider-neutral
seed for an import source (a repo the PLATFORM did not shape), pushed through the
VCSProvider.create_repo verb. Pure HTTP: no git binary, no SSH.

Only GitHub sources are supported because the platform's own template repos live
there (Stack.template_repo_url); the GitServer under test plays no part in the
fetch, so the seed works identically against every provider.
"""

import io
import logging
import re
import tarfile
from functools import cache

import httpx

from krci_testkit.clients.protocol import DEFAULT_REQUEST_TIMEOUT, http_client

log = logging.getLogger(__name__)

_GITHUB_REPO_URL = re.compile(r"https://github\.com/(?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?/?$")

# A template repo is a scaffold, not a payload: a tarball beyond this size is a
# wrong URL or a runaway repo, and buffering it in memory would be the symptom.
_MAX_TARBALL_BYTES = 50 * 1024 * 1024


def template_files(
    repo_url: str,
    *,
    token: str | None = None,
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, str | bytes]:
    """The repo's default-branch files, keyed by path — a faithful copy, never
    edited on the way through. Cached per URL for the process lifetime (each
    xdist worker fetches independently); entry count is bounded by the distinct
    source URLs a run touches, in practice the catalog.

    token authenticates against api.github.com (anonymous is ~60 calls/hour/IP —
    a catalog sweep exceeds it). Text decodes to str; everything else stays bytes
    (a gradle wrapper jar is part of the scaffold and CI needs it) — create_repo
    transports either.
    """
    return dict(_fetch(repo_url, token, request_timeout, transport))


@cache
def _fetch(
    repo_url: str,
    token: str | None,
    request_timeout: float,
    transport: httpx.BaseTransport | None,
) -> dict[str, str | bytes]:
    match = _GITHUB_REPO_URL.match(repo_url)
    if not match:
        raise ValueError(f"not a github.com repo URL: {repo_url!r}")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with (
        http_client(
            "https://api.github.com",
            headers,
            verify=True,
            transport=transport,
            request_timeout=request_timeout,
            follow_redirects=True,
        ) as client,
        client.stream("GET", f"/repos/{match['owner']}/{match['name']}/tarball") as resp,
    ):
        resp.raise_for_status()
        # Streamed so the cap bounds memory DURING the download, not after the
        # whole body already landed in it.
        chunks: list[bytes] = []
        received = 0
        for chunk in resp.iter_bytes():
            received += len(chunk)
            if received > _MAX_TARBALL_BYTES:
                raise ValueError(f"tarball of {repo_url} exceeds {_MAX_TARBALL_BYTES} bytes")
            chunks.append(chunk)
    files: dict[str, str | bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(b"".join(chunks)), mode="r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            # GitHub tarballs nest everything under one "<owner>-<repo>-<sha>/" root
            path = member.name.split("/", 1)[1] if "/" in member.name else member.name
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            raw = extracted.read()
            # git's own text/binary heuristic: a NUL byte means binary. Decoding
            # alone is not enough — UTF-8 happily decodes control bytes, which
            # would ship a jar as mangled "text".
            if b"\x00" in raw:
                files[path] = raw
                continue
            try:
                files[path] = raw.decode()
            except UnicodeDecodeError:
                files[path] = raw
    log.info("fetched %d files from %s", len(files), repo_url)
    return files
