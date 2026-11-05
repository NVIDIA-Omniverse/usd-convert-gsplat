# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: CC-BY-4.0 AND Apache-2.0
#
from .local_paths import resolve_local_path
from .ply_reader import (
    SH_LAYOUT_CHANNEL_MAJOR,
    SH_LAYOUT_VEC3_MAJOR,
    GaussianSplatData,
    read_ply,
    read_ply_raw,
)
from .ply_writer import write_ply
from .spz_reader import read_spz
from .usd_writer import (
    DEFAULT_MAX_SPLATS_PER_PRIM,
    UP_AXIS_Y,
    UP_AXIS_Z,
    convertPlyUSD,
    write_gaussian_splat_usd,
)

try:
    from ._version import __version__, get_version
except ImportError:
    __version__ = "0.0.0"

    def get_version():
        return __version__


__all__ = [
    "__version__",
    "get_version",
    "GaussianSplatData",
    "read_ply",
    "read_ply_raw",
    "read_spz",
    "write_gaussian_splat_usd",
    "convertPlyUSD",
    "write_ply",
    "UP_AXIS_Y",
    "UP_AXIS_Z",
    "DEFAULT_MAX_SPLATS_PER_PRIM",
    "SH_LAYOUT_CHANNEL_MAJOR",
    "SH_LAYOUT_VEC3_MAJOR",
    "resolve_local_path",
]
