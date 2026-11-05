# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: CC-BY-4.0 AND Apache-2.0
#
"""
USD writer for 3D Gaussian Splat data.

Produces standard USD files using the ParticleField3DGaussianSplat schema.

When OpenUSD 26.03+ is available (typically via usd-core on x86_64), the typed
UsdVol.ParticleField3DGaussianSplat API is used. Otherwise the converter defines
a prim with type ParticleField3DGaussianSplat and authors the expected attributes
directly (used on linux-aarch64 with usd-exchange, or when the Omniverse
usd_particle_field plugin is loaded). Schema validation against the typed API is
not performed on the fallback path.
"""

import os
import re

import numpy as np
from pxr import Gf, Sdf, Tf, Usd, UsdGeom, UsdUtils, Vt

from .local_paths import resolve_local_path
from .partition import partition_indices, select_splats
from .ply_reader import SH_LAYOUT_CHANNEL_MAJOR, SH_LAYOUT_VEC3_MAJOR, read_ply

try:
    import omni.usd.schema.usd_particle_field  # noqa: F401
except ImportError:
    pass

try:
    from pxr import UsdVol

    _HasParticleField3DGaussianSplat = hasattr(UsdVol, "ParticleField3DGaussianSplat")
except Exception:
    UsdVol = None
    _HasParticleField3DGaussianSplat = False

_EXTENT_LIMIT = 50000.0

# A ZIP member at or above this needs ZIP64 extension headers, which OpenUSD's
# reader does not accept. Checked explicitly before packaging: USD does its own
# zipping, so we can no longer delegate the limit to `zipfile`.
_USDZ_MEMBER_LIMIT_GIB = 4
_USDZ_MEMBER_LIMIT_BYTES = _USDZ_MEMBER_LIMIT_GIB * 1024**3

_PARTICLE_FIELD_3D_GAUSSIAN_SPLAT = "ParticleField3DGaussianSplat"

_PRIM_CREATE_FAILURE_MSG = (
    f"Failed to create {_PARTICLE_FIELD_3D_GAUSSIAN_SPLAT} prim. "
    'Install USD support with pip install "usd-convert-gsplat[usd]" '
    "(usd-core>=26.3 on x86_64; usd-exchange on linux-aarch64)."
)

UP_AXIS_Y = "Y"
UP_AXIS_Z = "Z"

# Renderer hints on ParticleField. Both are uniform tokens in the schema.
PROJECTION_MODE_PERSPECTIVE = "perspective"
SORTING_MODE_Z_DEPTH = "zDepth"
SORTING_MODE_CAMERA_DISTANCE = "cameraDistance"

# Tokens this converter is willing to author. The schema additionally declares
# `tangential` for projection and `rayHitDistance` for sorting; neither has been
# verified against Omniverse here, so neither is offered. Widening this is a
# one-line change once a token is confirmed.
PROJECTION_MODE_HINTS = (PROJECTION_MODE_PERSPECTIVE,)
SORTING_MODE_HINTS = (SORTING_MODE_Z_DEPTH, SORTING_MODE_CAMERA_DISTANCE)

# Both defaults match the schema's own (`perspective` and `zDepth`), so this
# changes no rendered output. Authoring them anyway is the point: it records the
# intended value in the asset instead of leaving it to whatever the reader's
# schema version happens to fall back to.
DEFAULT_PROJECTION_MODE_HINT = PROJECTION_MODE_PERSPECTIVE
DEFAULT_SORTING_MODE_HINT = SORTING_MODE_Z_DEPTH
DEFAULT_MAX_SPLATS_PER_PRIM = 8_000_000

__all__ = [
    "estimate_usdz_payload_bytes",
    "validate_usdz_payload_estimate",
    "write_gaussian_splat_usd",
    "convertPlyUSD",
    "UP_AXIS_Y",
    "UP_AXIS_Z",
    "PROJECTION_MODE_HINTS",
    "SORTING_MODE_HINTS",
    "DEFAULT_PROJECTION_MODE_HINT",
    "DEFAULT_SORTING_MODE_HINT",
    "DEFAULT_MAX_SPLATS_PER_PRIM",
]


def estimate_usdz_payload_bytes(
    splat_count: int,
    sh_coefficient_count: int,
    half_precision: bool,
) -> int:
    """Estimate the encoded bulk-array input before USD crate compression."""
    assert splat_count > 0, "splat_count must be positive"
    assert sh_coefficient_count > 0, "sh_coefficient_count must include the DC coefficient"

    component_bytes = 2 if half_precision else 4
    paired_component_count = 11 + 3 * sh_coefficient_count
    display_color_bytes = 3 * 4
    return splat_count * (paired_component_count * component_bytes + display_color_bytes)


