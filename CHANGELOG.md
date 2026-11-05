# Changelog

## [0.2.1] - 2026-10-15
### Added
- Kit importer controls for half precision and sorting mode.
- Advanced controls for the maximum splats per prim and an independent USD prim name.
- Early USDZ size validation in the Kit importer, using the selected precision.
- Expose new converter options in GUI
- Add Kit extension documentation

## [0.2.0] - 2026-10-14
### Fixed
- Corrected the conversion skill guidance for `--generateScales`. The option
  estimates missing scales only for PLY input and has no effect on SPZ input,
  which always contains scale data.

## [0.1.26] - 2026-08-26
### Added
- Scenes above 8,000,000 splats are automatically split along their longest
  spatial axes into `ParticleField3DGaussianSplat` prims. A diagnostic warning
  reports the threshold and resulting prim count when the split is applied.
- Partitioned fields share a parent `Xform` while positions, orientations and
  spherical harmonics remain in their original frame.
- `.usdz` conversion estimates bulk-array size from the PLY or SPZ header and
  rejects clearly oversized scenes before loading their splat data.

### Fixed
- USDZ validation now checks the ZIP32 total-archive limit as well as its
  per-member limit.

## [0.1.25] - 2026-08-18
### Added
- `--half-precision` writes the schema's half-typed arrays — `positionsh`,
  `orientationsh`, `scalesh`, `opacitiesh` and
  `radiance:sphericalHarmonicsCoefficientsh` — in place of their float counterparts.
  A 1,000,000-splat scene at spherical harmonic degree 3 goes from **248 MB to
  130 MB**. Off by default; output without the flag is unchanged.

### Notes
- One variant of each pair is written, never both. Consumers resolve a pair by
  preferring the float form, so authoring both would leave the half arrays ignored.
- Positions carry the precision cost, and it scales with distance from the origin
  rather than being uniform. On a scene reaching 95 units the largest error is 0.001
  units; on one reaching 34,000 the bulk is still within 0.007 units but the most
  distant outliers move by up to 16. Scenes spanning tens of thousands of units
  should be checked before the flag is used on them.
- `extent` and `radiance:sphericalHarmonicsDegree` stay as they were. The schema
  pairs only the per-splat arrays.

## [0.1.24] - 2026-08-17
### Fixed
- Removed two links from the `docs/` orientation page that pointed into
  `source/extensions`, which is not part of the published repository, so they would
  have been dead for anyone reading on GitHub. Release history is named rather than
  linked, since the changelog is published at the repository root but is generated
  there, so no link is correct both in a source checkout and in the published tree.
- Dropped a sentence from the same page describing how the documentation came to be
  reorganised. It described repository process rather than anything a reader needs.

## [0.1.23] - 2026-08-11
### Fixed
- `--rotate-x/y/z` now rotates view-dependent appearance along with the geometry.
  The rotation was applied to `positions` and `orientations` but not to the
  spherical harmonic coefficients, so shading stayed attached to the unrotated axes.
  Degree 0 content was unaffected, the DC term being direction-independent.

### Changed
- Every prim carries `xformOp:translate`, `xformOp:rotateXYZ` and `xformOp:scale`,
  in that order. Translation is zero and scale unit unless asked otherwise, and
  `--rotate-x/y/z` sets the angles.
- `positions`, `orientations` and `extent` are authored in the source frame. Resolved
  world space is unchanged; code reading the arrays directly, without the prim's
  transform, sees unrotated data.
- Output without `--rotate-*` gains those three ops, so it is not byte-identical to
  0.1.22. The splat data is untouched.

## [0.1.22] - 2026-08-10
### Changed
- `.usdz` packages are now built with `UsdUtils.CreateNewUsdzPackage`, storing the
  splat data in a binary crate layer beside a small readable `default.usda`. A
  1,000,000-splat scene drops from **842 MB to 248 MB**, with the resolved stage
  unchanged.
- The provenance comment records the source file name rather than the absolute path
  it was converted from, which exported the converting machine's directory layout.

### Fixed
- Packaged members are now 64-byte aligned, as the USDZ specification requires.
  The previous hand-rolled archive placed member data at offset 42, which forces
  a reader to copy the payload instead of memory-mapping it in place.

### Notes
- `.usd`, `.usda` and `.usdc` output is untouched; this affects `.usdz` only.
- On Windows, a crate payload stays memory-mapped while a stage on it is open, so
  release the stage before moving or replacing a package.
- The 4 GiB member guard from 0.1.20 still applies, with unchanged behaviour.

## [0.1.21] - 2026-08-10
### Changed
- Conversion is roughly **50x faster**, with numerical precision preserved. USD
  arrays are authored from numpy directly instead of being built one element at a
  time in Python.

### Fixed
- Opacity no longer raises `OverflowError` on strongly negative input. The scalar
  form computed `1 / (1 + exp(-v))`, which overflows past about -709; the
  vectorized form saturates to zero, which is the correct limit.
- Writing no longer modifies the arrays it is given. Quaternion normalisation ran in
  place, so a `float32` rotations array — which is what both readers produce — was
  rewritten by the conversion. Converting the same `GaussianSplatData` twice therefore
  produced slightly different `orientations` each time.

### Notes
- Output is unchanged apart from `orientations`, which can differ by up to 2 ulp
  where numpy and `Gf.Quatf.Normalize` round the division differently.

## [0.1.20] - 2026-08-10
### Fixed
- Refuse to write a `.usdz` that OpenUSD cannot read. A ZIP member above 4 GiB
  requires ZIP64 extension headers, which OpenUSD's reader rejects, so a
  sufficiently large scene previously produced an archive that failed to open with
  no error at write time. Conversion now stops with an error naming the splat count
  and the ways forward.

