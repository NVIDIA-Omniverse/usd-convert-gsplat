# usd-convert-gsplat

`usd-convert-gsplat` is an NVIDIA Python package for converting 3D Gaussian
Splat assets to Pixar USD. It reads `.ply` and `.spz` splat files and writes USD
files that use the `ParticleField3DGaussianSplat` schema.

## Features

- Converts `.ply` and `.spz` Gaussian Splat assets to `.usd`, `.usda`, `.usdc`,
  or `.usdz`.
- Preserves positions, scales, orientations, opacities, and spherical harmonics
  data.
- Uses `UsdVol.ParticleField3DGaussianSplat` when OpenUSD 26.03+ is available;
  otherwise authors the prim type and attributes manually (see Requirements).
- Provides a command-line interface through `usd-convert-gsplat` and
  `python -m usd_convert_gsplat`.
- Exposes Python APIs for reading splat data and writing USD stages.

## Requirements

- Python 3.11 or 3.12.
- `numpy`, installed automatically with the package.
- OpenUSD Python bindings when writing USD outside an Omniverse environment.
  Install the package with the `usd` extra; the dependency is selected by
  platform:

  | Platform | Package | Notes |
  | --- | --- | --- |
  | x86_64 (and most non-aarch64) | `usd-core>=26.3` | Typed `UsdVol.ParticleField3DGaussianSplat` API (OpenUSD 26.03+) |
  | linux-aarch64 | `usd-exchange==2.3.0` | Bundles OpenUSD ~25.x with `pxr` bindings |

  On platforms without the registered `ParticleField3DGaussianSplat` schema
  (including linux-aarch64 with `usd-exchange`), the converter writes a prim
  with type `ParticleField3DGaussianSplat` and the expected attributes via
  custom authoring. Output files remain compatible with Omniverse viewers, but
  USD schema validation against the typed API is not performed at write time.

## Installation

Install the package:

```bash
python -m pip install usd-convert-gsplat
```

Install with USD support:

```bash
python -m pip install "usd-convert-gsplat[usd]"
```

Verify the installation:

```bash
python -m pip show usd-convert-gsplat
usd-convert-gsplat --help
python -m usd_convert_gsplat --help
```

Uninstall the package:

```bash
python -m pip uninstall usd-convert-gsplat
```

## Usage

### Command Line

```bash
# Convert a PLY file to USDZ
usd-convert-gsplat -i input.ply -o output.usdz

# Convert an SPZ file to USDA with Z-up axis
usd-convert-gsplat -i input.spz -o output.usda --up-axis Z

# Generate spherical harmonics from RGB when f_dc data is not present
usd-convert-gsplat -i input.ply -o output.usdz --generateSh

# Generate scales from neighborhood spacing when scale data is not present
usd-convert-gsplat -i input.ply -o output.usdz --generateScales

# Apply orientation correction
usd-convert-gsplat -i input.ply -o output.usda --rotate-x 180
```

You can also run the CLI with `python -m`:

```bash
python -m usd_convert_gsplat -i input.ply -o output.usdz
```

### Python API

```python
from usd_convert_gsplat import read_ply, read_spz, write_gaussian_splat_usd

splat_data = read_ply("scene.ply")
write_gaussian_splat_usd(splat_data, "scene.usdz", source_file="scene.ply")

spz_data = read_spz("scene.spz")
write_gaussian_splat_usd(
    spz_data,
    "scene.usda",
    source_file="scene.spz",
    up_axis="Z",
    rotation_degrees=(90.0, 0.0, 0.0),
)
```

## Supported Formats

| Input | Notes |
| --- | --- |
| `.ply` | Standard 3DGS PLY files with positions, scales, rotations, opacity, and spherical harmonics. RGB input can be converted to SH DC coefficients with `--generateSh`. |
| `.spz` | Compressed Gaussian Splat files with vec3-major spherical harmonics coefficients. |

| Output | Notes |
| --- | --- |
| `.usd` | Generic USD file. |
| `.usda` | ASCII USD file. |
| `.usdc` | Binary USD crate file. |
| `.usdz` | Zip-packaged USD file. |

## Building From Source

The package source lives in `source/python` and builds with standard Python
packaging tools. In the full repository, run `repo.bat build`, `repo.bat subst`,
or the matching `repo.sh` command first so the generated `pyproject.toml` and
`usd_convert_gsplat/_version.py` files are available.

```bash
cd source/python
python -m pip install --upgrade pip build
python -m build
```

The build writes source and wheel distributions to `dist/`:

```text
dist/usd_convert_gsplat-<version>.tar.gz
dist/usd_convert_gsplat-<version>-py3-none-any.whl
```

Install and smoke test the local source tree:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install ".[usd]"
python -m usd_convert_gsplat --help
python -m usd_convert_gsplat -i input.ply -o output.usda
```

Test a built wheel directly:

```bash
python -m pip install "dist/usd_convert_gsplat-<version>-py3-none-any.whl[usd]"
usd-convert-gsplat -i input.ply -o output.usda
```

## Security

NVIDIA asks that potential security vulnerabilities are not reported through
public GitHub issues or pull requests. See `SECURITY.md` for private disclosure
instructions.

## License

This project is licensed under the Apache License, Version 2.0 and the Creative
Commons Attribution 4.0 International Public License. See `LICENSE` for the license text.

Third-party notices and license terms for distributed dependencies are listed in
`THIRD_PARTY_NOTICES.md`. Contributions require Developer Certificate of Origin
sign-off; see the repository `CONTRIBUTING.md` for details.