def validate_usdz_payload_estimate(
    splat_count: int,
    sh_coefficient_count: int,
    half_precision: bool,
) -> None:
    """Reject scenes whose authored arrays clearly exceed USDZ's ZIP32 limit."""
    estimated_bytes = estimate_usdz_payload_bytes(
        splat_count,
        sh_coefficient_count,
        half_precision,
    )
    if estimated_bytes < _USDZ_MEMBER_LIMIT_BYTES:
        return

    precision = "half-precision" if half_precision else "float32"
    reduction_advice = "reduce the scene"
    if not half_precision:
        reduction_advice = "enable --half-precision if its estimate fits, or reduce the scene"
    raise ValueError(
        f"Scene is too large to package as .usdz: its {precision} bulk arrays are "
        f"estimated at {estimated_bytes / 1024**3:.2f} GiB for {splat_count:,} splats. "
        f"USDZ uses ZIP32, so both each member and the total archive must stay below "
        f"{_USDZ_MEMBER_LIMIT_GIB} GiB; OpenUSD cannot read ZIP64 extensions. No USD "
        f"layers were written. Write to .usdc or .usda instead, {reduction_advice}."
    )


def _valid_usd_prim_name(name: str) -> str:
    """
    Turn a file stem or user label into a valid USD prim name (no spaces, etc.).

    Filenames such as ``My Scene - Copy.ply`` are not valid SdfPath components; without
    this, Usd.Stage will fail (e.g. "Path must be an absolute path: <>").
    """
    if not name or not str(name).strip():
        return "GaussianSplat"
    raw = str(name).strip()
    try:
        ident = Tf.MakeValidIdentifier(raw)
        if ident:
            return ident
    except Exception:
        pass
    out = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    out = re.sub(r"_+", "_", out).strip("_")
    if not out:
        return "GaussianSplat"
    if out[0].isdigit():
        return f"_{out}"
    return out


def _set_prim_display_name_usd(prim, display_name: str) -> None:
    """
    Set prim ``displayName`` metadata (outliner / stage UI); may contain spaces
    and characters that are not allowed in the prim's path name.
    """
    if not display_name or not str(display_name).strip():
        return
    p = prim if isinstance(prim, Usd.Prim) else prim.GetPrim()
    if p and p.IsValid():
        p.SetMetadata("displayName", str(display_name).strip())


def _validate_hint(name: str, value: str, supported: tuple) -> None:
    """Reject unsupported hint tokens up front rather than authoring them."""
    if value not in supported:
        raise ValueError(f"Unsupported {name} {value!r}; expected one of {list(supported)}")


def _set_render_hints(gs_prim, prim, projection_mode_hint: str, sorting_mode_hint: str) -> None:
    """
    Author the ParticleField renderer hints.

    Consumers fall back to the schema defaults (``perspective`` / ``zDepth``)
    when these are absent, so authoring them explicitly is what makes the
    intended sort deterministic rather than left to the reader.

    Both are uniform tokens; the non-typed fallback path sets that variability
    explicitly so its output matches the typed schema.
    """
    _validate_hint("projectionModeHint", projection_mode_hint, PROJECTION_MODE_HINTS)
    _validate_hint("sortingModeHint", sorting_mode_hint, SORTING_MODE_HINTS)

    if _HasParticleField3DGaussianSplat:
        gs_prim.CreateProjectionModeHintAttr(projection_mode_hint)
        gs_prim.CreateSortingModeHintAttr(sorting_mode_hint)
        return

    for name, value in (
        ("projectionModeHint", projection_mode_hint),
        ("sortingModeHint", sorting_mode_hint),
    ):
        attr = prim.CreateAttribute(
            name,
            Sdf.ValueTypeNames.Token,
            custom=False,
            variability=Sdf.VariabilityUniform,
        )
        if attr:
            attr.Set(value)


def _is_channel_major(sh_layout: str) -> bool:
    """
    True when ``f_rest`` is channel-major and needs transposing to the
    vec3-major order USD expects.

    The layout travels on GaussianSplatData, set by whichever reader produced
    it. It is deliberately not inferred from the source filename: ``source_file``
    is presentational metadata that may be absent or point at a different
    format, which would silently produce wrongly-ordered coefficients.
    """
    if sh_layout == SH_LAYOUT_CHANNEL_MAJOR:
        return True
    if sh_layout == SH_LAYOUT_VEC3_MAJOR:
        return False
    raise ValueError(
        f"Unknown spherical harmonic layout {sh_layout!r}; expected "
        f"{SH_LAYOUT_CHANNEL_MAJOR!r} or {SH_LAYOUT_VEC3_MAJOR!r}"
    )


def _up_axis_token(up_axis: str):
    """Return the UsdGeom token for the given up-axis string."""
    if up_axis and up_axis.upper() == UP_AXIS_Z:
        return UsdGeom.Tokens.z
    return UsdGeom.Tokens.y


