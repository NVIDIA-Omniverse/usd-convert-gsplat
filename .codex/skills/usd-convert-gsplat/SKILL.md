# usd-convert-gsplat

A Python library and CLI that converts 3D Gaussian Splat scene files into Pixar USD format for use in Omniverse and other USD-based pipelines.

---

<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 AND CC-BY-4.0 -->

## What this converter does

Reads `.ply` or `.spz` Gaussian Splat files and writes them as `ParticleField3DGaussianSplat` USD prims (`.usd`, `.usda`, `.usdc`, or `.usdz`). The USD schema used is `UsdVol.ParticleField3DGaussianSplat` (OpenUSD 26.03+) with an automatic fallback to the Omniverse `usd_particle_field` plugin on older builds.

Each splat's data is faithfully preserved:
- **Positions** — (N, 3) float32, XYZ centers
- **Scales** — (N, 3) float32, exponentiated from log-scale
- **Orientations** — (N, 4) quaternion (w, x, y, z), normalized
- **Opacities** — (N,) float32, sigmoid-applied from raw logit
- **Spherical harmonics** — DC coefficients (`f_dc`) always written; higher-order `f_rest` coefficients written when present (SH degree 0–3). PLY channel-major order is automatically transposed to USD vec3-major order.
- **Display color** — derived from DC SH coefficients for viewport preview

---

## Input formats

| Format | Notes |
|--------|-------|
| `.ply` | Standard 3DGS format (binary little/big-endian or ASCII). Properties: `x y z`, `scale_0/1/2`, `rot_0..3`, `opacity`, `f_dc_0/1/2`, `f_rest_0..N`. Fallback: `red/green/blue` → SH DC with `--generateSh`. |
| `.spz` | Compressed Gaussian Splat format. Coefficients stored in vec3-major order (no transpose needed). |

## Output formats

| Extension | Format |
|-----------|--------|
| `.usd`    | Generic USD |
| `.usda`   | ASCII USD |
| `.usdc`   | Binary USD (crate) |
| `.usdz`   | Zip-packaged USD |

---

## CLI usage

```bash
# Basic conversion
usd-convert-gsplat -i scene.ply -o scene.usda

# SPZ input
usd-convert-gsplat -i scene.spz -o scene.usdc

# With orientation correction (e.g. COLMAP Y-down data)
usd-convert-gsplat -i scene.ply -o scene.usda --rotate-x 180

# Generate SH from RGB when f_dc not present
usd-convert-gsplat -i scene.ply -o scene.usda --generateSh

# Generate scales from neighborhood spacing when scale_0/1/2 not present (requires scipy)
usd-convert-gsplat -i scene.ply -o scene.usda --generateScales

# Z-up output stage
usd-convert-gsplat -i scene.ply -o scene.usda --up-axis Z

# Custom prim name
usd-convert-gsplat -i scene.ply -o scene.usda --name MyScene
```

All CLI flags:

| Flag | Default | Description |
|------|---------|-------------|
| `-i` / `--input` | required | Path to `.ply` or `.spz` |
| `-o` / `--output` | required | Path to `.usd`, `.usda`, `.usdc`, or `.usdz` |
| `-n` / `--name` | input stem | USD prim name |
| `--generateSh` | false | Convert `red/green/blue` → SH DC when `f_dc` absent |
| `--generateScales` | false | Estimate scales from KNN neighborhood (scipy) |
| `--up-axis` | `Y` | Stage up-axis: `Y` or `Z` |
| `--rotate-x/y/z` | `0.0` | Euler rotation (degrees, XYZ order) applied before writing |

---

## Python API

```python
from usd_convert_gsplat.ply_reader import read_ply
from usd_convert_gsplat.spz_reader import read_spz
from usd_convert_gsplat.usd_writer import write_gaussian_splat_usd, convertPlyUSD

# --- Two-step (recommended) ---
splat_data = read_ply("scene.ply")         # returns GaussianSplatData
# or:
splat_data = read_spz("scene.spz")

write_gaussian_splat_usd(
    splat_data,
    output_path="scene.usda",
    source_file="scene.ply",       # optional, stored in layer comment
    prim_name="MyScene",           # optional, defaults to output stem
    up_axis="Y",                   # "Y" or "Z"
    rotation_degrees=(180, 0, 0),  # Euler XYZ in degrees
    progress_fn=lambda f, msg: print(f"{f:.0%} {msg}"),  # optional
)

# --- One-step PLY only (Pixar reference path, preserves raw vertex data) ---
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

### `GaussianSplatData` dataclass

```python
@dataclass
class GaussianSplatData:
    positions:  np.ndarray        # (N, 3) float32
    scales:     np.ndarray        # (N, 3) float32  — log-scale
    rotations:  np.ndarray        # (N, 4) float32  — (w, x, y, z)
    opacities:  np.ndarray        # (N,)   float32  — pre-sigmoid logit
    f_dc:       np.ndarray        # (N, 3) float32  — DC SH coefficients
    f_rest:     Optional[np.ndarray]  # (N, K) float32 or None
    count:      int               # N
```

Raw PLY access (no interpretation):

```python
from usd_convert_gsplat.ply_reader import read_ply_raw

data, vertex_count, property_names = read_ply_raw("scene.ply")
# data: dict[str, np.ndarray]  — one array per PLY property
```

---

## Installation

```bash
# Build first (generates pyproject.toml and _version.py)
repo.bat build     # Windows
./repo.sh build    # Linux/Mac

# Install (standard)
pip install ./source/python

# Install with USD support
pip install "./source/python[usd]"

# Verify
python -m pip show usd-convert-gsplat
usd-convert-gsplat -i input.ply -o output.usda
```

---

## Codebase map

| File | Role |
|------|------|
| `source/python/usd_convert_gsplat/ply_reader.py` | PLY parser → `GaussianSplatData` |
| `source/python/usd_convert_gsplat/spz_reader.py` | SPZ parser → `GaussianSplatData` |
| `source/python/usd_convert_gsplat/usd_writer.py` | `GaussianSplatData` → USD stage |
| `source/python/usd_convert_gsplat/cli.py` | `usd-convert-gsplat` entry point |
| `source/extensions/omni.kit.converter.gsplat/` | Omniverse Kit UI extension (calls the library) |
