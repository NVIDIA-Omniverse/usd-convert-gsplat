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

import math
import os
import re
import zipfile

from pxr import Gf, Sdf, Tf, Usd, UsdGeom, Vt

from .local_paths import resolve_local_path

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

_PARTICLE_FIELD_3D_GAUSSIAN_SPLAT = "ParticleField3DGaussianSplat"

_PRIM_CREATE_FAILURE_MSG = (
    f"Failed to create {_PARTICLE_FIELD_3D_GAUSSIAN_SPLAT} prim. "
    'Install USD support with pip install "usd-convert-gsplat[usd]" '
    "(usd-core>=26.3 on x86_64; usd-exchange on linux-aarch64)."
)

UP_AXIS_Y = "Y"
UP_AXIS_Z = "Z"

__all__ = ["write_gaussian_splat_usd", "convertPlyUSD", "UP_AXIS_Y", "UP_AXIS_Z"]


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


def _up_axis_token(up_axis: str):
    """Return the UsdGeom token for the given up-axis string."""
    if up_axis and up_axis.upper() == UP_AXIS_Z:
        return UsdGeom.Tokens.z
    return UsdGeom.Tokens.y


def _euler_to_rotation(rx_deg: float, ry_deg: float, rz_deg: float):
    """
    Build a 3x3 rotation matrix and quaternion (w, x, y, z) from euler
    angles in degrees, applied in XYZ order (Rx first, then Ry, then Rz).

    Returns (R, quat) where R is a 3x3 list-of-lists and quat is (w, x, y, z).
    """
    rx, ry, rz = math.radians(rx_deg), math.radians(ry_deg), math.radians(rz_deg)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)

    # R = Rz * Ry * Rx
    R = [
        [cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz],
        [cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz],
        [-sy, sx * cy, cx * cy],
    ]

    # Quaternion from rotation matrix (Shepperd's method)
    trace = R[0][0] + R[1][1] + R[2][2]
    if trace > 0:
        s = 2.0 * math.sqrt(trace + 1.0)
        w = 0.25 * s
        x = (R[2][1] - R[1][2]) / s
        y = (R[0][2] - R[2][0]) / s
        z = (R[1][0] - R[0][1]) / s
    elif R[0][0] > R[1][1] and R[0][0] > R[2][2]:
        s = 2.0 * math.sqrt(1.0 + R[0][0] - R[1][1] - R[2][2])
        w = (R[2][1] - R[1][2]) / s
        x = 0.25 * s
        y = (R[0][1] + R[1][0]) / s
        z = (R[0][2] + R[2][0]) / s
    elif R[1][1] > R[2][2]:
        s = 2.0 * math.sqrt(1.0 + R[1][1] - R[0][0] - R[2][2])
        w = (R[0][2] - R[2][0]) / s
        x = (R[0][1] + R[1][0]) / s
        y = 0.25 * s
        z = (R[1][2] + R[2][1]) / s
    else:
        s = 2.0 * math.sqrt(1.0 + R[2][2] - R[0][0] - R[1][1])
        w = (R[1][0] - R[0][1]) / s
        x = (R[0][2] + R[2][0]) / s
        y = (R[1][2] + R[2][1]) / s
        z = 0.25 * s

    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm > 0:
        w, x, y, z = w / norm, x / norm, y / norm, z / norm

    return R, (w, x, y, z)


def _apply_euler_rotation(positions, rotations, rx_deg, ry_deg, rz_deg):
    """
    Rotate positions (N,3) and orientations (N,4 as w,x,y,z) by the given
    euler angles (degrees, XYZ order).

    Returns (positions, rotations) as new arrays; inputs are not modified.
    Returns inputs unchanged when all angles are zero.
    """
    if rx_deg == 0.0 and ry_deg == 0.0 and rz_deg == 0.0:
        return positions, rotations

    R, (rw, rx, ry, rz) = _euler_to_rotation(rx_deg, ry_deg, rz_deg)

    # Rotate positions: p' = R @ p
    pos = positions.copy()
    px, py, pz = pos[:, 0].copy(), pos[:, 1].copy(), pos[:, 2].copy()
    pos[:, 0] = R[0][0] * px + R[0][1] * py + R[0][2] * pz
    pos[:, 1] = R[1][0] * px + R[1][1] * py + R[1][2] * pz
    pos[:, 2] = R[2][0] * px + R[2][1] * py + R[2][2] * pz

    # Rotate orientations: q' = r * q  (Hamilton product)
    if rotations is not None:
        rot = rotations.copy()
        qw, qx, qy, qz = rot[:, 0].copy(), rot[:, 1].copy(), rot[:, 2].copy(), rot[:, 3].copy()
        rot[:, 0] = rw * qw - rx * qx - ry * qy - rz * qz
        rot[:, 1] = rw * qx + rx * qw + ry * qz - rz * qy
        rot[:, 2] = rw * qy - rx * qz + ry * qw + rz * qx
        rot[:, 3] = rw * qz + rx * qy - ry * qx + rz * qw
    else:
        rot = rotations

    return pos, rot