def _variant(base: str, half: bool, float_type, half_type):
    """
    Name and value type for one side of a float/half attribute pair.

    The schema declares a half counterpart for each bulk array, suffixed ``h``. Only
    one side of a pair is ever authored: RTX's population layer expands the half form
    into the float one, and skips that conversion when the float attribute already
    holds data, so authoring both would silently discard the half arrays.
    """
    return (f"{base}h", half_type) if half else (base, float_type)


def _set_transform_stack(prim: Usd.Prim, rotation_degrees: tuple) -> None:
    """
    Give the prim a translate / rotateXYZ / scale transform; the point data is never
    rotated. Spherical harmonics are evaluated in the Gaussian's own frame, so moving
    positions without the coefficients would leave view-dependent appearance facing
    the wrong way. All three ops are authored whatever the rotation, resolving to
    identity when none is asked for, so the transform is always present and editable
    as angles. Our ``(rx, ry, rz)`` matches USD's ``rotateXYZ``.
    """
    rx, ry, rz = (float(a) for a in rotation_degrees)
    api = UsdGeom.XformCommonAPI(prim)
    api.SetTranslate(Gf.Vec3d(0.0, 0.0, 0.0))
    api.SetRotate(Gf.Vec3f(rx, ry, rz), UsdGeom.XformCommonAPI.RotationOrderXYZ)
    api.SetScale(Gf.Vec3f(1.0, 1.0, 1.0))


