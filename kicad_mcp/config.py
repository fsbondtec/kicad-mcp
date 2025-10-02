"""
Configuration settings for the KiCad MCP server.
"""
import os

import platform

# Determine operating system
system = platform.system()

# KiCad paths based on operating system
if system == "Darwin":  # macOS
    KICAD_USER_DIR = os.path.expanduser("~/Documents/KiCad")
    KICAD_APP_PATH = "/Applications/KiCad/KiCad.app"
elif system == "Windows":
    #Edit
    KICAD_USER_DIR = "C:/Users/messeel/KiCad/9.0/projects"
    KICAD_APP_PATH = "C:/Program Files/KiCad/9.0/"
    KICAD_TABLE_PATH = os.path.join(os.getenv('APPDATA'), 'kicad')
    DATASHEET_PATH = os.path.join(os.getenv('USERPROFILE'), 'KiCadProjects')
    
elif system == "Linux":
    KICAD_USER_DIR = os.path.expanduser("~/KiCad")
    KICAD_APP_PATH = "/usr/share/kicad"
else:
    # Default to macOS paths if system is unknown
    KICAD_USER_DIR = os.path.expanduser("~/Documents/KiCad")
    KICAD_APP_PATH = "/Applications/KiCad/KiCad.app"

# Additional search paths from environment variable
ADDITIONAL_SEARCH_PATHS = []
env_search_paths = os.environ.get("KICAD_SEARCH_PATHS", "")
if env_search_paths:
    for path in env_search_paths.split(","):
        expanded_path = os.path.expanduser(path.strip())
        if os.path.exists(expanded_path):
            ADDITIONAL_SEARCH_PATHS.append(expanded_path)

# Try to auto-detect common project locations if not specified
DEFAULT_PROJECT_LOCATIONS = [
    "~/Documents/PCB",
    "~/PCB",
    "~/Electronics",
    "~/Projects/Electronics",
    "~/Projects/PCB",
    "~/Projects/KiCad"
]

for location in DEFAULT_PROJECT_LOCATIONS:
    expanded_path = os.path.expanduser(location)
    if os.path.exists(expanded_path) and expanded_path not in ADDITIONAL_SEARCH_PATHS:
        ADDITIONAL_SEARCH_PATHS.append(expanded_path)

# Base path to KiCad's Python framework
if system == "Darwin":  # macOS
    KICAD_PYTHON_BASE = os.path.join(KICAD_APP_PATH, "Contents/Frameworks/Python.framework/Versions")
else:
    KICAD_PYTHON_BASE = ""  # Will be determined dynamically in python_path.py


# File extensions
KICAD_EXTENSIONS = {
    "project": ".kicad_pro",
    "pcb": ".kicad_pcb",
    "schematic": ".kicad_sch",
    "design_rules": ".kicad_dru",
    "worksheet": ".kicad_wks",
    "footprint": ".kicad_mod",
    "netlist": "_netlist.net",
    "kibot_config": ".kibot.yaml",
}

# Recognized data files
DATA_EXTENSIONS = [
    ".csv",  # BOM or other data
    ".pos",  # Component position file
]
