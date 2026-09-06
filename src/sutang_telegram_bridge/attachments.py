from __future__ import annotations

import asyncio
import grp
import os
import re
import shutil
import stat
import tarfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .telegram import TelegramClient


@dataclass(frozen=True)
class Attachment:
    kind: str
    original_name: str
    path: Path
    extracted: tuple[Path, ...] = ()


def media_file_ids(message: dict[str, Any]) -> list[tuple[str, str]]:
    assets: list[tuple[str, str]] = []
    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        assets.append(("photo", str(photos[-1]["file_id"])))
    for key, kind in (("animation", "animation"), ("sticker", "sticker")):
        item = message.get(key)
        if isinstance(item, dict) and item.get("file_id"):
            assets.append((kind, str(item["file_id"])))
    return assets


def _specs(message: dict[str, Any]) -> list[tuple[str, str, str, int | None]]:
    result: list[tuple[str, str, str, int | None]] = []
    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        item = photos[-1]
        result.append(("photo", str(item["file_id"]), "photo.jpg", item.get("file_size")))
    for key in ("document", "animation", "sticker", "voice", "audio"):
        item = message.get(key)
        if not isinstance(item, dict) or not item.get("file_id"):
            continue
        default = {
            "document": "document.bin",
            "animation": "animation.gif",
            "sticker": "sticker.webp",
            "voice": "voice.ogg",
            "audio": "audio.bin",
        }[key]
        result.append(
            (
                key,
                str(item["file_id"]),
                str(item.get("file_name") or default),
                int(item["file_size"]) if item.get("file_size") is not None else None,
            )
        )
    return result


def safe_name(name: str) -> str:
    clean = Path(name.replace("\\", "/")).name
    clean = re.sub(r"[^A-Za-z0-9._()\-\u4e00-\u9fff]+", "_", clean).strip("._")
    return clean[:160] or "attachment.bin"


def _inside(root: Path, member: str) -> Path:
    if not member or member.startswith(("/", "\\")):
        raise ValueError("archive contains an absolute or empty path")
    destination = (root / member).resolve()
    if not destination.is_relative_to(root.resolve()):
        raise ValueError("archive path traversal rejected")
    return destination


def _safe_extract_zip(path: Path, root: Path, max_files: int, max_bytes: int) -> tuple[Path, ...]:
    extracted: list[Path] = []
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        files = [item for item in members if not item.is_dir()]
        if len(members) > max_files or sum(item.file_size for item in files) > max_bytes:
            raise ValueError("archive exceeds configured expansion limits")
        for item in members:
            mode = item.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError("archive links and special files are not allowed")
            target = _inside(root, item.filename)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, 64 * 1024)
            target.chmod(0o600)
            extracted.append(target)
    return tuple(extracted)


def _safe_extract_tar(path: Path, root: Path, max_files: int, max_bytes: int) -> tuple[Path, ...]:
    extracted: list[Path] = []
    with tarfile.open(path, "r:*") as archive:
        members = archive.getmembers()
        files = [item for item in members if item.isfile()]
        if len(members) > max_files or sum(item.size for item in files) > max_bytes:
            raise ValueError("archive exceeds configured expansion limits")
        for item in members:
            if not (item.isdir() or item.isfile()):
                raise ValueError("archive links and special files are not allowed")
            target = _inside(root, item.name)
            if item.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            source = archive.extractfile(item)
            if source is None:
                raise ValueError("archive member could not be read")
            target.parent.mkdir(parents=True, exist_ok=True)
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output, 64 * 1024)
            target.chmod(0o600)
            extracted.append(target)
    return tuple(extracted)


def expand_archive(path: Path, max_files: int, max_bytes: int) -> tuple[Path, ...]:
    lower = path.name.lower()
    target = path.parent / (path.name + ".contents")
    if lower.endswith(".zip"):
        target.mkdir(mode=0o700)
        try:
            return _safe_extract_zip(path, target, max_files, max_bytes)
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
    tar_suffixes = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")
    if lower.endswith(tar_suffixes):
        target.mkdir(mode=0o700)
        try:
            return _safe_extract_tar(path, target, max_files, max_bytes)
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
    return ()


async def download_attachments(
    client: TelegramClient,
    message: dict[str, Any],
    root: Path,
    max_files: int,
    max_bytes: int,
    max_archive_files: int,
    max_archive_bytes: int,
) -> list[Attachment]:
    specs = _specs(message)
    if len(specs) > max_files:
        raise ValueError("too many attachments in one message")
    if any(size is not None and size > max_bytes for _, _, _, size in specs):
        raise ValueError("attachment exceeds configured size limit")
    message_root = root / uuid.uuid4().hex
    message_root.mkdir(parents=True, mode=0o700)
    results: list[Attachment] = []
    try:
        for index, (kind, file_id, name, _) in enumerate(specs):
            destination = message_root / f"{index:02d}-{safe_name(name)}"
            await client.download(file_id, destination, max_bytes)
            extracted = await asyncio.to_thread(
                expand_archive, destination, max_archive_files, max_archive_bytes
            )
            results.append(Attachment(kind, name, destination, extracted))
    except Exception:
        shutil.rmtree(message_root, ignore_errors=True)
        raise
    return results


def attachment_manifest(items: list[Attachment]) -> str:
    if not items:
        return ""
    lines = ["Attachments available for this turn (read-only):"]
    for item in items:
        lines.append(f"- {item.kind}: {item.original_name!r} -> {item.path}")
        for child in item.extracted:
            lines.append(f"  extracted -> {child}")
    return "\n".join(lines)


def grant_group_access(items: list[Attachment], group_name: str | None) -> None:
    """Grant only the configured Agent file group access to this turn's files."""
    if not items or not group_name:
        return
    gid = grp.getgrnam(group_name).gr_gid
    roots = {item.path.parent for item in items}
    for root in roots:
        paths = [root, *root.rglob("*")]
        for path in paths:
            os.chown(path, -1, gid)
            path.chmod(0o710 if path.is_dir() else 0o640)
