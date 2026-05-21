-- SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0 AND CC-BY-4.0

project "usd-convert-gsplat[cloudfront]"
    target_build_dir = repo_build.target_dir().."/package"
    kind "Utility"
    repo_build.prebuild_link {
        { "usd_convert_gsplat", target_build_dir.."/usd_convert_gsplat" },
    }

project "usd-convert-gsplat[pip]"
    target_build_dir = repo_build.target_dir().."/pip/usd-convert-gsplat"
    kind "Utility"
    repo_build.prebuild_copy {
        { "usd_convert_gsplat", target_build_dir.."/usd_convert_gsplat" },
        { "pyproject.toml", target_build_dir.."/pyproject.toml" },
        { "LICENSE", target_build_dir.."/LICENSE" },
        { "README.md", target_build_dir.."/README.md" },
        { "THIRD_PARTY_NOTICES.md", target_build_dir.."/THIRD_PARTY_NOTICES.md" },
    }
