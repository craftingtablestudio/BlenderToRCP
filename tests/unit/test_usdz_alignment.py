"""Unit tests for USDZ 64-byte data alignment.

USDZ requires each contained file's data to start on a 64-byte boundary.
``zipfile`` knows nothing about that rule, so the packager pads the local file
header's extra field itself.
"""

from __future__ import annotations

import struct
import sys
import types
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

sys.modules.setdefault("bpy", types.ModuleType("bpy"))

from Plugin.export.pack_usdz import _write_aligned  # noqa: E402


def _data_offsets(usdz_path: Path) -> dict[str, int]:
    """Offset of each entry's file data, read from the local headers."""
    offsets = {}
    raw = usdz_path.read_bytes()
    with zipfile.ZipFile(usdz_path) as zf:
        for info in zf.infolist():
            start = info.header_offset
            namelen, extralen = struct.unpack("<HH", raw[start + 26 : start + 30])
            offsets[info.filename] = start + 30 + namelen + extralen
    return offsets


def _write_package(tmp_path: Path, names: list[str], payload: bytes = b"x" * 100) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    out = tmp_path / "out.usdz"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as usdz:
        for name in names:
            source = tmp_path / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(payload)
            _write_aligned(usdz, str(source), name)
    return out


def test_single_entry_is_aligned(tmp_path):
    """30-byte header + 18-char name lands on 48 without padding — the reported bug."""
    out = _write_package(tmp_path, ["GameDieExport.usdc"])
    assert _data_offsets(out)["GameDieExport.usdc"] == 64


def test_every_entry_in_a_multi_file_package_is_aligned(tmp_path):
    names = [
        "Model.usdc",
        "textures/base_color.png",
        "textures/normal.png",
        "assets/extra.usdc",
    ]
    out = _write_package(tmp_path, names, payload=b"y" * 517)
    offsets = _data_offsets(out)
    assert set(offsets) == set(names)
    for name, offset in offsets.items():
        assert offset % 64 == 0, f"{name} starts at {offset}"


@pytest.mark.parametrize("namelen", range(6, 130))
def test_alignment_holds_for_every_name_length(tmp_path, namelen):
    """Whether the gap needed padding, needed a full extra block, or was already
    aligned, the data must land on a boundary."""
    name = "a" * (namelen - len(".usdc")) + ".usdc"
    assert len(name) == namelen
    out = _write_package(tmp_path / str(namelen), [name])
    assert _data_offsets(out)[name] % 64 == 0


def test_padding_uses_the_openusd_extra_record(tmp_path):
    """OpenUSD's packager writes header id 0x1986 then zero bytes."""
    out = _write_package(tmp_path, ["GameDieExport.usdc"])
    raw = out.read_bytes()
    namelen, extralen = struct.unpack("<HH", raw[26:30])
    extra = raw[30 + namelen : 30 + namelen + extralen]
    header_id, data_size = struct.unpack("<HH", extra[:4])
    assert header_id == 0x1986
    assert data_size == extralen - 4
    assert extra[4:] == b"\x00" * data_size


def test_contents_still_readable_and_stored(tmp_path):
    payload = b"z" * 1234
    out = _write_package(tmp_path, ["Model.usdc", "textures/t.png"], payload=payload)
    with zipfile.ZipFile(out) as zf:
        assert zf.testzip() is None
        for info in zf.infolist():
            assert info.compress_type == zipfile.ZIP_STORED
            assert zf.read(info.filename) == payload
