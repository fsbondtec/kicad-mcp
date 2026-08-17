"""
Design Rule Check (DRC) implementation using KiCad command-line interface.
"""

import glob
import os
import json
import re
import subprocess
import tempfile
from typing import Dict, Any, Optional

from kicad_mcp.config import system, TIMEOUT_CONSTANTS


async def run_drc_via_cli(pcb_file: str) -> Dict[str, Any]:
    """Run DRC using KiCad command line tools.

    Args:
        pcb_file: Path to the PCB file (.kicad_pcb)

    Returns:
        Dictionary with DRC results
    """
    results = {"success": False, "method": "cli", "pcb_file": pcb_file}

    try:
        # Create a temporary directory for the output
        with tempfile.TemporaryDirectory() as temp_dir:
            # Output file for DRC report
            output_file = os.path.join(temp_dir, "drc_report.json")

            # Find kicad-cli executable
            kicad_cli = find_kicad_cli()
            from kicad_mcp.config import KICAD_APP_PATH

            if not kicad_cli:
                print("kicad-cli not found in PATH or common installation locations")
                results["error"] = (
                    "kicad-cli not found. Please ensure KiCad 9.0+ is installed and kicad-cli is available."
                )
                return results
            
            # Build the DRC command
            cmd = [kicad_cli, "pcb", "drc", "--format", "json", "--output", output_file, pcb_file]

            # print(f"Running command: {' '.join(cmd)}")
            process = subprocess.run(cmd, capture_output=True, text=True)

            # Check if the command was successful
            if process.returncode != 0:
                # print(f"DRC command failed with code {process.returncode}")
                #  print(f"Error output: {process.stderr}")
                results["error"] = f"DRC command failed: {process.stderr}"
                return results

            # Check if the output file was created
            if not os.path.exists(output_file):
                # print("DRC report file not created")
                results["error"] = "DRC report file not created"
                return results

            # Read the DRC report
            with open(output_file, "r") as f:
                try:
                    drc_report = json.load(f)
                except json.JSONDecodeError:
                    #   print("Failed to parse DRC report JSON")
                    results["error"] = "Failed to parse DRC report JSON"
                    return results

            # Process the DRC report
            violations = drc_report.get("violations", [])
            violation_count = len(violations)
            print(f"DRC completed with {violation_count} violations")

            # Categorize violations by type
            error_types = {}
            for violation in violations:
                error_type = violation.get("message", "Unknown")
                if error_type not in error_types:
                    error_types[error_type] = 0
                error_types[error_type] += 1

            # Create success response
            results = {
                "success": True,
                "method": "cli",
                "pcb_file": pcb_file,
                "total_violations": violation_count,
                "violation_categories": error_types,
                "violations": violations,
            }

            return results

    except Exception as e:
        # print(f"Error in CLI DRC: {str(e)}", exc_info=True)
        results["error"] = f"Error in CLI DRC: {str(e)}"
        return results


VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)(.*)")

cli_path_cache: Optional[str] = None

def candidate_kicad_cli_paths() -> list:
    """Collect every kicad-cli executable path found on this system.

    """
    candidates = []

    if system == "Windows":
        try:
            result = subprocess.run(["where", "kicad-cli.exe"], capture_output=True, text=True)
            if result.returncode == 0:
                candidates.extend(result.stdout.strip().splitlines())
        except Exception as e:
            print(f"Error finding kicad-cli in PATH: {str(e)}")

        candidates.extend(glob.glob("C:/Program Files/KiCad/*/bin/kicad-cli.exe"))
        candidates.extend(glob.glob("C:/Program Files (x86)/KiCad/*/bin/kicad-cli.exe"))
        candidates.append("C:/Program Files/KiCad/bin/kicad-cli.exe")
        candidates.append("C:/Program Files (x86)/KiCad/bin/kicad-cli.exe")
    else:
        try:
            result = subprocess.run(["which", "-a", "kicad-cli"], capture_output=True, text=True)
            if result.returncode == 0:
                candidates.extend(result.stdout.strip().splitlines())
        except Exception as e:
            print(f"Error finding kicad-cli in PATH: {str(e)}")

        if system == "Darwin":  # macOS
            candidates.extend(glob.glob("/Applications/KiCad*/KiCad.app/Contents/MacOS/kicad-cli"))
            candidates.append("/Applications/KiCad/kicad-cli")
        else: 
            candidates.extend(glob.glob("/opt/kicad*/bin/kicad-cli"))
            candidates.append("/usr/bin/kicad-cli")
            candidates.append("/usr/local/bin/kicad-cli")

    seen = set()
    unique_paths = []
    for path in candidates:
        if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
            continue
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        unique_paths.append(path)

    return unique_paths


def get_kicad_cli_version_info(cli_path: str):
    """Return ((major, minor, patch), is_prerelease) for a kicad-cli executable.
    """
    try:
        result = subprocess.run(
            [cli_path, "--version"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_CONSTANTS["kicad_cli_version_check"],
        )
    except Exception:
        return None

    if result.returncode != 0:
        return None

    output = (result.stdout or result.stderr).strip()
    match = VERSION_RE.search(output)
    if not match:
        return None

    major, minor, patch = (int(g) for g in match.groups()[:3])
    suffix = match.group(4).strip()
    is_prerelease = minor == 99 or bool(suffix)
    return (major, minor, patch), is_prerelease


def find_kicad_cli(force_refresh: bool = False) -> Optional[str]:
    """Find the best kicad-cli executable installed on this system.
    Among everything found, this
    prefers the highest-numbered *official* release and only falls back to a
    nightly/pre-release build if no official release is available.
    """
    global cli_path_cache

    if cli_path_cache and not force_refresh and os.path.isfile(cli_path_cache):
        return cli_path_cache

    candidates = candidate_kicad_cli_paths()

    stable_versions = []
    prerelease_versions = []
    for path in candidates:
        info = get_kicad_cli_version_info(path)
        if info is None:
            continue
        version, is_prerelease = info
        (prerelease_versions if is_prerelease else stable_versions).append((version, path))

    best_pool = stable_versions or prerelease_versions
    if best_pool:
        best_pool.sort(key=lambda item: item[0])
        cli_path_cache = best_pool[-1][1]
    elif candidates:
        cli_path_cache = candidates[0]
    else:
        cli_path_cache = None

    return cli_path_cache
