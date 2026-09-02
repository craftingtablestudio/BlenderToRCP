"""
Material authoring mode shared by the export operator, the API command and the
USD post-process pass.

``SHADER_GRAPH`` authors the RealityKit MaterialX network on top of the
UsdPreviewSurface network Blender already exported. ``PREVIEW_SURFACE`` leaves
Blender's UsdPreviewSurface network as the only surface terminal, so Reality
Composer Pro shows a plain material inspector instead of a Shader Graph.
"""

SHADER_GRAPH = "SHADER_GRAPH"
PREVIEW_SURFACE = "PREVIEW_SURFACE"


def resolve_material_mode(settings) -> str:
    """Return the material mode for *settings*, defaulting to Shader Graph."""
    mode = getattr(settings, "material_mode", SHADER_GRAPH)
    return PREVIEW_SURFACE if mode == PREVIEW_SURFACE else SHADER_GRAPH


def is_preview_surface(settings) -> bool:
    return resolve_material_mode(settings) == PREVIEW_SURFACE
