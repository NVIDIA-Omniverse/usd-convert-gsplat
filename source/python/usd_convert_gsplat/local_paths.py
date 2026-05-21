# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: CC-BY-4.0 AND Apache-2.0
#
"""Normalize local filesystem paths from Kit URIs and percent-encoding."""

from __future__ import annotations

import os
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

__all__ = ["resolve_local_path"]


def resolve_local_path(path: str) -> str:
    """
    Convert paths from Omniverse Kit / asset importers into a string suitable
    for ``open()`` and USD local file APIs.

    Handles ``file:`` URLs (including ``%20`` for spaces) and percent-encoded
    paths when the literal string is not a valid on-disk path.

    Non-``file`` schemes (e.g. ``omniverse://``) are returned unchanged.
    """
    if not path:
        return path

    stripped = path.split("?", 1)[0].split("#", 1)[0]

    if stripped.lower().startswith("file:"):
        parsed = urlparse(stripped)
        raw = unquote(parsed.path or "")
        if os.name == "nt":
            return os.path.normpath(url2pathname(raw))
        return os.path.normpath(raw)

    if os.path.isfile(stripped):
        return os.path.normpath(stripped)

    if "%" in stripped:
        decoded = unquote(stripped.replace("\\", "/"))
        return os.path.normpath(decoded)

    return stripped
