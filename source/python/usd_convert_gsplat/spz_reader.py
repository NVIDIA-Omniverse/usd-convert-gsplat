# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: CC-BY-4.0 AND Apache-2.0
#
"""
SPZ reader for Niantic-format compressed Gaussian Splat files.

SPZ is a gzip-compressed binary format.  After decompression the layout is:

  Header (16 bytes):
    uint32  magic          = 0x5053474E  ("NGSP")
    uint32  version        = 2 or 3
    uint32  numPoints
    uint8   shDegree       (0-3)
    uint8   fractionalBits (position fixed-point precision, typically 12)
    uint8   flags          (bit 0 = antialiased)
    uint8   reserved

  Data (all per-splat values, in this order):
    positions   3 x N x 3 bytes   (24-bit little-endian signed int per component)
    alphas          N x 1 byte    (uint8,  sigmoid-encoded opacity)
    colors      3 x N x 1 byte   (uint8,  SH DC colour channels R,G,B)
    scales      3 x N x 1 byte   (uint8,  log-scale per axis)
    rotations   (version 2)  3 x N x 1 byte  (int8 x,y,z; w reconstructed)
                (version 3+) 4 x N x 1 byte  (uint32 smallest-3 quaternion)
    sh_rest     numRestCoeffs x N x 1 byte   (int8, coefficient-major order)

References:
    https://github.com/nianticlabs/spz
    https://pdal.io/en/2.9.0/stages/readers.spz.html
"""

import gzip
import math
import struct
from typing import Optional

import numpy as np

from .local_paths import resolve_local_path
from .ply_reader import SH_LAYOUT_VEC3_MAJOR, GaussianSplatData, GaussianSplatMetadata

_SPZ_MAGIC = 0x5053474E  # "NGSP" as little-endian uint32
_SUPPORTED_VERSIONS = (2, 3)

_COLOR_SCALE = 0.15

# Hard cap on decompressed .spz stream size, to bound the allocation from an
# untrusted gzip input and reject decompression bombs (CWE-409 / CWE-400).
_MAX_DECOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB


def _num_rest_coeffs(sh_degree: int) -> int:
    """Number of higher-order SH coefficients per splat (excluding DC)."""
    if sh_degree == 0:
        return 0
    return 3 * ((sh_degree + 1) ** 2 - 1)


def _parse_spz_header(header: bytes) -> tuple[int, int, int, int, int]:
    if len(header) < 16:
        raise ValueError("SPZ file too small to contain a valid header")

    magic, version, num_points, sh_degree, fractional_bits, flags, _ = struct.unpack_from("<IIIBBBB", header, 0)
    if magic != _SPZ_MAGIC:
        raise ValueError(f"Not an SPZ file (magic 0x{magic:08X}, expected 0x{_SPZ_MAGIC:08X})")
    if version not in _SUPPORTED_VERSIONS:
        raise ValueError(f"Unsupported SPZ version: {version}")
    if sh_degree > 3:
        raise ValueError(f"Invalid SH degree: {sh_degree}")
    if num_points <= 0:
        raise ValueError(f"SPZ file contains no splats (numPoints={num_points})")

    return version, num_points, sh_degree, fractional_bits, flags


def read_spz_metadata(filepath: str) -> GaussianSplatMetadata:
    """Read the splat count and SH degree from the compressed SPZ header only."""
    filepath = resolve_local_path(filepath)
    with gzip.open(filepath, "rb") as f:
        header = f.read(16)
    _, num_points, sh_degree, _, _ = _parse_spz_header(header)
    return GaussianSplatMetadata(
        count=num_points,
        sh_coefficient_count=(sh_degree + 1) ** 2,
    )


def _read_int24_block(raw: bytes, count: int) -> np.ndarray:
    """Decode `count` packed 24-bit little-endian signed integers."""
    b = np.frombuffer(raw, dtype=np.uint8).reshape(count, 3)
    vals = b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16)
    vals[vals >= 0x800000] -= 0x1000000
    return vals.astype(np.float32)


