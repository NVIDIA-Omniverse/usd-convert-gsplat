---
name: omniverse-gaussian-splat-to-usd
description: >
  Convert 3D Gaussian Splat scene files (.ply or .spz) into Pixar USD
  artifacts for Omniverse and USD-based pipelines. Use when documenting,
  invoking, or troubleshooting gsplat-to-USD conversion workflows.
license: "Apache-2.0 AND CC-BY-4.0"
version: "0.1.0"
author: NVIDIA OpenUSD
compatibility: >
  Requires Python package install from ./source/python. USD writing requires
  ./source/python[usd] and compatible OpenUSD runtime. --generateScales
  requires SciPy. OpenUSD 26.03+ is preferred for
  UsdVol.ParticleField3DGaussianSplat.
tags:
  - omniverse
  - openusd
  - gsplat
  - conversion
tools:
  - Read
  - Shell
---

# Omniverse Gaussian Splat to USD

Use the `usd-convert-gsplat` Python library and CLI to convert 3D Gaussian Splat scene files into Pixar USD artifacts for Omniverse and USD-based pipelines.

<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 AND CC-BY-4.0 -->

## When to Use

Use this skill when a user asks to:

- Convert `.ply` or `.spz` Gaussian Splat content to `.usd`, `.usda`, `.usdc`, or `.usdz`.
- Choose the right `usd-convert-gsplat` CLI flags for orientation, up-axis, RGB-to-SH generation, or scale generation.
- Explain or troubleshoot the converter's Python API, input expectations, output schema, or code locations.
- Map converter behavior to Omniverse/OpenUSD concepts such as `ParticleField3DGaussianSplat`.

Do not use this skill for unrelated USD conversion tasks such as CAD, URDF, mesh, material, or texture conversion unless Gaussian Splat content is the source data.

## Inputs

Accept whichever inputs are available, in this precedence:

1. User-provided source path to a `.ply` or `.spz` file.
2. User-provided output path ending in `.usd`, `.usda`, `.usdc`, or `.usdz`.
3. User-provided conversion options: `--name`, `--up-axis`, `--rotate-x`, `--rotate-y`, `--rotate-z`, `--generateSh`, or `--generateScales`.
4. Repository context, if the user asks for API guidance or code navigation instead of running a conversion.

If required input or output paths are missing and the user expects an actual conversion, ask for the missing path before running commands.

## Instructions

1. Confirm whether the user wants to run a conversion, inspect converter behavior, or get usage guidance.
2. Validate source and destination formats before invoking the tool: input must be `.ply` or `.spz`; output must be `.usd`, `.usda`, `.usdc`, or `.usdz`.
3. Choose CLI flags from the user's intent. Use `--rotate-x/y/z` for orientation correction, `--up-axis Z` for Z-up stages, `--generateSh` when RGB exists but SH DC coefficients are absent, and `--generateScales` when scale channels are absent.
4. Run the conversion with `usd-convert-gsplat -i <input> -o <output>` plus selected flags when the user asks for execution and paths are available.
5. Inspect command output or errors. If conversion fails, identify whether the issue is installation, unsupported input properties, missing optional dependencies, missing USD support, or bad file paths.
6. Return a concise result that includes the command used, output file path, relevant options, and any follow-up validation or troubleshooting notes.

## Output Format

For a completed conversion, return:

```markdown
Converted `<input>` to `<output>` with `usd-convert-gsplat`.

Command:
`usd-convert-gsplat -i <input> -o <output> [options]`

Notes:
- <orientation/up-axis/SH/scale choices, if any>
- <warnings or validation results, if any>
```

For usage guidance or troubleshooting, return a short explanation with the exact CLI command, Python API call, or code location the user needs.

## Prerequisites

- Build repository first if generated packaging files are missing:

```bash
repo.bat build
./repo.sh build
```

- Install Python package:

```bash
pip install ./source/python
```

- Install USD-enabled extra when writing USD through the Python package:

```bash
pip install "./source/python[usd]"
```

- Install SciPy-capable environment before using `--generateScales`.

## Converter Behavior

`usd-convert-gsplat` reads `.ply` or `.spz` Gaussian Splat files and writes `ParticleField3DGaussianSplat` USD prims.

The preferred schema is `UsdVol.ParticleField3DGaussianSplat` from OpenUSD 26.03+. Older builds use the Omniverse `usd_particle_field` fallback.

Preserved data:

- Positions: `(N, 3)` float32 XYZ centers.
- Scales: `(N, 3)` float32, exponentiated from log-scale.
- Orientations: `(N, 4)` quaternion `(w, x, y, z)`, normalized.
- Opacities: `(N,)` float32, sigmoid-applied from raw logit.
- Spherical harmonics: DC coefficients always written; higher-order coefficients written when present.
- Display color: derived from DC SH coefficients for viewport preview.

## Supported Formats

| Input | Notes |
|-------|-------|
| `.ply` | Standard 3DGS format, binary little/big-endian or ASCII. Expected properties include `x y z`, `scale_0/1/2`, `rot_0..3`, `opacity`, `f_dc_0/1/2`, and optional `f_rest_0..N`. Use `--generateSh` for `red/green/blue` fallback. |
| `.spz` | Compressed Gaussian Splat format. Coefficients are stored in vec3-major order, so no transpose is needed. |

