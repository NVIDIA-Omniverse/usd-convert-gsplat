# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: CC-BY-4.0 AND Apache-2.0
#
"""Spatial partitioning for Gaussian Splat data."""

import numpy as np

from .ply_reader import GaussianSplatData

__all__ = ["partition_indices", "select_splats"]


def partition_indices(positions: np.ndarray, max_splats_per_prim: int) -> list[np.ndarray]:
    """Split indices at the median of each partition's longest spatial axis."""
    assert positions.ndim == 2 and positions.shape[1] == 3, "positions must have shape (N, 3)"
    assert positions.shape[0] > 0, "positions must not be empty"
    assert np.isfinite(positions).all(), "positions must be finite for spatial partitioning"
    if max_splats_per_prim < 1:
        raise ValueError(f"max_splats_per_prim must be at least 1, got {max_splats_per_prim}")

    pending = [np.arange(positions.shape[0])]
    partitions = []

    while pending:
        indices = pending.pop()
        if indices.size <= max_splats_per_prim:
            partitions.append(indices)
            continue

        partition_positions = positions[indices]
        axis = int(np.argmax(np.ptp(partition_positions, axis=0)))
        order = np.argsort(partition_positions[:, axis], kind="stable")
        midpoint = indices.size // 2

        # Push the upper half first so the lower half is visited first.
        pending.append(indices[order[midpoint:]])
        pending.append(indices[order[:midpoint]])

    return partitions


def select_splats(splat_data: GaussianSplatData, indices: np.ndarray) -> GaussianSplatData:
    """Select every per-splat array with one shared index array."""
    assert indices.ndim == 1, "partition indices must be one-dimensional"
    return GaussianSplatData(
        positions=splat_data.positions[indices],
        scales=splat_data.scales[indices],
        rotations=splat_data.rotations[indices],
        opacities=splat_data.opacities[indices],
        f_dc=splat_data.f_dc[indices],
        f_rest=None if splat_data.f_rest is None else splat_data.f_rest[indices],
        sh_layout=splat_data.sh_layout,
    )
