# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: CC-BY-4.0 AND Apache-2.0
#
"""
Write GaussianSplatData to a standard 3DGS binary PLY file (float32).
Compatible with tools like SuperSplat, Luma AI, Polycam, etc.
"""

import os
import struct

import numpy as np

from .local_paths import resolve_local_path

_HEADER = """\
ply
format binary_little_endian 1.0
element vertex {n}
property float x
property float y
property float z
property float nx
property float ny
property float nz
property float f_dc_0
property float f_dc_1
property float f_dc_2
property float opacity
property float scale_0
property float scale_1
property float scale_2
property float rot_0
property float rot_1
property float rot_2
property float rot_3
{rest_props}end_header
"""

__all__ = ["write_ply"]


def write_ply(splat_data, output_path: str, progress_fn=None) -> str:
    """
    Write GaussianSplatData to a 3DGS binary PLY file.

    Parameters
    ----------
    splat_data  : GaussianSplatData
    output_path : Destination .ply path
    progress_fn : Optional callable(fraction, message)

    Returns
    -------
    Actual output path written.
    """
    output_path = resolve_local_path(output_path)

    def _p(f, msg=None):
        if progress_fn:
            progress_fn(f, msg)

    N = splat_data.count
    _p(0.05, f"Preparing {N:,} splats for PLY export...")

    K = splat_data.f_rest.shape[1] if splat_data.f_rest is not None else 0
    rest_props = "".join(f"property float f_rest_{i}\n" for i in range(K))

    header = _HEADER.format(n=N, rest_props=rest_props).encode("ascii")

    _p(0.20, "Encoding positions...")
    pos = splat_data.positions.astype("<f4")

    nrm = np.zeros((N, 3), dtype="<f4")

    _p(0.35, "Encoding colours...")
    fdc = splat_data.f_dc.astype("<f4")

    _p(0.50, "Encoding opacity & scales...")
    opa = splat_data.opacities.reshape(N, 1).astype("<f4")
    sc = splat_data.scales.astype("<f4")

    _p(0.65, "Encoding rotations...")
    rot = splat_data.rotations.astype("<f4")

    _p(0.75, "Encoding SH rest coefficients...")
    if K > 0:
        rest = splat_data.f_rest.astype("<f4")
    else:
        rest = np.empty((N, 0), dtype="<f4")

    _p(0.82, "Interleaving vertex data...")
    parts = [pos, nrm, fdc, opa, sc, rot]
    if K > 0:
        parts.append(rest)
    vertex_data = np.concatenate(parts, axis=1).astype("<f4")

    _p(0.90, f"Writing {output_path}...")
    if not output_path.lower().endswith(".ply"):
        output_path = output_path + ".ply"

    with open(output_path, "wb") as f:
        f.write(header)
        f.write(vertex_data.tobytes())

    size_mb = os.path.getsize(output_path) / 1_048_576
    print(f"[3DGS] PLY written -> {output_path}  ({size_mb:.1f} MB, {N:,} splats)")
    _p(1.0, f"Exported {N:,} splats -> {os.path.basename(output_path)}")
    return output_path
