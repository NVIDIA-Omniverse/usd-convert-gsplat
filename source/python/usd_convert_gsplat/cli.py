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
        help=("Name of the Gaussian Splat USD prim " "(default: input filename without extension)"),
    )
    parser.add_argument(
        "--generateSh",
        action="store_true",
        help="Generate DC spherical harmonics from RGB data if f_dc not in PLY",
    )
    parser.add_argument(
        "--generateScales",
        action="store_true",
        help="Generate scales from local neighborhood spacing if scales not in PLY (requires scipy)",
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

    ext = os.path.splitext(input_path)[1].lower()
    if ext == ".ply":
        if args.generateSh or args.generateScales:
            from .usd_writer import convertPlyUSD

            convertPlyUSD(
                input_path,
                output_path,
                args.name,
                args.generateSh,
                args.generateScales,
                up_axis=up_axis,
                rotation_degrees=rotation,
            )
        else:
            from .ply_reader import read_ply
            from .usd_writer import write_gaussian_splat_usd

            print(f"Reading PLY file: {input_path}")
            splat_data = read_ply(input_path)
            actual_path = write_gaussian_splat_usd(
                splat_data,
                output_path,
                source_file=input_path,
                prim_name=args.name,
                up_axis=up_axis,
                rotation_degrees=rotation,
            )
            print(f"Successfully saved: {actual_path}")
    elif ext == ".spz":
        from .spz_reader import read_spz
        from .usd_writer import write_gaussian_splat_usd

        print(f"Reading SPZ file: {input_path}")
        splat_data = read_spz(input_path)
        actual_path = write_gaussian_splat_usd(
            splat_data,
            output_path,
            source_file=input_path,
            prim_name=args.name,
            up_axis=up_axis,
            rotation_degrees=rotation,
        )
        print(f"Successfully saved: {actual_path}")
    else:
        print(f"Error: unsupported file type '{ext}'. Expected .ply or .spz", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
