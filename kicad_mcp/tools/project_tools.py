"""
Project management tools for KiCad.
"""

import os
import logging
from typing import Dict, List, Any
from mcp.server.fastmcp import FastMCP
import platform
import subprocess

from kicad_mcp.config import KICAD_APP_PATH

from kicad_mcp.utils.kicad_utils import find_kicad_projects
from kicad_mcp.utils.file_utils import get_project_files, load_project_json


def register_project_tools(mcp: FastMCP) -> None:
    """Register project management tools with the MCcP server.

    Args:
        mcp: The FastMCP server instance
    """

    @mcp.tool()
    def list_projects() -> List[Dict[str, Any]]:
        """Find and list all KiCad projects on this system."""
        logging.info(f"Executing list_projects tool...")
        projects = find_kicad_projects()
        logging.info(f"list_projects tool returning {len(projects)} projects.")
        return projects

    @mcp.tool()
    def get_project_structure(project_path: str) -> Dict[str, Any]:
        """Get the structure and files of a KiCad project."""
        if not os.path.exists(project_path):
            return {"error": f"Project not found: {project_path}"}

        project_dir = os.path.dirname(project_path)
        project_name = os.path.basename(project_path)[:-10]  # Remove .kicad_pro extension

        # Get related files
        files = get_project_files(project_path)


        return {
            "name": project_name,
            "path": project_path,
            "directory": project_dir,
            "files": files,
        }

    @mcp.tool()
    def open_kicad_project(project_path: str) -> Dict[str, Any]:
        """
        Open a KiCad project in the KiCad project manager.

        Args:
            project_path (str): Path to the KiCad project file (.kicad_pro).

        Returns:
            Dict with success flag and status message.
        """
        if not project_path.endswith(".kicad_pro"):
            project_path = f"{project_path}.kicad_pro"

        if not os.path.exists(project_path):
            return {"success": False, "error": f"Project not found: {project_path}"}

        try:
            system = platform.system()

            if system == "Windows":
                kicad_exe = os.path.join(KICAD_APP_PATH, "bin", "kicad.exe")
                if not os.path.exists(kicad_exe):
                    return {"success": False, "error": f"kicad.exe not found: {kicad_exe}"}
                subprocess.Popen([kicad_exe, project_path])

            return {"success": True, "message": f"Opening: {os.path.basename(project_path)}"}

        except Exception as e:
            return {"success": False, "error": f"Failed to open KiCad: {str(e)}"}