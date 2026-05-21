# Contributing

Thank you for your interest in contributing to `usd-convert-gsplat`.

This project accepts contributions through GitHub pull requests. Before opening
a pull request, please make sure your change is focused, documented where
appropriate, and tested for the behavior it affects.

## Reporting Issues

Use GitHub issues for bug reports, feature requests, and documentation problems.
Include enough detail for maintainers to reproduce or understand the issue:

- Package version or commit.
- Operating system and Python version.
- Input format (`.ply` or `.spz`) and output format.
- Exact command or API call used.
- Error output, logs, or a short description of the unexpected behavior.

Do not report security vulnerabilities through public GitHub issues. See
`SECURITY.md` for private disclosure instructions.

## Pull Requests

Pull requests should be scoped to a single logical change. Include a clear
description of the problem being solved and the approach taken.

Before submitting a pull request:

- Build the package from `source/python` when your change affects packaging.
- Run relevant tests or smoke tests.
- Update `README.md` or other docs when behavior, options, or supported formats
  change.
- Keep public APIs backwards compatible unless the pull request intentionally
  proposes a breaking change.

## Development Setup

From the full repository, generate the Python package metadata first:

```bash
# Windows
repo.bat build

# Linux or macOS
./repo.sh build
```

Then install the package locally:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install "./source/python[usd]"
```

## Building

The package uses standard Python packaging tools through Hatchling:

```bash
cd source/python
python -m pip install --upgrade build
python -m build
```

The build writes source and wheel distributions to `source/python/dist/`.

## Testing

Run the tests that apply to your change. At minimum, smoke test the CLI when
changing conversion, packaging, or entry point behavior:

```bash
python -m usd_convert_gsplat --help
usd-convert-gsplat -i input.ply -o output.usda
```

When adding or changing conversion behavior, prefer tests with small sample
assets that are suitable for source control.

## Signing Your Work

We require that all contributors sign off on their commits using the Developer
Certificate of Origin (DCO). This certifies that the contribution is your
original work, or that you have the right to submit it under this project's
license or a compatible license.

Contributions containing commits that are not signed off may not be accepted.
To sign off on a commit, use the `--signoff` or `-s` option:

```bash
git commit -s -m "Add conversion option"
```

This appends a line like this to your commit message:

```text
Signed-off-by: Your Name <your.email@example.com>
```

Full text of the DCO:

```text
Developer Certificate of Origin
Version 1.1

Copyright (C) 2004, 2006 The Linux Foundation and its contributors.

Everyone is permitted to copy and distribute verbatim copies of this license
document, but changing it is not allowed.

Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I have the right
to submit it under the open source license indicated in the file; or

(b) The contribution is based upon previous work that, to the best of my
knowledge, is covered under an appropriate open source license and I have the
right under that license to submit that work with modifications, whether created
in whole or in part by me, under the same open source license (unless I am
permitted to submit under a different license), as indicated in the file; or

(c) The contribution was provided directly to me by some other person who
certified (a), (b) or (c) and I have not modified it.

(d) I understand and agree that this project and the contribution are public and
that a record of the contribution (including all personal information I submit
with it, including my sign-off) is maintained indefinitely and may be
redistributed consistent with this project or the open source license(s)
involved.
```

## Coding Guidelines

- Follow the existing code style in the files you edit.
- Keep changes narrowly scoped and avoid unrelated formatting churn.
- Add comments only where they clarify non-obvious conversion or USD schema
  behavior.

## License

By contributing, you agree that your contributions will be licensed under the
Apache License, Version 2.0 and the Creative Commons Attribution 4.0
International Public License. See `LICENSE` for details.