def _gaussian_splat_data_to_usd(
    splat_data,
    stage: Usd.Stage,
    prim_path: str,
    prim_name: str,
    progress_fn=None,
    up_axis: str = UP_AXIS_Y,
    rotation_degrees: tuple = (0.0, 0.0, 0.0),
    prim_display_name: str = None,
    projection_mode_hint: str = DEFAULT_PROJECTION_MODE_HINT,
    sorting_mode_hint: str = DEFAULT_SORTING_MODE_HINT,
    half_precision: bool = False,
    set_default_prim: bool = True,
) -> None:
    """
    Write GaussianSplatData to a UsdVol.ParticleField3DGaussianSplat prim.

    Parameters
    ----------
    splat_data : GaussianSplatData
        From ply_reader or spz_reader.
    stage : Usd.Stage
        USD stage to write to.
    prim_path : str
        Path for the prim (e.g. "/GaussianSplat").
    prim_name : str
        Name used in layer metadata.
    prim_display_name : str, optional
        If set, stored as ``displayName`` metadata (typically the original import file stem).
    progress_fn : callable, optional
        progress_fn(fraction, message)
    up_axis : str
        Target stage up-axis ("Y" or "Z").
    rotation_degrees : tuple of (float, float, float)
        Euler rotation (rx, ry, rz) in degrees, authored as a transform op on
        the prim.  The arrays stay in their original frame.  Use to correct
        source orientation.
    projection_mode_hint : str
        ``projectionModeHint`` token; one of ``PROJECTION_MODE_HINTS``, which
        currently holds only ``perspective``.
    sorting_mode_hint : str
        ``sortingModeHint`` token; one of ``SORTING_MODE_HINTS``.
    half_precision : bool
        Author the schema's half-typed arrays instead of the float ones, roughly
        halving the payload. Off by default; see ``write_gaussian_splat_usd``.
    set_default_prim : bool
        Set this ParticleField as the stage's default prim. Partition children
        leave the parent Xform as the default instead.
    """

    # Split internally even though one flag sets both. The schema pairs attributes
    # individually and both reference implementations expose the two groups, so
    # offering finer control later needs no rework here. Note opacity belongs to
    # features rather than geometry, matching both of them.
    half_geometry = half_precision
    half_features = half_precision

    def _p(f, msg=None):
        if progress_fn:
            progress_fn(f, msg)

    vertex_count = splat_data.count
    positions = splat_data.positions
    scales = splat_data.scales
    rotations = splat_data.rotations
    opacities = splat_data.opacities
    f_dc = splat_data.f_dc
    f_rest = splat_data.f_rest

    _p(0.10, "Creating Gaussian Splat prim...")

    if _HasParticleField3DGaussianSplat:
        gs_prim = UsdVol.ParticleField3DGaussianSplat.Define(stage, prim_path)
    else:
        prim = stage.DefinePrim(prim_path, _PARTICLE_FIELD_3D_GAUSSIAN_SPLAT)
        if not prim or not prim.IsValid():
            raise RuntimeError(_PRIM_CREATE_FAILURE_MSG)
        gs_prim = prim

    if set_default_prim:
        stage.SetDefaultPrim(gs_prim.GetPrim() if hasattr(gs_prim, "GetPrim") else gs_prim)

    prim0 = gs_prim.GetPrim() if hasattr(gs_prim, "GetPrim") else gs_prim
    if prim_display_name is not None:
        _set_prim_display_name_usd(prim0, prim_display_name)

    _p(0.15, "Setting render hints...")
    _set_render_hints(gs_prim, prim0, projection_mode_hint, sorting_mode_hint)
    _set_transform_stack(prim0, rotation_degrees)

    if half_geometry:
        positions_vt = Vt.Vec3hArray.FromNumpy(np.ascontiguousarray(positions, dtype=np.float16))
    else:
        positions_vt = Vt.Vec3fArray.FromNumpy(np.ascontiguousarray(positions, dtype=np.float32))
    min_x = float(positions[:, 0].min())
    min_y = float(positions[:, 1].min())
    min_z = float(positions[:, 2].min())
    max_x = float(positions[:, 0].max())
    max_y = float(positions[:, 1].max())
    max_z = float(positions[:, 2].max())
    extent_min = Gf.Vec3f(
        float(max(-_EXTENT_LIMIT, min_x)),
        float(max(-_EXTENT_LIMIT, min_y)),
        float(max(-_EXTENT_LIMIT, min_z)),
    )
    extent_max = Gf.Vec3f(
        float(min(_EXTENT_LIMIT, max_x)),
        float(min(_EXTENT_LIMIT, max_y)),
        float(min(_EXTENT_LIMIT, max_z)),
    )
    extent = Vt.Vec3fArray([extent_min, extent_max])
    # float64 then narrow, matching the Python-float arithmetic this replaced.
    scales_linear = np.exp(np.asarray(scales, dtype=np.float64))
    if half_geometry:
        scales_vt = Vt.Vec3hArray.FromNumpy(np.ascontiguousarray(scales_linear, dtype=np.float16))
    else:
        scales_vt = Vt.Vec3fArray.FromNumpy(np.ascontiguousarray(scales_linear, dtype=np.float32))
    orientations_vt = _quats_to_vt(rotations, half=half_geometry)
    if half_features:
        opacities_vt = Vt.HalfArray.FromNumpy(_sigmoid(opacities, dtype=np.float16))
    else:
        opacities_vt = Vt.FloatArray.FromNumpy(_sigmoid(opacities))

    prim = gs_prim.GetPrim() if hasattr(gs_prim, "GetPrim") else gs_prim

    def _set_attr(name, value, type_name):
        attr = prim.CreateAttribute(name, type_name)
        if attr:
            attr.Set(value)

    _p(0.20, "Processing positions...")
    if _HasParticleField3DGaussianSplat:
        (gs_prim.CreatePositionshAttr if half_geometry else gs_prim.CreatePositionsAttr)(positions_vt)
    else:
        name, type_name = _variant(
            "positions", half_geometry, Sdf.ValueTypeNames.Point3fArray, Sdf.ValueTypeNames.Point3hArray
        )
        _set_attr(name, positions_vt, type_name)

    UsdGeom.Boundable(prim).CreateExtentAttr(extent)

    _p(0.35, "Processing scales...")
    if _HasParticleField3DGaussianSplat:
        (gs_prim.CreateScaleshAttr if half_geometry else gs_prim.CreateScalesAttr)(scales_vt)
    else:
        name, type_name = _variant(
            "scales", half_geometry, Sdf.ValueTypeNames.Float3Array, Sdf.ValueTypeNames.Half3Array
        )
        _set_attr(name, scales_vt, type_name)

    _p(0.50, "Processing orientations...")
    if _HasParticleField3DGaussianSplat:
        (gs_prim.CreateOrientationshAttr if half_geometry else gs_prim.CreateOrientationsAttr)(orientations_vt)
    else:
        name, type_name = _variant(
            "orientations", half_geometry, Sdf.ValueTypeNames.QuatfArray, Sdf.ValueTypeNames.QuathArray
        )
        _set_attr(name, orientations_vt, type_name)

    _p(0.65, "Processing opacities...")
    if _HasParticleField3DGaussianSplat:
        (gs_prim.CreateOpacitieshAttr if half_features else gs_prim.CreateOpacitiesAttr)(opacities_vt)
    else:
        name, type_name = _variant(
            "opacities", half_features, Sdf.ValueTypeNames.FloatArray, Sdf.ValueTypeNames.HalfArray
        )
        _set_attr(name, opacities_vt, type_name)

    _p(0.80, "Processing spherical harmonics...")
    K = f_rest.shape[1] if f_rest is not None and f_rest.shape[1] > 0 else 0
    sh_degree = {0: 0, 9: 1, 24: 2, 45: 3}.get(K, 3 if K > 0 else 0)

    if _HasParticleField3DGaussianSplat:
        gs_prim.CreateRadianceSphericalHarmonicsDegreeAttr(sh_degree)
    else:
        _set_attr("radiance:sphericalHarmonicsDegree", sh_degree, Sdf.ValueTypeNames.Int)

    dc = np.asarray(f_dc, dtype=np.float32).reshape(vertex_count, 1, 3)
    if K > 0:
        num_sh_vec3 = K // 3
        sh_vec_stride = 1 + num_sh_vec3
        rest = np.asarray(f_rest, dtype=np.float32)
        if _is_channel_major(splat_data.sh_layout):
            # PLY groups all coefficients of one channel together: (channel, coeff).
            rest = rest.reshape(vertex_count, 3, num_sh_vec3).transpose(0, 2, 1)
        else:
            # SPZ is already (coeff, channel).
            rest = rest.reshape(vertex_count, num_sh_vec3, 3)
        coeffs = np.concatenate([dc, rest], axis=1)
    else:
        sh_vec_stride = 1
        coeffs = dc
    flat = coeffs.reshape(-1, 3)
    if half_features:
        sh_vt = Vt.Vec3hArray.FromNumpy(np.ascontiguousarray(flat, dtype=np.float16))
    else:
        sh_vt = Vt.Vec3fArray.FromNumpy(np.ascontiguousarray(flat, dtype=np.float32))

    if _HasParticleField3DGaussianSplat:
        create_sh = (
            gs_prim.CreateRadianceSphericalHarmonicsCoefficientshAttr
            if half_features
            else gs_prim.CreateRadianceSphericalHarmonicsCoefficientsAttr
        )
        sh_attr = create_sh(sh_vt)
    else:
        name, type_name = _variant(
            "radiance:sphericalHarmonicsCoefficients",
            half_features,
            Sdf.ValueTypeNames.Float3Array,
            Sdf.ValueTypeNames.Half3Array,
        )
        sh_attr = prim.CreateAttribute(name, type_name)
        if sh_attr:
            sh_attr.Set(sh_vt)
    if sh_attr:
        sh_primvar = UsdGeom.Primvar(sh_attr)
        sh_primvar.SetElementSize(sh_vec_stride)
        sh_primvar.SetInterpolation(UsdGeom.Tokens.vertex)

    _SH_C0 = 0.28209479177387814
    display_colors = Vt.Vec3fArray.FromNumpy(
        np.ascontiguousarray(np.clip(0.5 + _SH_C0 * np.asarray(f_dc, dtype=np.float64), 0.0, 1.0), dtype=np.float32)
    )
    primvars_api = UsdGeom.PrimvarsAPI(prim)
    display_color_primvar = primvars_api.CreatePrimvar(
        "displayColor", Sdf.ValueTypeNames.Color3fArray, UsdGeom.Tokens.vertex
    )
    if display_color_primvar:
        display_color_primvar.Set(display_colors)


