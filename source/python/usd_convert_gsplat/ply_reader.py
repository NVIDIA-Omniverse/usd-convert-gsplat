# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: CC-BY-4.0 AND Apache-2.0
#
"""
PLY reader for 3D Gaussian Splat files.

Supports the standard 3DGS format (gaussian-splatting).
Handles binary little-endian, binary big-endian, and ASCII PLY files.

Implementation aligned with Pixar reference:
  py3dgsPlyToUsd.py (USD spzToUSD-nextsteps branch)
"""

import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from .local_paths import resolve_local_path

__all__ = ["GaussianSplatData", "read_ply", "read_ply_raw"]


@dataclass
class GaussianSplatData:
    """Parsed Gaussian Splat data from a PLY file."""

    positions: np.ndarray  # (N, 3) float32 - xyz center positions
    scales: np.ndarray  # (N, 3) float32 - log-scale per axis
    rotations: np.ndarray  # (N, 4) float32 - unit quaternion (w, x, y, z)
    opacities: np.ndarray  # (N,)   float32 - raw opacity (pre-sigmoid)
    f_dc: np.ndarray  # (N, 3) float32 - DC spherical harmonic (base RGB)
    f_rest: Optional[np.ndarray] = None  # (N, K) float32 - higher-order SH coeffs
    count: int = 0

    def __post_init__(self):
        self.count = self.positions.shape[0]


_PLY_TYPE_MAP: Dict[str, Tuple[str, int]] = {
    "float": ("f", 4),
    "float32": ("f", 4),
    "double": ("d", 8),
    "float64": ("d", 8),
    "int": ("i", 4),
    "int32": ("i", 4),
    "uint": ("I", 4),
    "uint32": ("I", 4),
    "short": ("h", 2),
    "int16": ("h", 2),
    "ushort": ("H", 2),
    "uint16": ("H", 2),
    "char": ("b", 1),
    "int8": ("b", 1),
    "uchar": ("B", 1),
    "uint8": ("B", 1),
}

_PLY_NP_TYPE_MAP: Dict[str, str] = {
    "float": "f4",
    "float32": "f4",
    "double": "f8",
    "float64": "f8",
    "int": "i4",
    "int32": "i4",
    "uint": "u4",
    "uint32": "u4",
    "short": "i2",
    "int16": "i2",
    "ushort": "u2",
    "uint16": "u2",
    "char": "i1",
    "int8": "i1",
    "uchar": "u1",
    "uint8": "u1",
}


def _parse_header(f) -> Tuple[int, List[Tuple[str, str]], str]:
    """
    Parse a PLY header.
    Returns (num_vertices, [(prop_name, prop_type), ...], format_string).
    """
    line = f.readline().decode("ascii").strip()
    if line != "ply":
        raise ValueError(f"Not a valid PLY file - missing 'ply' magic number (first line: '{line}')")

    fmt = "binary_little_endian"
    num_vertices = 0
    properties: List[Tuple[str, str]] = []
    in_vertex_element = False

    while True:
        line_bytes = f.readline()
        if not line_bytes:
            raise ValueError("Unexpected EOF in PLY header - missing 'end_header'")
        line = line_bytes.decode("ascii").strip()
        if line == "end_header":
            break

        parts = line.split()
        if not parts:
            continue

        if line.startswith("format"):
            parts = line.split()
            if len(parts) < 2:
                raise ValueError(f"Invalid format line in PLY header: '{line}'")
            fmt = parts[1]
        elif line.startswith("element vertex"):
            parts = line.split()
            if len(parts) < 3:
                raise ValueError(f"Invalid element vertex line in PLY header: '{line}'")
            try:
                num_vertices = int(parts[2])
            except ValueError:
                raise ValueError(f"Invalid vertex count in PLY header: '{parts[2]}'")
            in_vertex_element = True
        elif line.startswith("element"):
            in_vertex_element = False
        elif line.startswith("property") and in_vertex_element:
            parts = line.split()
            if len(parts) < 3:
                raise ValueError(f"Invalid property line in PLY header: '{line}'")
            prop_type = parts[1]
            prop_name = parts[2]
            if prop_type == "list":
                in_vertex_element = False
                continue
            if prop_type not in _PLY_TYPE_MAP:
                raise ValueError(f"Unsupported PLY property type: {prop_type}")
            properties.append((prop_name, prop_type))

    return num_vertices, properties, fmt


def _read_binary(
    f,
    num_vertices: int,
    properties: List[Tuple[str, str]],
    big_endian: bool,
) -> Dict[str, np.ndarray]:
    """Read binary PLY vertex data (numpy-accelerated)."""
    endian_char = ">" if big_endian else "<"

    dtype_list = []
    for name, ptype in properties:
        if ptype not in _PLY_NP_TYPE_MAP:
            raise ValueError(f"Unsupported PLY property type: {ptype}")
        dtype_list.append((name, endian_char + _PLY_NP_TYPE_MAP[ptype]))

    dtype = np.dtype(dtype_list)
    record_size = dtype.itemsize
    expected_bytes = num_vertices * record_size
    raw = f.read(expected_bytes)
    if len(raw) != expected_bytes:
        raise ValueError(
            f"Incomplete PLY data: expected {expected_bytes} bytes, got {len(raw)}. "
            "File may be truncated or corrupted."
        )
    arr = np.frombuffer(raw, dtype=dtype)

    return {name: arr[name].astype("f4") for name, _ in properties}


