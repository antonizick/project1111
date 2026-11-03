"""Resumable, hash-verified model downloads (spec R9, S9).

HTTPS only. A file is streamed into ``<name>.part`` while its SHA-256 is computed, resumed with a
``Range`` request after an interruption, and renamed into place only when size and hash match the
manifest; a mismatch deletes the partial file. Redirects are followed by hand so that a token is
sent only to the host it belongs to, never to the CDN a redirect points at.
"""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import stat
import threading
import time
import tomllib
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import IO
from urllib.parse import urljoin, urlsplit

import httpx

from p11 import paths

CHUNK = 1 << 20
#: Free space left over after every download, so the desktop never ends up on a full disk.
SPACE_MARGIN = 1 << 30
MAX_REDIRECTS = 10
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})

#: ``(label, bytes done, bytes total)``; called at most once per chunk.
Progress = Callable[[str, int, int], None]


class DownloadError(RuntimeError):
    """A download failed; the message is plain English with a hint."""


class HashMismatchError(DownloadError):
    pass


class DiskSpaceError(DownloadError):
    pass


class SecretsError(RuntimeError):
    pass


@dataclass(frozen=True)
class DownloadItem:
    url: str
    dest: Path
    #: ``None`` only for user-added URLs (``p11 models add``), which have no pinned hash or size.
    sha256: str | None
    size: int | None
    label: str = ""

    @property
    def part(self) -> Path:
        return self.dest.with_name(self.dest.name + ".part")

    @property
    def name(self) -> str:
        return self.label or self.dest.name


def secrets_file() -> Path:
    return paths.config_dir() / "secrets.toml"


def load_tokens(path: Path | None = None) -> dict[str, str]:
    """Host → token from ``secrets.toml`` (``[tokens] "huggingface.co" = "…"``), S9.

    The file must be ``0600``; a file readable by others is refused rather than used.
    """
    path = path or secrets_file()
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        return {}
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise SecretsError(
            f"{path} is readable by other users. Run `chmod 600 {path}`; P11 does not use "
            "tokens from a file others can read."
        )
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError:
        raise SecretsError(f"{path} is not valid TOML.") from None
    tokens = data.get("tokens", {})
    if not isinstance(tokens, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in tokens.items()
    ):
        raise SecretsError(f'{path}: [tokens] must map host names to strings, e.g. "host" = "…".')
    return {k.lower(): v for k, v in tokens.items()}


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1000 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1000
    raise AssertionError("unreachable")


def sha256_file(path: Path, chunk: int = CHUNK) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def _write(f: IO[bytes], block: bytes) -> None:
    f.write(block)


class _Retry(Exception):
    """A transient failure: back off and resume."""


