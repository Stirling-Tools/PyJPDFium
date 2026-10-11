"""OCR model profiles on disk: find one, and check its files against the digests it pins.

Pure Python, so it runs before any native code loads. Opening an OcrEngine checks the same
digests again natively.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from .errors import InvalidArgumentError

StrPath = Union[str, "os.PathLike[str]"]
PROFILE_ENV = "PYJPDFIUM_OCR_PROFILE"
MANIFEST = "profile.txt"


@dataclass(frozen=True)
class ProfileFile:
    role: str
    name: str
    sha256: str


@dataclass(frozen=True)
class Profile:
    id: str
    directory: Path
    files: tuple[ProfileFile, ...]


def default_profile_dir() -> Path | None:
    configured = os.environ.get(PROFILE_ENV)
    return Path(configured) if configured else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_profile(directory: StrPath) -> Profile:
    """Parses a fetched profile directory's manifest without checking digests."""
    directory = Path(directory)
    manifest = directory / MANIFEST
    if not manifest.is_file():
        raise InvalidArgumentError(f"{directory} is not a fetched OCR profile: no {MANIFEST}")
    profile_id, files = "", []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if fields[:1] == ["id"] and len(fields) == 2:
            profile_id = fields[1]
        elif fields[:1] in (["file"], ["derived"]) and len(fields) >= 4:
            files.append(ProfileFile(fields[1], fields[2], fields[3]))
    if not profile_id or not files:
        raise InvalidArgumentError(f"{manifest} names no profile id or files")
    return Profile(profile_id, directory, tuple(files))


def verify_profile(directory: StrPath) -> Profile:
    """Checks every pinned file; raises InvalidArgumentError naming the first that fails."""
    profile = read_profile(directory)
    for item in profile.files:
        path = profile.directory / item.name
        if not path.is_file():
            raise InvalidArgumentError(f"OCR profile file {path} is missing")
        if sha256_file(path) != item.sha256:
            raise InvalidArgumentError(f"OCR profile file {path} does not match its pinned digest")
    return profile
