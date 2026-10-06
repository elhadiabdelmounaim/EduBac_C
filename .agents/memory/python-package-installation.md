---
name: Python package installation
description: Replit package installation reads the workspace root Python project manifest.
---

Resolve invalid TOML and merge-conflict markers in the workspace-root `pyproject.toml` before using Replit's Python package installer, even when the application also has its own `requirements.txt`.

**Why:** the package installer failed to parse the root project manifest while `project.dependencies` contained unresolved merge markers.

**How to apply:** validate the root `pyproject.toml` before retrying an install, and keep the root dependency list consistent with the application requirements.