class Downloader:
    def __init__(
        self,
        *,
        tokens: Mapping[str, str] | None = None,
        client: httpx.Client | None = None,
        retries: int = 4,
        backoff: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
        per_host: int = 2,
        insecure_hosts: Iterable[str] = (),
        free_space: Callable[[Path], int] | None = None,
        timeout: float = 30.0,
    ) -> None:
        insecure = frozenset(h.lower() for h in insecure_hosts)
        if not insecure <= LOOPBACK:
            raise ValueError("plain http is only allowed to loopback test servers")
        self._insecure = insecure
        self._tokens = {k.lower(): v for k, v in (tokens or {}).items()}
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(timeout, read=timeout * 4), follow_redirects=False
        )
        self._retries = retries
        self._backoff = backoff
        self._sleep = sleep
        self._per_host = per_host
        self._host_slots: dict[str, threading.BoundedSemaphore] = {}
        self._slots_lock = threading.Lock()
        self._free_space = free_space or (lambda p: shutil.disk_usage(p).free)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Downloader:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- planning --------------------------------------------------------------------------

    @staticmethod
    def remaining(item: DownloadItem) -> int:
        """Bytes still to fetch, counting a partial file that can be resumed."""
        if item.dest.exists() or item.size is None:
            return 0
        try:
            have = item.part.stat().st_size
        except FileNotFoundError:
            have = 0
        return item.size - have if have <= item.size else item.size

    def check_space(self, items: Sequence[DownloadItem]) -> None:
        """Refuse before starting when the target disk cannot hold everything plus a margin."""
        need: dict[int, tuple[Path, int]] = {}
        for item in items:
            folder = item.dest.parent
            folder.mkdir(parents=True, exist_ok=True)
            dev = folder.stat().st_dev
            path, total = need.get(dev, (folder, 0))
            need[dev] = (path, total + self.remaining(item))
        for folder, total in need.values():
            if total == 0:
                continue
            free = self._free_space(folder)
            if free < total + SPACE_MARGIN:
                raise DiskSpaceError(
                    f"Not enough disk space in {folder}: the download needs {human_size(total)} "
                    f"plus {human_size(SPACE_MARGIN)} spare, {human_size(free)} is free. "
                    "Free some space or move the models directory (models_root in config.toml)."
                )

    # -- fetching ----------------------------------------------------------------------------

    def fetch_all(
        self, items: Sequence[DownloadItem], progress: Progress | None = None, workers: int = 3
    ) -> list[Path]:
        self.check_space(items)
        if len(items) <= 1 or workers <= 1:
            return [self.fetch(i, progress, check_space=False) for i in items]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self.fetch, i, progress, check_space=False) for i in items]
            return [f.result() for f in futures]

    def fetch(
        self, item: DownloadItem, progress: Progress | None = None, *, check_space: bool = True
    ) -> Path:
        """Download ``item`` (resuming a ``.part``) and return its verified final path."""
        if item.dest.exists():
            return item.dest
        if check_space:
            self.check_space([item])
        host = self._check_url(item.url)
        with self._slot(host):
            for attempt in range(self._retries + 1):
                try:
                    return self._attempt(item, progress)
                except _Retry as exc:
                    if attempt == self._retries:
                        raise DownloadError(
                            f"Download of {item.name} kept failing ({exc}). Check the network and "
                            "run the same command again: it resumes where it stopped."
                        ) from None
                    self._sleep(self._backoff * 2**attempt)
        raise AssertionError("unreachable")

    def _slot(self, host: str) -> threading.BoundedSemaphore:
        with self._slots_lock:
            return self._host_slots.setdefault(host, threading.BoundedSemaphore(self._per_host))

    def _check_url(self, url: str) -> str:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if not host:
            raise DownloadError(f"Not a download URL: {url!r}")
        if parts.scheme == "https" or (parts.scheme == "http" and host in self._insecure):
            return host
        raise DownloadError(f"Refusing a non-HTTPS download: {parts.scheme}://{host}/…")

    def _headers(self, url: str, offset: int) -> dict[str, str]:
        headers = {"Accept-Encoding": "identity", "User-Agent": "p11-model-manager"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        token = self._tokens.get((urlsplit(url).hostname or "").lower())
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _attempt(self, item: DownloadItem, progress: Progress | None) -> Path:
        item.dest.parent.mkdir(parents=True, exist_ok=True)
        part = item.part
        offset = part.stat().st_size if part.exists() else 0
        if item.size is not None and offset > item.size:
            part.unlink()
            offset = 0
        hasher = hashlib.sha256()
        if offset:
            with part.open("rb") as f:
                while block := f.read(CHUNK):
                    hasher.update(block)
        if offset and offset == item.size:
            return self._finish(item, hasher.hexdigest())

        url = item.url
        try:
            for _ in range(MAX_REDIRECTS + 1):
                self._check_url(url)
                request = self._client.build_request("GET", url, headers=self._headers(url, offset))
                response = self._client.send(request, stream=True)
                try:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise DownloadError(f"{item.name}: redirect without a location.")
                        url = urljoin(url, location)
                        continue
                    return self._receive(item, response, offset, hasher, progress)
                finally:
                    response.close()
        except httpx.TransportError as exc:
            raise _Retry(type(exc).__name__) from None
        raise DownloadError(f"{item.name}: too many redirects.")

    def _receive(
        self,
        item: DownloadItem,
        response: httpx.Response,
        offset: int,
        hasher: hashlib._Hash,
        progress: Progress | None,
    ) -> Path:
        code = response.status_code
        if code == 416 and offset:
            # The server says our partial file is not a prefix it can resume: start over.
            item.part.unlink(missing_ok=True)
            raise _Retry("resume refused")
        if code in (429,) or code >= 500:
            raise _Retry(f"HTTP {code}")
        if code in (401, 403):
            raise DownloadError(
                f"{item.name}: the host refused access (HTTP {code}). This file needs a login; "
                "see the user guide on optional models and secrets.toml."
            )
        if code == 404:
            raise DownloadError(
                f"{item.name}: the file is no longer at its source (HTTP 404). The manifest entry "
                "needs updating; report it or pick another model."
            )
        if code not in (200, 206):
            raise DownloadError(f"{item.name}: unexpected HTTP {code} from the host.")
        if code == 200 and offset:
            offset = 0  # the server ignored Range: restart from byte 0
            hasher = hashlib.sha256()
        elif code == 206:
            start = _content_range_start(response.headers.get("content-range", ""))
            if start != offset:
                item.part.unlink(missing_ok=True)
                raise _Retry("resume offset mismatch")

        done = offset
        total = item.size or int(response.headers.get("content-length", 0)) + offset
        try:
            with item.part.open("ab" if offset else "wb") as f:
                for block in response.iter_bytes(CHUNK):
                    if item.size is not None and done + len(block) > item.size:
                        f.close()
                        item.part.unlink(missing_ok=True)
                        raise HashMismatchError(
                            f"{item.name}: the host sent more data than the manifest's "
                            f"{item.size} bytes; the partial file was deleted."
                        )
                    _write(f, block)
                    hasher.update(block)
                    done += len(block)
                    if progress:
                        progress(item.name, done, total)
                f.flush()
                os.fsync(f.fileno())
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                raise DiskSpaceError(
                    f"The disk filled up while downloading {item.name}. Free some space and run "
                    "the same command again: it resumes where it stopped."
                ) from None
            raise
        if done < (item.size or total):
            raise _Retry("connection closed early")
        return self._finish(item, hasher.hexdigest())

    @staticmethod
    def _finish(item: DownloadItem, digest: str) -> Path:
        if item.sha256 is not None and digest != item.sha256:
            item.part.unlink(missing_ok=True)
            raise HashMismatchError(
                f"{item.name}: SHA-256 mismatch (expected {item.sha256[:12]}…, got "
                f"{digest[:12]}…). The file was deleted; P11 never keeps an unverified model. "
                "Try again later; if it persists the source changed and the manifest needs "
                "updating."
            )
        os.replace(item.part, item.dest)
        return item.dest


def _content_range_start(value: str) -> int | None:
    # "bytes 100-199/200"
    try:
        unit, rest = value.split(" ", 1)
        if unit != "bytes":
            return None
        return int(rest.split("-", 1)[0])
    except ValueError:
        return None
