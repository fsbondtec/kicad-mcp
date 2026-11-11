"""
Design Rule Check (DRC) implementation using KiCad command-line interface.
"""

import os
import json
import shutil
import subprocess
import tempfile
from typing import Dict, Any, Optional

from kicad_mcp.config import system, KICAD_APP_PATH


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

            if not kicad_cli:
                results["error"] = KICAD_CLI_NOT_FOUND
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


def find_kicad_cli() -> Optional[str]:
    """Find the kicad-cli executable belonging to the configured KiCad installation.

    """
    if system == "Windows":
        candidate = os.path.join(KICAD_APP_PATH, "bin", "kicad-cli.exe")
    elif system == "Darwin":  # macOS
        candidate = os.path.join(KICAD_APP_PATH, "Contents", "MacOS", "kicad-cli")
    else:  # Linux and other Unix-like systems
        candidate = os.path.join(KICAD_APP_PATH, "bin", "kicad-cli")

    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate

    # Fall back to whatever kicad-cli is available on PATH.
    exe_name = "kicad-cli.exe" if system == "Windows" else "kicad-cli"
    return shutil.which(exe_name)


def kicad_cli_env() -> Dict[str, str]:
    """Environment for netlist exports"""
    
    config_dir = os.path.join(tempfile.gettempdir(), "kicad-mcp", "kicad-config")
    os.makedirs(config_dir, exist_ok=True)
    return {**os.environ, "KICAD_CONFIG_HOME": config_dir}


KICAD_CLI_NOT_FOUND = (
    "kicad-cli nicht gefunden. KiCad 9.0+ installiert bzw. KICAD_APP_PATH korrekt gesetzt?"
)

# seconds a netlist export may take
KICAD_CLI_EXPORT_TIMEOUT = 120


def export_netlist(schematic_path: str, netlist_format: str):
    """Export the schematic's netlist with kicad-cli.

    Args:
        schematic_path: root .kicad_sch file.
        netlist_format: kicad-cli format, e.g. 'kicadsexpr' or 'spice'.

    Returns:
        (text, error): text is the file content whenever kicad-cli wrote the file,
        error describes a failed run or a missing file, otherwise None.
    """
    
    kicad_cli = find_kicad_cli()
    if not kicad_cli:
        return None, KICAD_CLI_NOT_FOUND

    text = None
    error = None
    with tempfile.TemporaryDirectory() as temp_dir:
        output_file = os.path.join(temp_dir, "netlist")
        cmd = [kicad_cli, "sch", "export", "netlist", "--format", netlist_format,
               "--output", output_file, schematic_path]
        try:
            process = subprocess.run(cmd, capture_output=True, text=True,
                                     stdin=subprocess.DEVNULL, env=kicad_cli_env(),
                                     timeout=KICAD_CLI_EXPORT_TIMEOUT)
        except OSError as e:
            return None, f"kicad-cli konnte nicht gestartet werden: {e}"
        except subprocess.TimeoutExpired:
            return None, (f"kicad-cli-Export ({netlist_format}) nach "
                          f"{KICAD_CLI_EXPORT_TIMEOUT} s abgebrochen.")

        if process.returncode != 0:
            details = process.stderr.strip()
            if not details:
                details = "keine Fehlerausgabe"
            error = (f"kicad-cli-Export ({netlist_format}) fehlgeschlagen "
                     f"(Code {process.returncode}): {details}")

        if os.path.exists(output_file):
            with open(output_file, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        elif error is None:
            error = "kicad-cli meldete Erfolg, aber die Netlist-Datei wurde nicht erzeugt."

    return text, error