def _sigmoid(x, dtype=np.float32) -> "np.ndarray":
    """
    Sigmoid that does not overflow for large negative input.

    The scalar form this replaced computed ``1 / (1 + exp(-v))`` directly, which
    raises OverflowError once ``-v`` exceeds ~709.

    Computed in float64 and narrowed at the end. That is deliberate: the scalar
    form went through Python floats, so evaluating in float32 would round
    differently and change the written bytes for no benefit.
    """
    x = np.asarray(x, dtype=np.float64)
    out = np.empty_like(x)
    pos = x >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-x[pos]))
    e = np.exp(x[~pos])
    out[~pos] = e / (1.0 + e)
    return np.ascontiguousarray(out, dtype=dtype)


def _quats_to_vt(rotations, half: bool = False):
    """
    Convert an ``(N, 4)`` array of ``(w, x, y, z)`` quaternions to ``Vt.QuatfArray``.

    The column roll is essential and easy to miss. ``Gf.Quatf(w, x, y, z)`` takes
    the real part **first**, but ``Vt.QuatfArray.FromNumpy`` expects it **last**:
    handing over ``(w, x, y, z)`` unrolled silently reinterprets w as the k
    component and mis-rotates every splat, with no error anywhere. See
    ``tests/test_vectorized_authoring.py`` for the test that pins this.
    """
    # float32 throughout, because Gf.Quatf.Normalize() worked in float32 and this
    # must reproduce it bit for bit. Contrast the scales and opacity paths, which
    # went through Python floats and so need float64.
    #
    # Copied, not viewed. `np.asarray` returns the caller's own array when the dtype
    # already matches, and the normalisation below writes through `out=`, so a view
    # would rewrite the caller's data — silently, and only for float32 input, which
    # is exactly what the readers produce.
    q = np.array(rotations, dtype=np.float32, copy=True)
    norms = np.linalg.norm(q, axis=1, keepdims=True)
    # A zero quaternion cannot be normalised; leave it rather than divide by zero.
    np.divide(q, norms, out=q, where=norms > 0)
    rolled = q[:, [1, 2, 3, 0]]
    # Normalised in float32 either way, so the half form quantises an already
    # unit-length quaternion rather than normalising in half precision.
    if half:
        return Vt.QuathArray.FromNumpy(np.ascontiguousarray(rolled, dtype=np.float16))
    return Vt.QuatfArray.FromNumpy(np.ascontiguousarray(rolled, dtype=np.float32))


