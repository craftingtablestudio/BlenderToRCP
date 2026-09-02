"""
USDZ packager

Creates USDZ files as stored (uncompressed) ZIP archives.
"""

import os
import shutil
import struct
import zipfile
from pathlib import Path
from typing import Optional, List

# USDZ requires every contained file's data to start on a 64-byte boundary so
# readers can memory-map the layer straight out of the package. Padding goes in
# the local file header's extra field, using the same dummy record OpenUSD's own
# packager writes: header id 0x1986, then zero bytes.
_USDZ_ALIGNMENT = 64
_PADDING_HEADER_ID = 0x1986
_ZIP_LOCAL_HEADER_SIZE = 30
_EXTRA_RECORD_HEADER_SIZE = 4


def _alignment_extra_field(header_start: int, arcname: str) -> bytes:
    """Build the extra field that pushes this entry's data to a 64-byte boundary."""
    unpadded = header_start + _ZIP_LOCAL_HEADER_SIZE + len(arcname.encode("utf-8"))
    padding = -unpadded % _USDZ_ALIGNMENT
    if padding == 0:
        return b""
    # An extra field record cannot be shorter than its own 4-byte header, so a
    # sub-4 gap has to grow by a full alignment block to stay well-formed.
    if padding < _EXTRA_RECORD_HEADER_SIZE:
        padding += _USDZ_ALIGNMENT
    data_size = padding - _EXTRA_RECORD_HEADER_SIZE
    return struct.pack("<HH", _PADDING_HEADER_ID, data_size) + b"\x00" * data_size


def _write_aligned(usdz: zipfile.ZipFile, source_path: str, arcname: str) -> None:
    """Add a file to *usdz* stored uncompressed and 64-byte aligned."""
    arcname = arcname.replace(os.sep, "/")
    zinfo = zipfile.ZipInfo.from_file(source_path, arcname)
    zinfo.compress_type = zipfile.ZIP_STORED
    zinfo.extra = _alignment_extra_field(usdz.fp.tell(), arcname)

    with open(source_path, "rb") as src, usdz.open(zinfo, "w") as dst:
        shutil.copyfileobj(src, dst)

def create_usdz(usd_path: str, output_path: str, settings, context, diagnostics=None):
    """Create USDZ file from USD stage
    
    Args:
        usd_path: Path to USD file
        output_path: Path to output USDZ file
        settings: Export settings
        context: Blender context
        diagnostics: ExportDiagnostics instance
    """
    # Imported here, not at module scope, so the packaging helpers below stay
    # importable outside Blender.
    from .. import prefs as addon_prefs

    prefs = addon_prefs.get_preferences(context)
    usdzip_path = prefs.usdzip_path if prefs and hasattr(prefs, 'usdzip_path') else None
    
    if usdzip_path and os.path.exists(usdzip_path):
        # Use external tool
        create_usdz_with_tool(usd_path, output_path, usdzip_path)
        if diagnostics:
            diagnostics.add_generated_file("usdz", output_path, packager="usdzip")
    else:
        # Use Python fallback
        create_usdz_python(usd_path, output_path, settings, diagnostics)
        if diagnostics:
            diagnostics.add_generated_file("usdz", output_path, packager="python_zip")

    _cleanup_usdz_staging(usd_path, diagnostics)


def create_usdz_with_tool(usd_path: str, output_path: str, usdzip_path: str):
    """Create USDZ using external usdzip tool"""
    import subprocess
    
    try:
        result = subprocess.run(
            [usdzip_path, output_path, usd_path],
            capture_output=True,
            text=True,
            check=True
        )
        print(f"USDZ created using usdzip: {output_path}")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"usdzip failed: {e.stderr}") from e
    except Exception as e:
        raise RuntimeError(f"Failed to run usdzip: {e}") from e


def create_usdz_python(usd_path: str, output_path: str, settings, diagnostics=None):
    """Create USDZ using Python ZIP (stored, uncompressed)"""
    usd_file = Path(usd_path)
    usd_dir = usd_file.parent
    
    # Ensure output directory exists
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Create ZIP archive with no compression (stored)
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_STORED) as usdz:
        # Add main USD file at root
        usd_arcname = usd_file.name
        _write_aligned(usdz, usd_path, usd_arcname)

        # Add textures directory if it exists
        textures_dir = usd_dir / "textures"
        if textures_dir.exists():
            for texture_file in textures_dir.rglob("*"):
                if texture_file.is_file():
                    # Preserve relative path structure
                    arcname = texture_file.relative_to(usd_dir)
                    _write_aligned(usdz, str(texture_file), str(arcname))

        # Add staged assets directory if it exists
        assets_dir = usd_dir / "assets"
        if assets_dir.exists():
            for asset_file in assets_dir.rglob("*"):
                if asset_file.is_file():
                    arcname = asset_file.relative_to(usd_dir)
                    _write_aligned(usdz, str(asset_file), str(arcname))
        
        # Add any other referenced assets
        # (This is a simplified implementation - full version would parse USD for all asset references)
    
    print(f"USDZ created: {output_path}")
    
    if diagnostics:
        diagnostics.add_warning("USDZ packaged using Python fallback (stored ZIP)")


def validate_usdz(usdz_path: str) -> bool:
    """Validate USDZ file structure
    
    Args:
        usdz_path: Path to USDZ file
        
    Returns:
        True if valid, False otherwise
    """
    try:
        with zipfile.ZipFile(usdz_path, 'r') as usdz:
            # Check for at least one USD file at root
            root_files = [f for f in usdz.namelist() if '/' not in f or f.count('/') == 1]
            usd_files = [f for f in root_files if f.endswith(('.usd', '.usda', '.usdc'))]
            
            if not usd_files:
                return False
            
            # Check that main USD file is readable
            main_usd = usd_files[0]
            try:
                usdz.read(main_usd)
            except Exception:
                return False
            
            return True
    except Exception:
        return False


def _cleanup_usdz_staging(usd_path: str, diagnostics=None) -> None:
    """Remove the temporary USDZ staging directory after successful packaging."""
    staging_dir = Path(usd_path).resolve().parent
    if staging_dir.name != ".blendertorcp_temp":
        if staging_dir.parent.name != ".blendertorcp_temp":
            return

    # Current USDZ exports stage into `.blendertorcp_temp/<stem>/...`; keep
    # compatibility with older flat staging layouts under `.blendertorcp_temp/`.
    target_dir = staging_dir
    if staging_dir.name != ".blendertorcp_temp":
        temp_root = staging_dir.parent
    else:
        temp_root = staging_dir

    try:
        shutil.rmtree(target_dir)
    except Exception as exc:
        if diagnostics:
            diagnostics.add_warning(
                f"Failed to remove USDZ staging directory '{target_dir}': {exc}"
            )
        return

    if temp_root.name == ".blendertorcp_temp":
        try:
            temp_root.rmdir()
        except OSError:
            pass
