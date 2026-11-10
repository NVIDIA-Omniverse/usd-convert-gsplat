# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: CC-BY-4.0 AND Apache-2.0
#
"""Regression test for README install path consistency."""

import unittest
from pathlib import Path


class TestReadmeInstallPath(unittest.TestCase):
    def test_install_command_uses_relative_dot_after_cd(self):
        readme = Path(__file__).resolve().parents[1] / "README.md"
        text = readme.read_text()

        sections = text.split("## Building From Source")
        self.assertEqual(len(sections), 2, "Building From Source section not found")

        build_section = sections[1]
        cd_pos = build_section.find("cd source/python")
        self.assertGreater(cd_pos, -1, "cd source/python instruction missing")

        after_cd = build_section[cd_pos:]
        self.assertNotIn(
            'python -m pip install "./source/python[usd]"',
            after_cd,
            "Install command uses invalid path after cd source/python",
        )


if __name__ == "__main__":
    unittest.main()