def _gaussian_splat_data_to_usd(
    splat_data,
    stage: Usd.Stage,
    prim_path: str,
    prim_name: str,
    source_file: str,
    progress_fn=None,
    up_axis: str = UP_AXIS_Y,
    rotation_degrees: tuple = (0.0, 0.0, 0.0),
    prim_display_name: str = None,
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
    source_file : str
        Path to source file (for metadata).
    prim_display_name : str, optional
        If set, stored as ``displayName`` metadata (typically the original import file stem).
    progress_fn : callable, optional
        progress_fn(fraction, message)
    up_axis : str
        Target stage up-axis ("Y" or "Z").
    rotation_degrees : tuple of (float, float, float)
        Euler rotation (rx, ry, rz) in degrees applied to positions and
        orientations before writing.  Use to correct source orientation.
    """

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

    positions, rotations = _apply_euler_rotation(
        positions,
        rotations,
        *rotation_degrees,
    )

    _p(0.10, "Creating Gaussian Splat prim...")

    if _HasParticleField3DGaussianSplat:
        gs_prim = UsdVol.ParticleField3DGaussianSplat.Define(stage, prim_path)
    else:
        prim = stage.DefinePrim(prim_path, _PARTICLE_FIELD_3D_GAUSSIAN_SPLAT)
        if not prim or not prim.IsValid():
            raise RuntimeError(_PRIM_CREATE_FAILURE_MSG)
        gs_prim = prim

    stage.SetDefaultPrim(gs_prim.GetPrim() if hasattr(gs_prim, "GetPrim") else gs_prim)

    prim0 = gs_prim.GetPrim() if hasattr(gs_prim, "GetPrim") else gs_prim
    if prim_display_name is not None:
        _set_prim_display_name_usd(prim0, prim_display_name)

    positions_vt = Vt.Vec3fArray(
        [Gf.Vec3f(float(positions[i, 0]), float(positions[i, 1]), float(positions[i, 2])) for i in range(vertex_count)]
    )
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
    scales_vt = Vt.Vec3fArray(
        [
            Gf.Vec3f(
                math.exp(float(scales[i, 0])),
                math.exp(float(scales[i, 1])),
                math.exp(float(scales[i, 2])),
            )
            for i in range(vertex_count)
        ]
    )
    orientations_list = []
    for i in range(vertex_count):
        w, x, y, z = float(rotations[i, 0]), float(rotations[i, 1]), float(rotations[i, 2]), float(rotations[i, 3])
        quat = Gf.Quatf(w, x, y, z)
        quat.Normalize()
        orientations_list.append(quat)
    orientations_vt = Vt.QuatfArray(orientations_list)
    opacities_vt = Vt.FloatArray([1.0 / (1.0 + math.exp(-float(opacities[i]))) for i in range(vertex_count)])

    prim = gs_prim.GetPrim() if hasattr(gs_prim, "GetPrim") else gs_prim

    def _set_attr(name, value, type_name):
        attr = prim.CreateAttribute(name, type_name)
        if attr:
            attr.Set(value)

    _p(0.20, "Processing positions...")
    if _HasParticleField3DGaussianSplat:
        gs_prim.CreatePositionsAttr(positions_vt)
    else:
        _set_attr("positions", positions_vt, Sdf.ValueTypeNames.Point3fArray)

    UsdGeom.Boundable(prim).CreateExtentAttr(extent)

    _p(0.35, "Processing scales...")
    if _HasParticleField3DGaussianSplat:
        gs_prim.CreateScalesAttr(scales_vt)
    else:
        _set_attr("scales", scales_vt, Sdf.ValueTypeNames.Float3Array)

    _p(0.50, "Processing orientations...")
    if _HasParticleField3DGaussianSplat:
        gs_prim.CreateOrientationsAttr(orientations_vt)
    else:
        _set_attr("orientations", orientations_vt, Sdf.ValueTypeNames.QuatfArray)

    _p(0.65, "Processing opacities...")
    if _HasParticleField3DGaussianSplat:
        gs_prim.CreateOpacitiesAttr(opacities_vt)
    else:
        _set_attr("opacities", opacities_vt, Sdf.ValueTypeNames.FloatArray)

    _p(0.80, "Processing spherical harmonics...")
    K = f_rest.shape[1] if f_rest is not None and f_rest.shape[1] > 0 else 0
    sh_degree = {0: 0, 9: 1, 24: 2, 45: 3}.get(K, 3 if K > 0 else 0)

    if _HasParticleField3DGaussianSplat:
        gs_prim.CreateRadianceSphericalHarmonicsDegreeAttr(sh_degree)
    else:
        _set_attr("radiance:sphericalHarmonicsDegree", sh_degree, Sdf.ValueTypeNames.Int)

    if K > 0:
        num_sh_vec3 = K // 3
        sh_vec_stride = 1 + num_sh_vec3
        # PLY stores f_rest in channel-major order; USD expects vec3-major.
        # SPZ stores coefficient-major (vec3-major) per format spec.
        from_ply = not (source_file and source_file.lower().endswith(".spz"))
        sh_data = []
        for i in range(vertex_count):
            vertex_sh = []
            vertex_sh.append([float(f_dc[i, 0]), float(f_dc[i, 1]), float(f_dc[i, 2])])
            for j in range(num_sh_vec3):
                if from_ply:
                    vertex_sh.append(
                        [
                            float(f_rest[i, j]),
                            float(f_rest[i, num_sh_vec3 + j]),
                            float(f_rest[i, 2 * num_sh_vec3 + j]),
                        ]
                    )
                else:
                    idx = j * 3
                    vertex_sh.append(
                        [
                            float(f_rest[i, idx]),
                            float(f_rest[i, idx + 1]),
                            float(f_rest[i, idx + 2]),
                        ]
                    )
            sh_data.extend(vertex_sh)
        sh_vt = Vt.Vec3fArray([Gf.Vec3f(float(v[0]), float(v[1]), float(v[2])) for v in sh_data])
    else:
        sh_vec_stride = 1
        sh_vt = Vt.Vec3fArray(
            [Gf.Vec3f(float(f_dc[i, 0]), float(f_dc[i, 1]), float(f_dc[i, 2])) for i in range(vertex_count)]
        )

    if _HasParticleField3DGaussianSplat:
        sh_attr = gs_prim.CreateRadianceSphericalHarmonicsCoefficientsAttr(sh_vt)
    else:
        sh_attr = prim.CreateAttribute("radiance:sphericalHarmonicsCoefficients", Sdf.ValueTypeNames.Float3Array)
        if sh_attr:
            sh_attr.Set(sh_vt)
    if sh_attr:
        sh_primvar = UsdGeom.Primvar(sh_attr)
        sh_primvar.SetElementSize(sh_vec_stride)
        sh_primvar.SetInterpolation(UsdGeom.Tokens.vertex)

    _SH_C0 = 0.28209479177387814
    display_colors = []
    for i in range(vertex_count):
        r = 0.5 + _SH_C0 * float(f_dc[i, 0])
        g = 0.5 + _SH_C0 * float(f_dc[i, 1])
        b = 0.5 + _SH_C0 * float(f_dc[i, 2])
        r = max(0.0, min(1.0, r))
        g = max(0.0, min(1.0, g))
        b = max(0.0, min(1.0, b))
        display_colors.append(Gf.Vec3f(r, g, b))
    primvars_api = UsdGeom.PrimvarsAPI(prim)
    display_color_primvar = primvars_api.CreatePrimvar(
        "displayColor", Sdf.ValueTypeNames.Color3fArray, UsdGeom.Tokens.vertex
    )
    if display_color_primvar:
        display_color_primvar.Set(Vt.Vec3fArray(display_colors))

    stage.GetRootLayer().comment = (
        f"Converted from PLY/SPZ to USD using usd-convert-gsplat\n" f"Source file: {source_file}"
    )


def write_gaussian_splat_usd(
    splat_data,
    output_path: str,
    progress_fn=None,
    source_file: str = None,
    prim_name: str = None,
    up_axis: str = UP_AXIS_Y,
    rotation_degrees: tuple = (0.0, 0.0, 0.0),
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
        Euler rotation (rx, ry, rz) in degrees applied to positions and
        orientations before writing.  Use to correct source orientation
        (e.g. 180,0,0 for COLMAP Y-down data).

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
    output_path = base + ext  # return the path that will actually be written

    want_usdz = ext.lower() == ".usdz"
    layer_path = base + ".usda" if want_usdz else output_path

    src_label = source_file if source_file else "(from PLY/SPZ import)"

    print(f"[3DGS] Writing {splat_data.count:,} splats -> {output_path}")
    _p(0.05, "Creating USD stage...")

    stage = Usd.Stage.CreateNew(layer_path)
    UsdGeom.SetStageUpAxis(stage, _up_axis_token(up_axis))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)

    _gaussian_splat_data_to_usd(
        splat_data,
        stage,
        prim_path,
        prim_name,
        source_file=src_label,
        progress_fn=_p,
        up_axis=up_axis,
        rotation_degrees=rotation_degrees,
        prim_display_name=prim_display_name,
    )

    _p(0.90, "Saving USD...")
    stage.Save()

    if want_usdz:
        _p(0.95, "Packaging USDZ...")
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_STORED) as zf:
            zf.write(layer_path, "default.usda")
        os.remove(layer_path)

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
) -> None:
    """
    Convert PLY Gaussian Splat file to USD (Pixar reference implementation).

    Uses the typed UsdVol.ParticleField3DGaussianSplat API when available
    (OpenUSD 26.03+), or defines the prim type and attributes manually.

    Parameters
    ----------
    up_axis : str, optional
        Target stage up-axis: "Y" (default) or "Z".
    rotation_degrees : tuple of (float, float, float)
        Euler rotation (rx, ry, rz) in degrees applied to positions and
        orientations before writing.  Use to correct source orientation.
    """
    input_file = resolve_local_path(input_file)
    output_file = resolve_local_path(output_file)

    prim_display_name = os.path.splitext(os.path.basename(input_file))[0]
    if prim_name is None:
        prim_name = os.path.splitext(os.path.basename(input_file))[0]
    prim_name = _valid_usd_prim_name(prim_name)

    print(f"Input PLY file: {input_file}")
    print(f"Output USD file: {output_file}")
    print(f"Prim name: /{prim_name}")

    from .ply_reader import read_ply_raw

    vertex_data, vertex_count, property_names = read_ply_raw(input_file)

    print(f"\nPLY Data Information:")
    print(f"Vertex count: {vertex_count}")
    print(f"Available properties: {tuple(property_names)}")

    import numpy as np

    if all(k in vertex_data for k in ("x", "y", "z")):
        _pos = np.stack([vertex_data["x"], vertex_data["y"], vertex_data["z"]], axis=1)
        _has_rot = all(k in vertex_data for k in ("rot_0", "rot_1", "rot_2", "rot_3"))
        _rot = (
            np.stack([vertex_data["rot_0"], vertex_data["rot_1"], vertex_data["rot_2"], vertex_data["rot_3"]], axis=1)
            if _has_rot
            else None
        )
        _pos, _rot = _apply_euler_rotation(_pos, _rot, *rotation_degrees)
        vertex_data["x"], vertex_data["y"], vertex_data["z"] = _pos[:, 0], _pos[:, 1], _pos[:, 2]
        if _rot is not None:
            vertex_data["rot_0"], vertex_data["rot_1"] = _rot[:, 0], _rot[:, 1]
            vertex_data["rot_2"], vertex_data["rot_3"] = _rot[:, 2], _rot[:, 3]

    base, ext = os.path.splitext(output_file)
    want_usdz = ext and ext.lower() == ".usdz"
    layer_path = base + ".usda" if want_usdz else output_file

    stage = Usd.Stage.CreateNew(layer_path)
    UsdGeom.SetStageUpAxis(stage, _up_axis_token(up_axis))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    stage.GetRootLayer().comment = (
        f"Converted from PLY to USD using usd-convert-gsplat (convertPlyUSD)\n" f"Source file: {input_file}"
    )

    prim_path = f"/{prim_name}"
    if _HasParticleField3DGaussianSplat:
        gs_prim = UsdVol.ParticleField3DGaussianSplat.Define(stage, prim_path)
    else:
        prim = stage.DefinePrim(prim_path, _PARTICLE_FIELD_3D_GAUSSIAN_SPLAT)
        if not prim or not prim.IsValid():
            raise RuntimeError(_PRIM_CREATE_FAILURE_MSG)
        gs_prim = prim

    stage.SetDefaultPrim(gs_prim.GetPrim() if hasattr(gs_prim, "GetPrim") else gs_prim)
    prim = gs_prim.GetPrim() if hasattr(gs_prim, "GetPrim") else gs_prim
    _set_prim_display_name_usd(prim, prim_display_name)

    def _set_attr(name, value, type_name):
        attr = prim.CreateAttribute(name, type_name)
        if attr:
            attr.Set(value)

    if all(prop in vertex_data for prop in ["x", "y", "z"]):
        print("\nProcessing positions...")
        positions = list(zip(vertex_data["x"], vertex_data["y"], vertex_data["z"]))
        positions_vt = Vt.Vec3fArray([Gf.Vec3f(float(p[0]), float(p[1]), float(p[2])) for p in positions])
        if _HasParticleField3DGaussianSplat:
            gs_prim.CreatePositionsAttr(positions_vt)
        else:
            _set_attr("positions", positions_vt, Sdf.ValueTypeNames.Point3fArray)

        min_x, min_y, min_z = min(vertex_data["x"]), min(vertex_data["y"]), min(vertex_data["z"])
        max_x, max_y, max_z = max(vertex_data["x"]), max(vertex_data["y"]), max(vertex_data["z"])
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
        UsdGeom.Boundable(prim).CreateExtentAttr(extent)
        print(f"  Set positions for {vertex_count} vertices")
        print(f"  Extent: {extent_min} to {extent_max}")
    else:
        print("ERROR: PLY file missing x, y, z position data")
        return

    if all(prop in vertex_data for prop in ["scale_0", "scale_1", "scale_2"]):
        print("\nProcessing scales...")
        scales = [
            (math.exp(s0), math.exp(s1), math.exp(s2))
            for s0, s1, s2 in zip(vertex_data["scale_0"], vertex_data["scale_1"], vertex_data["scale_2"])
        ]
        scales_vt = Vt.Vec3fArray([Gf.Vec3f(float(s[0]), float(s[1]), float(s[2])) for s in scales])
        if _HasParticleField3DGaussianSplat:
            gs_prim.CreateScalesAttr(scales_vt)
        else:
            _set_attr("scales", scales_vt, Sdf.ValueTypeNames.Float3Array)
        print(f"  Set scales for {vertex_count} vertices")
    elif generateScales:
        import numpy as np
        from scipy.spatial import KDTree

        points = np.array(positions)
        tree = KDTree(points)
        distances, _ = tree.query(points, k=3, workers=-1)
        scales = (distances[:, 0] + distances[:, 1] + distances[:, 2]) / (3.0 * 2.0)
        scales_vt = Vt.Vec3fArray([Gf.Vec3f(float(s), float(s), float(s)) for s in scales])
        if _HasParticleField3DGaussianSplat:
            gs_prim.CreateScalesAttr(scales_vt)
        else:
            _set_attr("scales", scales_vt, Sdf.ValueTypeNames.Float3Array)
        print(f"  Set scales for {vertex_count} vertices, generated from local neighborhood spacing")
    else:
        print("  Warning: PLY file missing scale_0, scale_1, scale_2 data. Consider re-running with --generateScales")

    if all(prop in vertex_data for prop in ["rot_0", "rot_1", "rot_2", "rot_3"]):
        print("\nProcessing orientations...")
        orientations = list(zip(vertex_data["rot_1"], vertex_data["rot_2"], vertex_data["rot_3"], vertex_data["rot_0"]))
        orientations_list = []
        for q in orientations:
            quat = Gf.Quatf(float(q[3]), float(q[0]), float(q[1]), float(q[2]))
            quat.Normalize()
            orientations_list.append(quat)
        orientations_vt = Vt.QuatfArray(orientations_list)
        if _HasParticleField3DGaussianSplat:
            gs_prim.CreateOrientationsAttr(orientations_vt)
        else:
            _set_attr("orientations", orientations_vt, Sdf.ValueTypeNames.QuatfArray)
        print(f"  Set orientations for {vertex_count} vertices")
    else:
        print("  Warning: PLY file missing rot_0, rot_1, rot_2, rot_3 data")

    if "opacity" in vertex_data:
        print("\nProcessing opacities...")
        opacities = [1.0 / (1.0 + math.exp(-v)) for v in vertex_data["opacity"]]
        opacities_vt = Vt.FloatArray(opacities)
        if _HasParticleField3DGaussianSplat:
            gs_prim.CreateOpacitiesAttr(opacities_vt)
        else:
            _set_attr("opacities", opacities_vt, Sdf.ValueTypeNames.FloatArray)
        print(f"  Set opacities for {vertex_count} vertices")
    else:
        print("  Warning: PLY file missing opacity data")

    if all(prop in vertex_data for prop in ["f_dc_0", "f_dc_1", "f_dc_2"]):
        print("\nProcessing spherical harmonics...")
        f_dc = list(zip(vertex_data["f_dc_0"], vertex_data["f_dc_1"], vertex_data["f_dc_2"]))

        max_sh_index = -1
        for i in range(45):
            prop_name = f"f_rest_{i}"
            if prop_name in vertex_data:
                max_sh_index = i
            else:
                break

        if max_sh_index == -1:
            sh_degree = 0
        elif max_sh_index == 8:
            sh_degree = 1
        elif max_sh_index == 23:
            sh_degree = 2
        elif max_sh_index == 44:
            sh_degree = 3
        else:
            print(f"  Warning: Invalid number of SH coefficients found ({max_sh_index})")
            sh_degree = 0

        print(f"  Found SH degree: {sh_degree}")
        if _HasParticleField3DGaussianSplat:
            gs_prim.CreateRadianceSphericalHarmonicsDegreeAttr(sh_degree)
        else:
            _set_attr("radiance:sphericalHarmonicsDegree", sh_degree, Sdf.ValueTypeNames.Int)

        if max_sh_index >= 0:
            stride = max_sh_index + 1
            f_rest_data = [vertex_data[f"f_rest_{i}"] for i in range(stride)]
            f_rest = list(zip(*f_rest_data))
            num_sh_vec3 = stride // 3
            sh_vec_stride = num_sh_vec3 + 1

            sh_data = []
            for i in range(vertex_count):
                vertex_sh = [[0.0, 0.0, 0.0] for _ in range(sh_vec_stride)]
                vertex_sh[0] = list(f_dc[i])
                for j in range(num_sh_vec3):
                    for k in range(3):
                        src_index = k * num_sh_vec3 + j
                        vertex_sh[j + 1][k] = f_rest[i][src_index]
                sh_data.extend(vertex_sh)

            sh_vt = Vt.Vec3fArray([Gf.Vec3f(float(v[0]), float(v[1]), float(v[2])) for v in sh_data])
            if _HasParticleField3DGaussianSplat:
                sh_attr = gs_prim.CreateRadianceSphericalHarmonicsCoefficientsAttr(sh_vt)
            else:
                sh_attr = prim.CreateAttribute(
                    "radiance:sphericalHarmonicsCoefficients", Sdf.ValueTypeNames.Float3Array
                )
                if sh_attr:
                    sh_attr.Set(sh_vt)
            if sh_attr:
                sh_primvar = UsdGeom.Primvar(sh_attr)
                sh_primvar.SetElementSize(sh_vec_stride)
                sh_primvar.SetInterpolation(UsdGeom.Tokens.vertex)
            print(f"  Set spherical harmonics with {sh_vec_stride} coefficients per vertex")
        else:
            if _HasParticleField3DGaussianSplat:
                gs_prim.CreateRadianceSphericalHarmonicsDegreeAttr(0)
            else:
                _set_attr("radiance:sphericalHarmonicsDegree", 0, Sdf.ValueTypeNames.Int)
            sh_vt = Vt.Vec3fArray([Gf.Vec3f(float(v[0]), float(v[1]), float(v[2])) for v in f_dc])
            if _HasParticleField3DGaussianSplat:
                sh_attr = gs_prim.CreateRadianceSphericalHarmonicsCoefficientsAttr(sh_vt)
            else:
                sh_attr = prim.CreateAttribute(
                    "radiance:sphericalHarmonicsCoefficients", Sdf.ValueTypeNames.Float3Array
                )
                if sh_attr:
                    sh_attr.Set(sh_vt)
            if sh_attr:
                sh_primvar = UsdGeom.Primvar(sh_attr)
                sh_primvar.SetElementSize(1)
                sh_primvar.SetInterpolation(UsdGeom.Tokens.vertex)
            print("  Set spherical harmonics with degree 0 (DC only)")

    elif all(prop in vertex_data for prop in ["red", "green", "blue"]):
        if generateSh:
            _SH_C0 = 0.28209479177387814
            sh_dc = Vt.Vec3fArray(
                [
                    Gf.Vec3f(
                        (float(v[0]) / 255.0 - 0.5) / _SH_C0,
                        (float(v[1]) / 255.0 - 0.5) / _SH_C0,
                        (float(v[2]) / 255.0 - 0.5) / _SH_C0,
                    )
                    for v in zip(vertex_data["red"], vertex_data["green"], vertex_data["blue"])
                ]
            )
            if _HasParticleField3DGaussianSplat:
                gs_prim.CreateRadianceSphericalHarmonicsDegreeAttr(0)
                sh_attr = gs_prim.CreateRadianceSphericalHarmonicsCoefficientsAttr(sh_dc)
            else:
                _set_attr("radiance:sphericalHarmonicsDegree", 0, Sdf.ValueTypeNames.Int)
                sh_attr = prim.CreateAttribute(
                    "radiance:sphericalHarmonicsCoefficients", Sdf.ValueTypeNames.Float3Array
                )
                if sh_attr:
                    sh_attr.Set(sh_dc)
            if sh_attr:
                sh_primvar = UsdGeom.Primvar(sh_attr)
                sh_primvar.SetElementSize(1)
                sh_primvar.SetInterpolation(UsdGeom.Tokens.vertex)
            print("  Set spherical harmonics with degree 0 (DC only) generated from (red/green/blue)")
        else:
            print(
                "  Warning: PLY file missing spherical harmonics data (f_dc_0/1/2). PLY file contains (red/green/blue); consider re-running with --generateSh"
            )
    else:
        print("  Warning: PLY file missing spherical harmonics data (f_dc_0/1/2).")

    if all(prop in vertex_data for prop in ["f_dc_0", "f_dc_1", "f_dc_2"]):
        _SH_C0 = 0.28209479177387814
        display_colors = []
        for v in zip(vertex_data["f_dc_0"], vertex_data["f_dc_1"], vertex_data["f_dc_2"]):
            r = max(0.0, min(1.0, 0.5 + _SH_C0 * float(v[0])))
            g = max(0.0, min(1.0, 0.5 + _SH_C0 * float(v[1])))
            b = max(0.0, min(1.0, 0.5 + _SH_C0 * float(v[2])))
            display_colors.append(Gf.Vec3f(r, g, b))
        primvars_api = UsdGeom.PrimvarsAPI(prim)
        pv = primvars_api.CreatePrimvar("displayColor", Sdf.ValueTypeNames.Color3fArray, UsdGeom.Tokens.vertex)
        if pv:
            pv.Set(Vt.Vec3fArray(display_colors))

    stage.Save()

    if want_usdz:
        with zipfile.ZipFile(output_file, "w", zipfile.ZIP_STORED) as zf:
            zf.write(layer_path, "default.usda")
        os.remove(layer_path)

    print(f"\nSuccessfully saved USD file: {output_file}")