### Notes
- `.usd`, `.usda` and `.usdc` output is unaffected — the limit applies only to
  members of a `.usdz` archive, so writing one of those formats instead is the
  simplest remedy.
- When this fires, the partial `.usdz` is removed but the uncompressed layer is
  kept and named in the error, so a large conversion does not have to be repeated.

## [0.1.19] - 2026-08-10
### Fixed
- Installation instructions now use `python -m pip` and quote the extra, as
  `pip install usd-convert-gsplat[usd]` fails in zsh where the brackets are glob
  characters.
- All command-line options are now documented; `-n`/`--name`, `--rotate-y` and
  `--rotate-z` were missing.

### Changed
- Installation and usage are documented in one place, the readme published with the
  package; the repository's `docs/` page links to it instead of repeating it.
- That readme now also covers why Python 3.10 is unsupported, why `usd-core` is not
  used on linux-aarch64, the renderer hints written on every prim, and the
  scale-estimation option on the PLY reader.

## [0.1.18] - 2026-08-04
### Added
- Author the `ParticleField` renderer hints `projectionModeHint` and
  `sortingModeHint` on every converted prim, as uniform tokens matching the
  schema. Consumers previously fell back to the schema defaults.
- `--sorting-mode-hint` selects between `zDepth` (default) and
  `cameraDistance`. The schema also declares `rayHitDistance`, and `tangential`
  for projection; neither has been verified against Omniverse here, so neither is
  offered. Widening the set is a one-line change once a token is confirmed.

### Notes
- Both authored values match the schema's own defaults, so rendered output is
  unchanged for existing consumers. The gain is that the intended sort is now
  recorded in the asset rather than depending on the schema fallback of whatever
  OpenUSD version reads it.

## [0.1.17] - 2026-08-03
### Added
- `SH_LAYOUT_CHANNEL_MAJOR` and `SH_LAYOUT_VEC3_MAJOR` are exported from
  `usd_convert_gsplat`, alongside the new `GaussianSplatData.sh_layout` field that
  records which ordering a reader produced.

### Changed
- Unified the two PLY conversion implementations into a single authoring path.
  `convertPlyUSD` now delegates to `write_gaussian_splat_usd`. Its signature is
  unchanged; for the behavioural differences see the prim name and `displayColor`
  entries below.
- The USD prim name is now always derived from the output filename stem. Through
  the CLI it previously came from the input stem whenever `--generateSh` or
  `--generateScales` was passed, so the prim path depended on unrelated flags.
  Callers of `convertPlyUSD` see the change unconditionally, since that function
  always used the input stem regardless of flags.

### Deprecated
- `--generateSh` (and the `generateSh` parameter of `convertPlyUSD`) is ignored
  and slated for removal. DC spherical harmonics are always derived from
  `red`/`green`/`blue` when `f_dc_*` is absent, so the flag is redundant. Passing
  it prints a notice; it is still accepted so existing callers keep working.

### Fixed
- `--generateScales` is honoured on the single conversion path, so it no longer
  depends on which entry point or flag combination routed the conversion. Scale
  estimation moved into the reader as part of the unification above. It remains a
  no-op for `.spz`, whose format carries a mandatory scales block.
- `displayColor` is now authored for RGB-only point clouds. On the `convertPlyUSD`
  path it was omitted for exactly that input; inputs carrying `f_dc_*` already
  received it.
- Spherical harmonic coefficient ordering is taken from the parsed data instead
  of being inferred from the source filename extension. Passing a `source_file`
  that did not match the real format, or omitting it, could silently produce
  wrongly ordered coefficients.

## [0.1.16] - 2026-07-07
### Fixed
- Reject PLY files with non-positive vertex counts
- Reject truncated SPZ files with a `ValueError`
- Bound SPZ gzip decompression to prevent a decompression-bomb OOM DoS

## [0.1.15] - 2026-06-10
### Changed
- Update `usd-convert-gsplat` Python module

## [0.1.14] - 2026-05-21
### Changed
- Update agent skill metadata and structure for Skills as Docs compliance

## [0.1.13] - 2026-05-21
### Changed
- Release Prep

## [0.1.12] - 2026-05-20
### Changed
- Update documentation

## [0.1.11] - 2026-05-20
### Changed
- Update documentation

## [0.1.10] - 2026-05-19
### Changed
- Update license headers

## [0.1.9] - 2026-05-13
### Changed
- update documentation
- Add Skills.md files

## [0.1.8] - 2026-05-12
### Changed
- update premake

## [0.1.7] - 2026-05-11
### Changed
- Update `usd-core` to 26.3
- Update `Third_Party_Noticed.md`, `Contributing.md`, and update `README.md`

## [0.1.6] - 2026-05-07
### Changed
- Improved documentation
- Added license headers
- Renamed pip package from gsplat2USD to usd-convert-gsplat

## [0.1.5] - 2026-04-27
### Changed
- Renamed pip package library name from omniverse-gsplat-converter to gsplat2USD

## [0.1.4] - 2026-04-24
### Changed
- Prevent pip from downloading dependencies for `omniverse_gsplat_converter` (use Kit-provided modules only)

## [0.1.3] - 2026-04-21
### Changed
- Use numpy module from the `omni.kit.pip_archive` dependency

### Fixed
- Handle input files with spaces

## [0.1.2] - 2026-04-15
### Changed
- Refactored GUI to utilize Asset Importer delegate

## [0.1.1] - 2026-04-09
### Changed
- Decoupled conversion logic to standalone Python module.
- Setup Python Wheel package

## [0.1.0] - 2026-03-23
### Added
- Initial development version