def _provenance_comment(source_name: str) -> str:
    """
    Provenance recorded on the top-level layer only.

    Deliberately the file name and not the path it was converted from: the comment
    travels with the artifact, and a full path exports the converting machine's
    directory layout, usually including a username.
    """
    return f"Converted from PLY/SPZ to USD using usd-convert-gsplat\nSource file: {source_name}"


def _write_composition_root(root_path: str, payload_name: str, prim_path: str, up_axis: str, source_file: str) -> None:
    """
    Write the small text layer that sublayers the binary payload.

    This is what makes the archive inspectable: unzip a ``.usdz`` and the first
    member is a few lines of readable USD naming the payload, rather than an
    opaque crate file. Both reference implementations ship the same shape.
    """
    root = Usd.Stage.CreateNew(root_path)
    root.GetRootLayer().subLayerPaths = [f"./{payload_name}"]
    UsdGeom.SetStageUpAxis(root, _up_axis_token(up_axis))
    UsdGeom.SetStageMetersPerUnit(root, 1.0)
    prim = root.GetPrimAtPath(prim_path)
    if prim:
        root.SetDefaultPrim(prim)
    root.GetRootLayer().comment = f"Converted from PLY/SPZ to USD using usd-convert-gsplat\nSource file: {source_file}"
    root.Save()


def _package_usdz(output_path: str, root_path: str, payload_path: str, splat_count: int) -> None:
    """
    Pack the composition root and its payload into a spec-conformant ``.usdz``.

    ``UsdUtils.CreateNewUsdzPackage`` collects the sublayer, names the first member
    and — the reason for preferring it over hand-rolled zipping — pads every member
    to the 64-byte alignment the USDZ specification requires. Our previous manual
    archive placed data at offset 42, which forces a reader to copy the payload
    instead of memory-mapping it in place.

    The size guard from the previous release is kept, but has to be explicit now.
    It used to ride on ``zipfile``'s ``allowZip64=False``, which raised exactly at
    the 32-bit overflow; USD does its own zipping, so the check moves here.
    """
    package_paths = (root_path, payload_path)
    package_sizes = {path: os.path.getsize(path) for path in package_paths}
    for path in package_paths:
        size = package_sizes[path]
        if size >= _USDZ_MEMBER_LIMIT_BYTES:
            raise ValueError(
                f"Scene is too large to package as .usdz: {os.path.basename(path)} is "
                f"{size / 1024**3:.2f} GiB, at or above the {_USDZ_MEMBER_LIMIT_GIB} GiB a ZIP "
                f"member can address without ZIP64 extensions, which OpenUSD cannot read "
                f"({splat_count:,} splats). Write to .usdc or .usda instead, which have no "
                f"such limit, or reduce the scene. The layers have been left at "
                f"{payload_path} and {root_path}."
            )

    package_size = sum(package_sizes.values())
    if package_size >= _USDZ_MEMBER_LIMIT_BYTES:
        raise ValueError(
            f"Scene is too large to package as .usdz: its layers total "
            f"{package_size / 1024**3:.2f} GiB, at or above the {_USDZ_MEMBER_LIMIT_GIB} GiB "
            f"a ZIP32 archive can address. OpenUSD cannot read ZIP64 extensions "
            f"({splat_count:,} splats). Write to .usdc or .usda instead, which have no "
            f"such limit, or reduce the scene. The layers have been left at "
            f"{payload_path} and {root_path}."
        )

    if not UsdUtils.CreateNewUsdzPackage(Sdf.AssetPath(root_path), output_path, firstLayerName="default.usda"):
        raise RuntimeError(f"Failed to package {output_path} from {root_path}")

    for path in (root_path, payload_path):
        # Asserted rather than left to the platform: an open handle is merely
        # untidy on Linux but makes the removal below fail outright on Windows,
        # so this keeps the failure reproducible everywhere.
        assert not Sdf.Layer.Find(path), f"{path} is still open and cannot be removed"
        os.remove(path)


