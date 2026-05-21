# 3D Gaussian Splat Converter

## Developer Guide

### Project Structure

The converter code lives in two places:

- **`source/python/usd_convert_gsplat/`** — The pip-installable library (import name
  `usd_convert_gsplat`).
- **`source/extensions/omni.kit.converter.gsplat/`** — The Kit extension (import name
  `omni.kit.converter.gsplat`): UI and extension lifecycle only; it calls the standalone
  package’s public API.

The extension build **links** `source/python/usd_convert_gsplat` next to the
extension (see `premake5.lua`) so Kit can `import usd_convert_gsplat` without
copying individual converter modules into `omni.kit.converter.gsplat`.

### Installing from Source

After building the repo, the generated `pyproject.toml` (with the version resolved from
`VERSION.md`) is located at `source/python/pyproject.toml`. You can install the package
directly from the source tree.

**Standard install** (copies into site-packages):

```bash
python -m pip install ./source/python
```

**With USD support:**

```bash
python -m pip install "./source/python[usd]"
```

> **Note:** You must run `repo.bat build` (or `repo.bat subst`) at least once before
> installing, because the build generates `source/python/pyproject.toml` and
> `source/python/usd_convert_gsplat/_version.py` from their templates.

### Uninstalling

```bash
python -m pip uninstall usd-convert-gsplat
```

Add `-y` to skip the confirmation prompt:

```bash
python -m pip uninstall -y usd-convert-gsplat
```

### Verifying the Installation

```bash
# Check the package is installed and see its version
python -m pip show usd-convert-gsplat

# Run the CLI
usd-convert-gsplat -i input.ply -o output.usdz

# Or via python -m
python -m usd_convert_gsplat -i input.ply -o output.usdz
```

### Open Source Release Compliance

The `source/python` package is licensed under the Apache License, Version 2.0
and the Creative Commons Attribution 4.0 International Public License. See
`source/python/LICENSE` for the full license text.

Third-party notices and license terms for distributed dependencies are listed in
`source/python/THIRD_PARTY_NOTICES.md`. External contributions require Developer
Certificate of Origin sign-off; see `CONTRIBUTING.md`.