| Output | Format |
|--------|--------|
| `.usd` | Generic USD |
| `.usda` | ASCII USD |
| `.usdc` | Binary USD crate |
| `.usdz` | Zip-packaged USD |

## CLI Usage

```bash
# Basic conversion
usd-convert-gsplat -i scene.ply -o scene.usda

# SPZ input
usd-convert-gsplat -i scene.spz -o scene.usdc

# With orientation correction, for example COLMAP Y-down data
usd-convert-gsplat -i scene.ply -o scene.usda --rotate-x 180

# Generate SH from RGB when f_dc is not present
usd-convert-gsplat -i scene.ply -o scene.usda --generateSh

# Generate scales from neighborhood spacing when scale_0/1/2 are not present
usd-convert-gsplat -i scene.ply -o scene.usda --generateScales

# Z-up output stage
usd-convert-gsplat -i scene.ply -o scene.usda --up-axis Z

# Custom prim name
usd-convert-gsplat -i scene.ply -o scene.usda --name MyScene
```

| Flag | Default | Description |
|------|---------|-------------|
| `-i` / `--input` | required | Path to `.ply` or `.spz`. |
| `-o` / `--output` | required | Path to `.usd`, `.usda`, `.usdc`, or `.usdz`. |
| `-n` / `--name` | input stem | USD prim name. |
| `--generateSh` | false | Convert `red/green/blue` to SH DC when `f_dc` is absent. |
| `--generateScales` | false | Estimate scales from KNN neighborhood; requires SciPy. |
| `--up-axis` | `Y` | Stage up-axis: `Y` or `Z`. |
| `--rotate-x/y/z` | `0.0` | Euler rotation in degrees, XYZ order, applied before writing. |

## Python API

```python
from usd_convert_gsplat.ply_reader import read_ply
from usd_convert_gsplat.spz_reader import read_spz
from usd_convert_gsplat.usd_writer import write_gaussian_splat_usd, convertPlyUSD

splat_data = read_ply("scene.ply")
# or:
splat_data = read_spz("scene.spz")

write_gaussian_splat_usd(
    splat_data,
    output_path="scene.usda",
    source_file="scene.ply",
    prim_name="MyScene",
    up_axis="Y",
    rotation_degrees=(180, 0, 0),
    progress_fn=lambda f, msg: print(f"{f:.0%} {msg}"),
)

# PLY-only reference path that preserves raw vertex data.
convertPlyUSD(
    input_file="scene.ply",
    output_file="scene.usda",
    prim_name="MyScene",
    generateSh=False,
    generateScales=False,
    up_axis="Y",
    rotation_degrees=(0, 0, 0),
)
```

`GaussianSplatData` contains:

```python
@dataclass
class GaussianSplatData:
    positions: np.ndarray
    scales: np.ndarray
    rotations: np.ndarray
    opacities: np.ndarray
    f_dc: np.ndarray
    f_rest: Optional[np.ndarray]
    count: int
```

For raw PLY access:

```python
from usd_convert_gsplat.ply_reader import read_ply_raw

data, vertex_count, property_names = read_ply_raw("scene.ply")
```

## Limitations

- `--generateScales` requires SciPy and may be slower on large splat sets because it estimates neighborhood spacing.
- `.spz` inputs already store coefficients in vec3-major order; do not transpose them as if they were PLY channel-major data.
- The OpenUSD `UsdVol.ParticleField3DGaussianSplat` schema requires OpenUSD 26.03+; older builds use Omniverse fallback behavior.
- This skill covers Gaussian Splat conversion only. It does not convert meshes, CAD, URDF, materials, or arbitrary USD assets.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `usd-convert-gsplat` command not found | Package is not installed in active Python environment | Run `pip install ./source/python` and verify with `python -m pip show usd-convert-gsplat`. |
| USD import or writer failure | USD extras or compatible OpenUSD runtime missing | Install with `pip install "./source/python[usd]"` and verify OpenUSD version/plugin availability. |
| Missing SH coefficients | PLY contains RGB but no `f_dc_*` fields | Re-run with `--generateSh`. |
| Missing scale channels | PLY has no `scale_0/1/2` properties | Re-run with `--generateScales` in an environment with SciPy. |
| Scene orientation is wrong | Source data uses different up-axis or camera convention | Use `--up-axis Z` or `--rotate-x/y/z` flags. |

## Codebase Map

| File | Role |
|------|------|
| `source/python/usd_convert_gsplat/ply_reader.py` | PLY parser to `GaussianSplatData`. |
| `source/python/usd_convert_gsplat/spz_reader.py` | SPZ parser to `GaussianSplatData`. |
| `source/python/usd_convert_gsplat/usd_writer.py` | `GaussianSplatData` to USD stage. |
| `source/python/usd_convert_gsplat/cli.py` | `usd-convert-gsplat` entry point. |
| `source/extensions/omni.kit.converter.gsplat/` | Omniverse Kit UI extension that calls the library. |