def write_gaussian_splat_usd(
    splat_data,
    output_path: str,
    progress_fn=None,
    source_file: str = None,
    prim_name: str = None,
    up_axis: str = UP_AXIS_Y,
    rotation_degrees: tuple = (0.0, 0.0, 0.0),
    projection_mode_hint: str = DEFAULT_PROJECTION_MODE_HINT,
    sorting_mode_hint: str = DEFAULT_SORTING_MODE_HINT,
    half_precision: bool = False,
    max_splats_per_prim: int = DEFAULT_MAX_SPLATS_PER_PRIM,
) -> str:
    """
    Write GaussianSplatData to a standard USD file (UsdVol.ParticleField3DGaussianSplat).

    Parameters
    ----------
    splat_data : GaussianSplatData
        From ply_reader or spz_reader.
    output_path : str
        Destination path (.usd, .usda, .usdc, or .usdz).
    progress_fn : callable, optional
        progress_fn(fraction, message)
    source_file : str, optional
        Path to source PLY/SPZ file (for layer metadata). When this path exists,
        its filename stem (original characters, e.g. spaces) is set as the prim's
        ``displayName`` for the stage outliner. Otherwise the output file stem
        is used.
    prim_name : str, optional
        Name for the USD prim path. If None, uses output filename stem, then
        sanitized for valid USD identifiers.
    up_axis : str, optional
        Target stage up-axis: "Y" (default) or "Z".
    rotation_degrees : tuple of (float, float, float)
        Euler rotation (rx, ry, rz) in degrees, authored as a transform op on
        the prim.  The arrays stay in their original frame.  Use to correct
        source orientation (e.g. 180,0,0 for COLMAP Y-down data).
    projection_mode_hint : str, optional
        ``projectionModeHint`` token. ``perspective`` is the only value offered;
        the schema's ``tangential`` is unverified here and raises ``ValueError``.
    half_precision : bool, optional
        Author the schema's half-typed arrays (``positionsh``, ``orientationsh``,
        ``scalesh``, ``opacitiesh``, ``radiance:sphericalHarmonicsCoefficientsh``)
        instead of their float counterparts, roughly halving the payload. One
        variant of each pair is written, never both. Off by default.
    sorting_mode_hint : str, optional
        ``sortingModeHint`` token. Defaults to ``zDepth``. Pass
        ``cameraDistance`` to sort by distance to the camera instead.
    max_splats_per_prim : int, optional
        Maximum splats in each ParticleField prim. Scenes above the default
        8,000,000-splat renderer threshold are partitioned automatically.
        Zero explicitly disables partitioning.

    Returns
    -------
    str
        Actual output path written.
    """

    def _p(f, msg=None):
        if progress_fn:
            progress_fn(f, msg)

    output_path = resolve_local_path(output_path)
    if source_file is not None:
        source_file = resolve_local_path(source_file)

    if source_file is not None and os.path.isfile(source_file):
        prim_display_name = os.path.splitext(os.path.basename(source_file))[0]
    else:
        prim_display_name = os.path.splitext(os.path.basename(output_path))[0]

    if prim_name is None:
        prim_name = os.path.splitext(os.path.basename(output_path))[0]
    prim_name = _valid_usd_prim_name(prim_name)
    prim_path = f"/{prim_name}"

    base, ext = os.path.splitext(output_path)
    if not ext or ext.lower() not in (".usd", ".usda", ".usdc", ".usdz"):
        ext = ".usda"

    want_usdz = ext.lower() == ".usdz"
    if want_usdz:
        rest_coefficient_count = 0 if splat_data.f_rest is None else splat_data.f_rest.shape[1]
        validate_usdz_payload_estimate(
            splat_data.count,
            1 + rest_coefficient_count // 3,
            half_precision,
        )

    if max_splats_per_prim < 0:
        raise ValueError(f"max_splats_per_prim must be non-negative, got {max_splats_per_prim}")
    if 0 < max_splats_per_prim < splat_data.count:
        partitions = partition_indices(splat_data.positions, max_splats_per_prim)
    else:
        partitions = []
    if partitions:
        print(
            f"[3DGS] Warning: {splat_data.count:,} splats exceed the "
            f"{max_splats_per_prim:,}-splat per-prim renderer threshold; "
            f"splitting into {len(partitions)} ParticleField prims."
        )

    # Inside a .usdz the splat arrays go to a binary crate layer, which is 3.4x
    # smaller and much faster to serialize than the equivalent text. A small text
    # root sublayers it, so the composition stays readable when the archive is
    # opened by hand.
    layer_path = base + ".usdc" if want_usdz else output_path

    src_label = os.path.basename(source_file) if source_file else "(from PLY/SPZ import)"

    partition_label = f" in {len(partitions)} prims" if partitions else ""
    print(f"[3DGS] Writing {splat_data.count:,} splats{partition_label} -> {output_path}")
    _p(0.05, "Creating USD stage...")

    stage = Usd.Stage.CreateNew(layer_path)
    UsdGeom.SetStageUpAxis(stage, _up_axis_token(up_axis))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)

    if partitions:
        parent = UsdGeom.Xform.Define(stage, prim_path)
        parent_prim = parent.GetPrim()
        stage.SetDefaultPrim(parent_prim)
        _set_prim_display_name_usd(parent_prim, prim_display_name)
        _set_transform_stack(parent_prim, rotation_degrees)

        width = max(3, len(str(len(partitions) - 1)))
        for partition_index, indices in enumerate(partitions):
            partition_name = f"Partition_{partition_index:0{width}d}"
            partition_path = f"{prim_path}/{partition_name}"

            def _partition_progress(fraction, message=None, index=partition_index):
                scaled = 0.05 + 0.80 * (index + fraction) / len(partitions)
                prefix = f"Partition {index + 1}/{len(partitions)}"
                _p(scaled, f"{prefix}: {message}" if message else prefix)

            _gaussian_splat_data_to_usd(
                select_splats(splat_data, indices),
                stage,
                partition_path,
                partition_name,
                progress_fn=_partition_progress,
                up_axis=up_axis,
                rotation_degrees=(0.0, 0.0, 0.0),
                projection_mode_hint=projection_mode_hint,
                sorting_mode_hint=sorting_mode_hint,
                half_precision=half_precision,
                set_default_prim=False,
            )
    else:
        _gaussian_splat_data_to_usd(
            splat_data,
            stage,
            prim_path,
            prim_name,
            progress_fn=_p,
            up_axis=up_axis,
            rotation_degrees=rotation_degrees,
            prim_display_name=prim_display_name,
            projection_mode_hint=projection_mode_hint,
            sorting_mode_hint=sorting_mode_hint,
            half_precision=half_precision,
        )

    # Provenance belongs on whichever layer a consumer opens first. For .usdz that
    # is the composition root written below, so putting it here too would only
    # duplicate it inside the package.
    if not want_usdz:
        stage.GetRootLayer().comment = _provenance_comment(src_label)

    _p(0.90, "Saving USD...")
    stage.Save()

    if want_usdz:
        _p(0.95, "Packaging USDZ...")
        root_path = base + ".usda"
        _write_composition_root(root_path, os.path.basename(layer_path), prim_path, up_axis, src_label)
        # USD keeps a crate layer memory-mapped for as long as a stage holds it,
        # and Windows refuses to delete a file with an open handle. Release ours
        # before packaging clears the intermediates away.
        stage = None
        _package_usdz(output_path, root_path, layer_path, splat_data.count)

    print(f"[3DGS] Saved -> {output_path}")
    return output_path