def _read_ascii(
    f,
    num_vertices: int,
    properties: List[Tuple[str, str]],
) -> Dict[str, np.ndarray]:
    """Read ASCII PLY vertex data."""
    for _, ptype in properties:
        if ptype not in _PLY_TYPE_MAP:
            raise ValueError(f"Unsupported PLY property type: {ptype}")
    prop_names = [p[0] for p in properties]
    n_props = len(prop_names)
    rows = []
    for i in range(num_vertices):
        line = f.readline()
        if not line:
            raise ValueError(
                f"Incomplete PLY data: expected {num_vertices} vertices, " f"got {len(rows)}. File may be truncated."
            )
        values = line.decode("ascii").strip().split()
        if len(values) < n_props:
            raise ValueError(f"Vertex {i}: expected {n_props} values, got {len(values)}. " "PLY may be malformed.")
        rows.append([float(v) for v in values[:n_props]])
    arr = np.array(rows, dtype=np.float32)
    return {name: arr[:, j] for j, name in enumerate(prop_names)}


def read_ply_raw(filepath: str) -> Tuple[Dict[str, np.ndarray], int, List[str]]:
    """
    Read PLY file and return raw vertex data.

    Returns
    -------
    data : dict
        Property names to numpy arrays.
    vertex_count : int
    property_names : list
    """
    filepath = resolve_local_path(filepath)
    with open(filepath, "rb") as f:
        num_vertices, properties, fmt = _parse_header(f)
        if num_vertices == 0:
            raise ValueError("PLY file contains no vertices")
        if fmt == "ascii":
            data = _read_ascii(f, num_vertices, properties)
        elif fmt == "binary_little_endian":
            data = _read_binary(f, num_vertices, properties, big_endian=False)
        elif fmt == "binary_big_endian":
            data = _read_binary(f, num_vertices, properties, big_endian=True)
        else:
            raise ValueError(f"Unsupported PLY format: {fmt}")
    prop_names = [p[0] for p in properties]
    return data, num_vertices, prop_names


def read_ply(filepath: str) -> GaussianSplatData:
    """
    Read a 3D Gaussian Splat PLY file (standard 3DGS format).

    Expected vertex properties (order may vary):
        x, y, z                     - position
        scale_0, scale_1, scale_2   - log-scale per axis
        rot_0..rot_3                - quaternion (w, x, y, z)
        opacity                     - pre-sigmoid opacity
        f_dc_0, f_dc_1, f_dc_2     - DC spherical harmonic coefficients
        f_rest_0 .. f_rest_N        - higher-order SH coefficients (optional)
    """
    filepath = resolve_local_path(filepath)
    print(f"[3DGS] Reading PLY file: {filepath}")
    data, num_vertices, _ = read_ply_raw(filepath)
    prop_names = set(data.keys())
    if "x" not in prop_names or "y" not in prop_names or "z" not in prop_names:
        raise ValueError("PLY file is missing required position properties (x, y, z)")

    positions = np.stack([data["x"], data["y"], data["z"]], axis=1)

    if all(k in data for k in ("scale_0", "scale_1", "scale_2")):
        scales = np.stack([data["scale_0"], data["scale_1"], data["scale_2"]], axis=1)
    else:
        print("[3DGS] Warning: scale_0/1/2 not found, defaulting to zero")
        scales = np.zeros((num_vertices, 3), dtype=np.float32)

    if all(k in data for k in ("rot_0", "rot_1", "rot_2", "rot_3")):
        rotations = np.stack([data["rot_0"], data["rot_1"], data["rot_2"], data["rot_3"]], axis=1)
        norms = np.linalg.norm(rotations, axis=1, keepdims=True)
        rotations = rotations / np.maximum(norms, 1e-8)
    else:
        print("[3DGS] Warning: rotation properties not found, defaulting to identity")
        rotations = np.zeros((num_vertices, 4), dtype=np.float32)
        rotations[:, 0] = 1.0

    if "opacity" in data:
        opacities = data["opacity"]
    else:
        print("[3DGS] Warning: opacity property not found, defaulting to 0")
        opacities = np.zeros(num_vertices, dtype=np.float32)

    _SH_C0 = 0.28209479177387814
    if all(k in data for k in ("f_dc_0", "f_dc_1", "f_dc_2")):
        f_dc = np.stack([data["f_dc_0"], data["f_dc_1"], data["f_dc_2"]], axis=1)
    elif "red" in data and "green" in data and "blue" in data:
        rgb = np.stack([data["red"], data["green"], data["blue"]], axis=1).astype(np.float32)
        f_dc = ((rgb / 255.0) - 0.5) / _SH_C0
        print("[3DGS] Converted red/green/blue to f_dc (SH DC coefficients)")
    else:
        print("[3DGS] Warning: f_dc and red/green/blue not found, defaulting to gray")
        f_dc = np.full((num_vertices, 3), 0.5 / _SH_C0, dtype=np.float32)

    rest_keys = sorted(
        [k for k in data if k.startswith("f_rest_")],
        key=lambda k: int(k.split("_")[-1]),
    )
    f_rest = np.stack([data[k] for k in rest_keys], axis=1).astype(np.float32) if rest_keys else None

    n_rest = len(rest_keys)
    print(
        f"[3DGS] Loaded {num_vertices:,} splats | "
        f"SH degree: {'3' if n_rest == 45 else '2' if n_rest == 24 else '1' if n_rest == 9 else str(n_rest) + ' coeffs'}"
    )

    return GaussianSplatData(
        positions=positions.astype(np.float32),
        scales=scales.astype(np.float32),
        rotations=rotations.astype(np.float32),
        opacities=opacities.astype(np.float32),
        f_dc=f_dc.astype(np.float32),
        f_rest=f_rest,
    )
