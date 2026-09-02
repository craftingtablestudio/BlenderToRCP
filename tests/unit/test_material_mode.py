"""Unit tests for the material authoring mode."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Plugin.export.material_mode import (
    PREVIEW_SURFACE,
    SHADER_GRAPH,
    is_preview_surface,
    resolve_material_mode,
)
from Plugin.export.materials.rewrite import rewrite_materials
from Plugin.export.usd_utils import PXR_AVAILABLE, Usd, UsdGeom, UsdShade


class _Settings:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_defaults_to_shader_graph_when_setting_absent():
    assert resolve_material_mode(_Settings()) == SHADER_GRAPH
    assert not is_preview_surface(_Settings())


def test_unknown_value_falls_back_to_shader_graph():
    assert resolve_material_mode(_Settings(material_mode="NONSENSE")) == SHADER_GRAPH


def test_preview_surface_is_recognized():
    settings = _Settings(material_mode=PREVIEW_SURFACE)
    assert resolve_material_mode(settings) == PREVIEW_SURFACE
    assert is_preview_surface(settings)


@pytest.mark.skipif(
    not PXR_AVAILABLE,
    reason="OpenUSD Python bindings are required for USD authoring tests.",
)
def test_preview_surface_mode_leaves_the_stage_untouched():
    """The whole feature: no mtlx terminal, binding survives."""
    stage = Usd.Stage.CreateInMemory()
    material = UsdShade.Material.Define(stage, "/Material0")
    shader = UsdShade.Shader.Define(stage, "/Material0/Principled_BSDF")
    shader.CreateIdAttr("UsdPreviewSurface")
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")

    mesh = UsdGeom.Mesh.Define(stage, "/Mesh0")
    UsdShade.MaterialBindingAPI(mesh).Bind(material)

    context = types.SimpleNamespace(blend_data=types.SimpleNamespace(materials=[]))
    rewrite_materials(stage, _Settings(material_mode=PREVIEW_SURFACE), context)

    material_prim = stage.GetPrimAtPath("/Material0")
    assert not material_prim.GetAttribute("outputs:mtlx:surface").IsValid()
    assert material_prim.GetAttribute("outputs:surface").IsValid()
    assert [p.GetName() for p in material_prim.GetChildren()] == ["Principled_BSDF"]

    bound = UsdShade.MaterialBindingAPI(stage.GetPrimAtPath("/Mesh0")).GetDirectBinding().GetMaterial()
    assert bound.GetPrim().GetPath() == material.GetPrim().GetPath()