def convertPlyUSD(
    input_file: str,
    output_file: str,
    prim_name: str = None,
    generateSh: bool = False,
    generateScales: bool = False,
    up_axis: str = UP_AXIS_Y,
    rotation_degrees: tuple = (0.0, 0.0, 0.0),
    projection_mode_hint: str = DEFAULT_PROJECTION_MODE_HINT,
    sorting_mode_hint: str = DEFAULT_SORTING_MODE_HINT,
    half_precision: bool = False,
    max_splats_per_prim: int = DEFAULT_MAX_SPLATS_PER_PRIM,
) -> None:
    """
    Convert a PLY Gaussian Splat file to USD.

    Thin wrapper retained for API compatibility. It reads the PLY and delegates
    to :func:`write_gaussian_splat_usd`, which is the single authoring
    implementation; previously this function authored the stage itself, which
    let the two paths drift apart.

    Parameters
    ----------
    input_file : path to the source .ply
    output_file : destination .usd, .usda, .usdc or .usdz
    prim_name : USD prim name; defaults to the output filename stem
    generateSh : deprecated and ignored. ``read_ply`` always derives DC
        coefficients from ``red``/``green``/``blue`` when ``f_dc_*`` is absent,
        for every entry point. Retained so existing callers keep working; slated
        for removal in a future release.
    generateScales : estimate scales from local neighbourhood spacing when the
        PLY has no ``scale_*`` properties (requires SciPy)
    up_axis : target stage up-axis, "Y" (default) or "Z"
    rotation_degrees : euler rotation (rx, ry, rz) in degrees, authored as a transform op
    projection_mode_hint : ``projectionModeHint`` token; ``perspective`` is the
        only value offered
    half_precision : author the schema's half-typed arrays instead of the float ones
    sorting_mode_hint : ``sortingModeHint`` token, ``zDepth`` (default) or
        ``cameraDistance``
    max_splats_per_prim : maximum splats per ParticleField prim; defaults to the
        conservative 8,000,000-splat renderer threshold, and zero disables it
    """
    input_file = resolve_local_path(input_file)
    output_file = resolve_local_path(output_file)

    splat_data = read_ply(input_file, generate_scales=generateScales)
    write_gaussian_splat_usd(
        splat_data,
        output_file,
        source_file=input_file,
        prim_name=prim_name,
        up_axis=up_axis,
        rotation_degrees=rotation_degrees,
        projection_mode_hint=projection_mode_hint,
        sorting_mode_hint=sorting_mode_hint,
        half_precision=half_precision,
        max_splats_per_prim=max_splats_per_prim,
    )
