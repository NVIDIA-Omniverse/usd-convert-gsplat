# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: CC-BY-4.0 AND Apache-2.0
#
"""
Command-line interface for PLY and SPZ to USD conversion.

Usage:
    python -m usd_convert_gsplat -i input.ply -o output.usda
    python -m usd_convert_gsplat.cli -i input.spz -o output.usda
"""

import argparse
import os
import sys

from .local_paths import resolve_local_path
from .usd_writer import (
    DEFAULT_MAX_SPLATS_PER_PRIM,
    DEFAULT_SORTING_MODE_HINT,
    SORTING_MODE_HINTS,
    validate_usdz_payload_estimate,
)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Convert PLY or SPZ Gaussian Splat files to USD format")
    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Input PLY or SPZ file path",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output USD file path (.usd, .usda, .usdc, or .usdz)",
    )
    parser.add_argument(
        "-n",
        "--name",
        default=None,
        help=(
            "Name of the Gaussian Splat USD prim, sanitized to a valid USD "
            "identifier (default: output filename without extension)"
        ),
    )
    parser.add_argument(
        "--generateSh",
        action="store_true",
        help=(
            "Deprecated and ignored. DC spherical harmonics are always derived from "
            "red/green/blue when f_dc is absent."
        ),
    )
    parser.add_argument(
        "--generateScales",
        action="store_true",
        help=(
            "Generate scales from local neighborhood spacing when the input has no "
            "scale data (requires scipy). SPZ always carries scales, so this has no "
            "effect for .spz input."
        ),
    )
    parser.add_argument(
        "--up-axis",
        choices=["Y", "Z"],
        default="Y",
        help="Target up-axis for the output USD stage (default: Y)",
    )
    parser.add_argument(
        "--rotate-x",
        type=float,
        default=0.0,
        help="Rotation around X axis in degrees (default: 0)",
    )
    parser.add_argument(
        "--rotate-y",
        type=float,
        default=0.0,
        help="Rotation around Y axis in degrees (default: 0)",
    )
    parser.add_argument(
        "--rotate-z",
        type=float,
        default=0.0,
        help="Rotation around Z axis in degrees (default: 0)",
    )
    parser.add_argument(
        "--sorting-mode-hint",
        choices=SORTING_MODE_HINTS,
        default=DEFAULT_SORTING_MODE_HINT,
        help=("Renderer sorting hint written to the prim " f"(default: {DEFAULT_SORTING_MODE_HINT})"),
    )
    parser.add_argument(
        "--half-precision",
        action="store_true",
        help=(
            "Write the half-precision variants of the bulk arrays instead of the "
            "float ones, roughly halving output size. Positions lose about 0.05%% "
            "relative precision, which is imperceptible for a scene of ordinary "
            "extent but coarse for one spanning tens of thousands of units."
        ),
    )
    parser.add_argument(
        "--max-splats-per-prim",
        type=int,
        default=DEFAULT_MAX_SPLATS_PER_PRIM,
        help=(
            "Advanced override for the automatic per-prim renderer threshold "
            f"(default: {DEFAULT_MAX_SPLATS_PER_PRIM}; 0 disables partitioning)."
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    input_path = resolve_local_path(args.input)
    output_path = resolve_local_path(args.output)

    if not os.path.isfile(input_path):
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    up_axis = args.up_axis.upper()
    rotation = (args.rotate_x, args.rotate_y, args.rotate_z)

    if args.generateSh:
        print(
            "[3DGS] Note: --generateSh is deprecated and has no effect. DC spherical "
            "harmonics are always derived from red/green/blue when f_dc is absent."
        )

    ext = os.path.splitext(input_path)[1].lower()
    if ext not in (".ply", ".spz"):
        print(f"Error: unsupported file type '{ext}'. Expected .ply or .spz", file=sys.stderr)
        sys.exit(1)

    if os.path.splitext(output_path)[1].lower() == ".usdz":
        if ext == ".ply":
            from .ply_reader import read_ply_metadata

            metadata = read_ply_metadata(input_path)
        else:
            from .spz_reader import read_spz_metadata

            metadata = read_spz_metadata(input_path)
        try:
            validate_usdz_payload_estimate(
                metadata.count,
                metadata.sh_coefficient_count,
                args.half_precision,
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    # One route for every format: read into GaussianSplatData, then write once.
    # Synthesis of missing data belongs to each reader. Only PLY can omit scales,
    # so generateScales applies to PLY input only.
    if ext == ".ply":
        from .ply_reader import read_ply

        splat_data = read_ply(input_path, generate_scales=args.generateScales)
    elif ext == ".spz":
        from .spz_reader import read_spz

        splat_data = read_spz(input_path)

    from .usd_writer import write_gaussian_splat_usd

    actual_path = write_gaussian_splat_usd(
        splat_data,
        output_path,
        source_file=input_path,
        prim_name=args.name,
        up_axis=up_axis,
        rotation_degrees=rotation,
        sorting_mode_hint=args.sorting_mode_hint,
        half_precision=args.half_precision,
        max_splats_per_prim=args.max_splats_per_prim,
    )
    print(f"Successfully saved: {actual_path}")


if __name__ == "__main__":
    main()
