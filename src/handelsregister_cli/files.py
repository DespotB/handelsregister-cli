"""Filename sanitising and checksum-based deduplication.

The DK tree lists the same physical PDF under several folders, and distinct
documents can share a label. Writing therefore goes through :class:`FileSink`,
which skips byte-identical duplicates and suffixes name collisions.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .models import Download

# Magic bytes we accept as "this is a real document, not an error page".
_MAGIC = (b"%PDF", b"PK\x03\x04", b"<?xml")


def looks_like_document(data: bytes) -> bool:
    """True if *data* starts like a PDF, ZIP or XML file (not an HTML page)."""
    return any(data[: len(m)] == m for m in _MAGIC)


def guess_extension(data: bytes) -> str:
    if data[:4] == b"%PDF":
        return ".pdf"
    if data[:4] == b"PK\x03\x04":
        return ".zip"
    if data[:5] == b"<?xml":
        return ".xml"
    return ".bin"


def clean_label(label: str) -> str:
    """Turn a tree/link label into a filesystem-safe base name."""
    name = label.replace("/", " - ")
    name = re.sub(r'[\\:*?"<>|]', "-", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:120] or "dokument"


class FileSink:
    """Writes downloads into a directory with dedupe + collision handling."""

    def __init__(self, outdir: Path):
        self.outdir = Path(outdir)
        self.outdir.mkdir(parents=True, exist_ok=True)
        self._seen_hashes: dict = {}  # sha256 -> filename already written
        self._used_names: set = set()

    def write(self, label: str, data: bytes, source: str) -> Download | None:
        """Save *data* under a clean name derived from *label*.

        Returns the resulting :class:`Download`, or ``None`` if an identical
        file (same SHA-256) was already written.
        """
        digest = hashlib.sha256(data).hexdigest()
        if digest in self._seen_hashes:
            return None

        base = clean_label(label)
        ext = guess_extension(data)
        name = base + ext
        n = 2
        while name in self._used_names:
            name = f"{base} ({n}){ext}"
            n += 1

        path = self.outdir / name
        path.write_bytes(data)
        self._seen_hashes[digest] = name
        self._used_names.add(name)
        return Download(label=label, path=path, size=len(data), sha256=digest, source=source)
