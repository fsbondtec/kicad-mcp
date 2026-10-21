"""
File handling utilities for KiCad MCP Server.
"""

import hashlib
import json
import os
from typing import Any

from kicad_mcp.utils.kicad_utils import get_project_name_from_path
from kiutils.schematic import Schematic


def hash_file(path: str) -> str:
    """Return the SHA-256 hex digest of a file's contents (used to invalidate caches)."""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def resolve_project_file(project_path: str) -> str:
    """Resolve a project reference to its .kicad_pro file.

    Accepts the .kicad_pro file itself, the project directory, or a path whose
    sibling <path>.kicad_pro exists.

    Args:
        project_path: A .kicad_pro file, a project directory, or a path stem.

    Returns:
        Path to the .kicad_pro file, or the original input if none was found.
    """
    if project_path.endswith(".kicad_pro") and os.path.isfile(project_path):
        return project_path

    if os.path.isdir(project_path):
        matches = [f for f in os.listdir(project_path) if f.endswith(".kicad_pro")]
        if matches:
            return os.path.join(project_path, matches[0])

    candidate = f"{project_path}.kicad_pro"
    if os.path.isfile(candidate):
        return candidate

    return project_path


def get_project_files(project_path: str) -> dict[str, str]:
    """Get all files related to a KiCad project.

    Args:
        project_path: Path to the .kicad_pro file (a project directory or path
            stem is also accepted and resolved to the .kicad_pro).

    Returns:
        Dictionary mapping file types to file paths
    """
    from kicad_mcp.config import DATA_EXTENSIONS, KICAD_EXTENSIONS

    project_path = resolve_project_file(project_path)
    project_dir = os.path.dirname(project_path)
    project_name = get_project_name_from_path(project_path)

    files = {}

    # Check for standard KiCad files
    for file_type, extension in KICAD_EXTENSIONS.items():
        if file_type == "project":
            # We already have the project file
            files[file_type] = project_path
            continue

        if file_type == "schematic":
            # When project has subsheets
            matching = [
                os.path.join(project_dir, f)
                for f in os.listdir(project_dir)
                if f.endswith(extension)
            ]
            if matching:
                files[file_type] = matching

        else:
            file_path = os.path.join(project_dir, f"{project_name}{extension}")
            if os.path.exists(file_path):
                files[file_type] = file_path

    # Check for data files
    try:
        for ext in DATA_EXTENSIONS:
            for file in os.listdir(project_dir):
                if file.startswith(project_name) and file.endswith(ext):
                    # Extract the type from filename (e.g., project_name-bom.csv -> bom)
                    file_type = file[len(project_name) :].strip("-_")
                    file_type = file_type.split(".")[0]
                    if not file_type:
                        file_type = ext[1:]  # Use extension if no specific type

                    files[file_type] = os.path.join(project_dir, file)
    except (OSError, FileNotFoundError):
        # Directory doesn't exist or can't be accessed - return what we have
        pass

    return files


def find_component_sheets(project_path: str, ref: str, exclude_path: str | None = None) -> list[str]:
    """Search every schematic sheet in the project for a component reference.

    Used to build a better error message when a component isn't found in the
    schematic the caller passed in, it may simply live on a different sheet.

    Args:
        project_path: Path to the .kicad_pro file
        ref: Component reference designator to search for (e.g. "U12")
        exclude_path: Schematic path to skip, typically the one already searched

    Returns:
        List of schematic file paths that contain a symbol with this reference
    """

    files = get_project_files(project_path)
    schematic_paths = files.get("schematic", [])
    if isinstance(schematic_paths, str):
        schematic_paths = [schematic_paths]

    exclude_abs = os.path.abspath(exclude_path) if exclude_path else None
    found_in = []

    for sch_path in schematic_paths:
        if exclude_abs and os.path.abspath(sch_path) == exclude_abs:
            continue
        try:
            sch = Schematic.from_file(sch_path)
        except Exception:
            continue
        for inst in sch.schematicSymbols:
            if any(p.key == "Reference" and p.value == ref for p in inst.properties):
                found_in.append(sch_path)
                break

    return found_in


def load_project_json(project_path: str) -> dict[str, Any] | None:
    """Load and parse a KiCad project file.

    Args:
        project_path: Path to the .kicad_pro file

    Returns:
        Parsed JSON data or None if parsing failed
    """
    try:
        with open(project_path) as f:
            return json.load(f)
    except Exception:
        return None