def _decode_positions(raw: bytes, N: int, fractional_bits: int) -> np.ndarray:
    """Decode N x 3 positions from 9N bytes of packed int24 values."""
    vals = _read_int24_block(raw, N * 3)
    scale = 1.0 / float(1 << fractional_bits)
    return (vals * scale).reshape(N, 3)


def _decode_scales(raw: bytes, N: int) -> np.ndarray:
    """Decode N x 3 log-scales from 3N uint8 bytes."""
    u8 = np.frombuffer(raw, dtype=np.uint8).astype(np.float32).reshape(N, 3)
    log_scale = (u8 / 16.0) - 10.0
    return log_scale.astype(np.float32)


def _decode_opacities(raw: bytes, N: int) -> np.ndarray:
    """Decode N opacity values from N uint8 bytes. Returns raw pre-sigmoid opacity."""
    u8 = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
    val = np.clip(u8 / 255.0, 1e-6, 1.0 - 1e-6)
    return np.log(val / (1.0 - val)).astype(np.float32)


def _decode_colors(raw: bytes, N: int) -> np.ndarray:
    """Decode N x 3 SH DC coefficients from 3N uint8 bytes."""
    u8 = np.frombuffer(raw, dtype=np.uint8).astype(np.float32).reshape(N, 3)
    return ((u8 / 255.0 - 0.5) / _COLOR_SCALE).astype(np.float32)


def _decode_rotations_v2(raw: bytes, N: int) -> np.ndarray:
    """
    Version 2: 3 uint8 bytes per splat -> (x, y, z); w reconstructed.
    Returns (N, 4) quaternions in (w, x, y, z) order.
    """
    u8 = np.frombuffer(raw, dtype=np.uint8).astype(np.float32).reshape(N, 3)
    xyz = (u8 / 127.5) - 1.0
    sum_sq = np.sum(xyz**2, axis=1, keepdims=True)
    w = np.sqrt(np.maximum(0.0, 1.0 - sum_sq))
    wxyz = np.concatenate([w, xyz], axis=1)
    norms = np.linalg.norm(wxyz, axis=1, keepdims=True)
    return (wxyz / np.maximum(norms, 1e-8)).astype(np.float32)


def _decode_rotations_v3(raw: bytes, N: int) -> np.ndarray:
    """
    Version 3: 4 bytes per splat, Niantic "smallest three" quaternion encoding.
    Returns (N, 4) quaternions in (w, x, y, z) order.
    """
    C_MASK = (1 << 9) - 1
    SCALE = 0.7071067811865476  # 1/sqrt(2)

    if len(raw) < N * 4:
        raise ValueError(f"Truncated SPZ v3 rotation data: need {N * 4} bytes for {N:,} splats, got {len(raw)}")

    rotations = np.zeros((N, 4), dtype=np.float32)
    for i in range(N):
        packed = struct.unpack_from("<I", raw, i * 4)[0]

        i_largest = packed >> 30
        comps = [0.0, 0.0, 0.0, 0.0]
        sum_sq = 0.0

        for idx in (3, 2, 1, 0):
            if idx == i_largest:
                continue
            mag = packed & C_MASK
            negbit = (packed >> 9) & 0x1
            packed >>= 10
            v = SCALE * (float(mag) / float(C_MASK))
            if negbit == 1:
                v = -v
            comps[idx] = v
            sum_sq += v * v

        comps[i_largest] = math.sqrt(max(0.0, 1.0 - sum_sq))
        rotations[i, 0] = comps[3]  # w
        rotations[i, 1] = comps[0]  # x
        rotations[i, 2] = comps[1]  # y
        rotations[i, 3] = comps[2]  # z

    norms = np.linalg.norm(rotations, axis=1, keepdims=True)
    return (rotations / np.maximum(norms, 1e-8)).astype(np.float32)


def _decode_sh_rest(raw: bytes, N: int, num_rest_coeffs: int) -> Optional[np.ndarray]:
    """Decode higher-order SH coefficients. Returns (N, num_rest_coeffs) float32."""
    if num_rest_coeffs == 0 or not raw:
        return None
    u8 = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
    decoded = (u8 - 128.0) / 128.0
    return decoded.reshape(N, num_rest_coeffs).astype(np.float32)


def read_spz(filepath: str) -> GaussianSplatData:
    """
    Read a Niantic SPZ Gaussian Splat file (versions 2 and 3).

    Parameters
    ----------
    filepath : path to the .spz file (gzip-compressed)

    Returns
    -------
    GaussianSplatData (same schema as read_ply output)
    """
    filepath = resolve_local_path(filepath)
    print(f"[3DGS] Reading SPZ file: {filepath}")

    with gzip.open(filepath, "rb") as f:
        # Bounded read: never materialize an unbounded decompressed stream.
        # gzip reaches ~1000:1 on zero-filled input, so a tiny .spz could expand
        # to GBs and OOM the process. Reading at most the cap (+1 to detect
        # overflow) turns a decompression-bomb DoS into a handled ValueError.
        data = f.read(_MAX_DECOMPRESSED_BYTES + 1)

    if len(data) > _MAX_DECOMPRESSED_BYTES:
        raise ValueError(
            f"SPZ decompressed stream exceeds the {_MAX_DECOMPRESSED_BYTES:,}-byte "
            "limit (possible decompression bomb)"
        )

    version, N, sh_degree, fractional_bits, flags = _parse_spz_header(data)

    num_rest = _num_rest_coeffs(sh_degree)

    print(
        f"[3DGS] SPZ v{version}: {N:,} splats, SH degree {sh_degree}, "
        f"fractionalBits={fractional_bits}, flags=0x{flags:02X}"
    )

    rot_bytes_per_splat = 3 if version == 2 else 4

    offset = 16
    pos_size = N * 3 * 3
    alpha_size = N
    color_size = N * 3
    scale_size = N * 3
    rot_size = N * rot_bytes_per_splat
    rest_size = N * num_rest

    # Required per-splat fields must be fully present. A truncated file here
    # would otherwise produce a mis-shaped buffer and leak a low-level error
    # (e.g. struct.error / ValueError from reshape) instead of the reader's
    # documented, catchable ValueError contract. Rest SH is optional and may
    # legitimately be absent, so only warn on that tail being short.
    required_needed = offset + pos_size + alpha_size + color_size + scale_size + rot_size
    if len(data) < required_needed:
        raise ValueError(
            f"Truncated SPZ file: need at least {required_needed} bytes for "
            f"{N:,} splats (v{version}), got {len(data)}"
        )

    total_needed = required_needed + rest_size
    if len(data) < total_needed:
        print(
            f"[3DGS] Warning: file smaller than expected "
            f"({len(data)} < {total_needed} bytes). Rest SH may be absent."
        )

    def _chunk(size: int) -> bytes:
        nonlocal offset
        end = min(offset + size, len(data))
        chunk = data[offset:end]
        offset += size
        return chunk

    positions = _decode_positions(_chunk(pos_size), N, fractional_bits)
    opacities = _decode_opacities(_chunk(alpha_size), N)
    f_dc = _decode_colors(_chunk(color_size), N)
    scales = _decode_scales(_chunk(scale_size), N)

    rot_raw = _chunk(rot_size)
    if version == 2:
        rotations = _decode_rotations_v2(rot_raw, N)
    else:
        rotations = _decode_rotations_v3(rot_raw, N)

    rest_raw = _chunk(rest_size) if num_rest > 0 else b""
    f_rest = _decode_sh_rest(rest_raw, N, num_rest)

    print(f"[3DGS] Decoded {N:,} splats | " f"SH degree {sh_degree} ({num_rest} rest coeffs)")

    return GaussianSplatData(
        positions=positions,
        scales=scales,
        rotations=rotations,
        opacities=opacities,
        f_dc=f_dc,
        f_rest=f_rest,
        sh_layout=SH_LAYOUT_VEC3_MAJOR,
    )
