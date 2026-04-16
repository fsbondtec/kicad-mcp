import os
import re
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET
import sys

from kicad_mcp.utils.kicad_cli import *
from kicad_mcp.utils.file_utils import get_project_files 

from kiutils.board import Board


OVERLAY_START = "<!-- path_overlay_start -->"
OVERLAY_END   = "<!-- path_overlay_end -->"

DEFAULT_STYLE = {
    "stroke":         "#FF4400",
    "stroke_width":   0.4,        
    "stroke_opacity": 0.85,
    "fill":           "none",
    "stroke_linecap": "round",
    "stroke_linejoin":"round",
}

def plot_svg_schematic(project_path: str):
    try:
        cli_path = get_kicad_cli_path(required=True)
    except KiCadCLIError as e:
        print("Error searching for cli")
        return
    
    base_path, _ = os.path.splitext(project_path)
    main_sch_path = f"{base_path}.kicad_sch"

    if not os.path.exists(main_sch_path):
        print(f"Schematic not found: {main_sch_path}", file=sys.stderr)
        return
    
    project_dir = os.path.dirname(project_path)

    cmd = [
        cli_path,
        "sch",
        "export",
        "svg",
        "--output", project_dir,
        main_sch_path
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("export successfull")
    except subprocess.CalledProcessError as e:
        print("error when plotting")
        print(e.stderr if e.stderr else e.stdout)

    
def plot_svg_pcb(project_path: str):
    try:
        cli_path = get_kicad_cli_path(required=True)
    except KiCadCLIError as e:
        print("Error searching for cli")
        return
    
    base_path, _ = os.path.splitext(project_path)
    main_sch_path = f"{base_path}.kicad_pcb"
    project_name = os.path.basename(base_path)


    project_dir = os.path.dirname(project_path)
    cam_dir = os.path.join(project_dir, "CAM")
    output_dir = cam_dir if os.path.isdir(cam_dir) else project_dir

    output_svg = os.path.join(output_dir, f"{project_name}_pcb.svg")

    cmd = [
            cli_path, "pcb", "export", "svg",
            "--output", output_svg,
            "--layers", "F.Cu,B.Cu", 
            "--page-size-mode", "0", #same viewbox as schematic 
            main_sch_path
        ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return output_svg
    except subprocess.CalledProcessError as e:
        print("error when plotting")
        print(e.stderr if e.stderr else e.stdout)
        return None



def build_svg_map_from_project_files(project_files: Dict) -> Dict[str, str]:
    """
    Maps the schematic file names to svg file names
    """
    svg_map: Dict[str, str] = {}

    project_path = project_files.get("project")
    if not project_path:
        return svg_map
    
    project_dir = os.path.dirname(project_path)

    schematics: List[str] = project_files.get("schematic", [])
    if isinstance(schematics, str):
        schematics = [schematics]

    try:
        svg_files = [f for f in os.listdir(project_dir) if f.lower().endswith(".svg")]
        
        for sch_path in schematics:
            clean_path = sch_path.replace('\\', '/')
            sch_basename = os.path.basename(clean_path)
            sch_name_only = os.path.splitext(sch_basename)[0].lower()
            
            sch_name_normalized = sch_name_only.replace(" ", "_")
            best_match = None
            
            for file in svg_files:
                file_lower = file.lower()
                file_base = os.path.splitext(file_lower)[0]

                file_base_normalized = file_base.replace(" ", "_")
                
                if file_base_normalized == sch_name_normalized:
                    best_match = file
                    break  
                    
                elif file_base_normalized.endswith(f"-{sch_name_normalized}") or file_base_normalized.endswith(f"_{sch_name_normalized}"):
                    best_match = file
                    break
            
            if not best_match:
                for file in svg_files:
                    if sch_name_normalized in file.lower():
                        best_match = file

            if best_match:
                svg_map[sch_path] = os.path.join(project_dir, best_match)
                
    except (OSError, FileNotFoundError) as e:
        print(f"Error searching directory: {e}")

    return svg_map


def segments_to_svg_path(segments: List[Dict]) -> str:
    """
    Converts the wire segments of the wire graph to svg path 
    """
    d_parts = []
    for seg in segments:
        start_node = seg.get("start", {})
        end_node = seg.get("end", {})
        
        start_pos = start_node.get("position")
        end_pos = end_node.get("position")
        
        if not start_pos or not end_pos:
            continue
            
        sx, sy = start_pos.get("x", 0), start_pos.get("y", 0)
        ex, ey = end_pos.get("x", 0), end_pos.get("y", 0)
        
        if sx == ex and sy == ey:
            continue
            
        d_parts.append(f"M {sx:.4f} {sy:.4f} L {ex:.4f} {ey:.4f}")
        
    return " ".join(d_parts)

def tracks_to_svg_path(segments, net_map: dict, nets: list) -> str:
    """Converts kiutils track segments to an SVG path string."""
    d_parts = []
    for seg in segments:
        net_name = net_map.get(seg.net, "")
        if net_name not in nets:
            continue
        if not hasattr(seg, 'start'):  
            continue
        sx, sy = seg.start.X, seg.start.Y
        ex, ey = seg.end.X, seg.end.Y
        if sx == ex and sy == ey:
            continue
        d_parts.append(f"M {sx:.4f} {sy:.4f} L {ex:.4f} {ey:.4f}")
    return " ".join(d_parts)


def build_path_element(d: str, style: Dict, path_id: str) -> str:
    """Creates SVG <path>-Tag as string."""
    sw = style["stroke_width"]
    return (
        f'<path id="{path_id}" '
        f'd="{d}" '
        f'stroke="{style["stroke"]}" '
        f'stroke-width="{sw}" '
        f'stroke-opacity="{style["stroke_opacity"]}" '
        f'stroke-linecap="{style["stroke_linecap"]}" '
        f'stroke-linejoin="{style["stroke_linejoin"]}" '
        f'fill="{style["fill"]}" />'
    )

def inject_into_svg(svg_path: str, new_elements: str, path_id_prefix: str) -> bool:
    """Add path before svg closing tag"""

    with open(svg_path, "r", encoding="utf-8") as f:
        content = f.read()

    group = (
        f'\n{OVERLAY_START}\n'
        f'<g id="overlay_{path_id_prefix}">\n'
        f'  {new_elements}\n'
        f'</g>\n'
        f'{OVERLAY_END}\n'
    )

    #if a Path already exists in the file it is overwritten 
    pattern = re.compile(
        re.escape(OVERLAY_START) + r".*?" + re.escape(OVERLAY_END),
        re.DOTALL
    )
    if pattern.search(content):
        new_content = pattern.sub(lambda m: group.strip(), content)
    else:
        if "</svg>" not in content:
            return False
        new_content = content.replace("</svg>", group + "</svg>", 1)

    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return True

def draw_path_to_svg(
    wire_segments:  List[Dict],
    project_path:   str,
    path_id_prefix: str         = "mcp_path",
    style:          Optional[Dict] = None,
    svg_map: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    draw wire segments in svg files
    """
    result = {
        "success":       False,
        "written_files": [],
        "skipped_sheets": [],
        "errors":        [],
    }

    if not wire_segments:
        result["errors"].append("No wire segments given")
        return result

    active_style = {**DEFAULT_STYLE, **(style or {})}

    by_sheet: Dict[str, List[Dict]] = {}
    for seg in wire_segments:
        sheet = seg.get("sheet", "")
        if not sheet:
            result["skipped_sheets"].append({"sheet": "(empty)", "reason": "no sheet in segment"})
            continue
        by_sheet.setdefault(sheet, []).append(seg)

    if not by_sheet:
        result["errors"].append("No segments with sheet found")
        return result

    
    any_written = False
    for sheet, segs in by_sheet.items():
        svg_file = (svg_map or {}).get(sheet) 
        if svg_file is None:
            result["skipped_sheets"].append({
                "sheet":  sheet,
                "reason": f"No svg File found in project folder (searched for: *{sheet}*.svg)"
            })
            continue

        d = segments_to_svg_path(segs)
        if not d:
            result["skipped_sheets"].append({
                "sheet":  sheet,
                "reason": "all segments are virtual bridges, skipped"
            })
            continue

        safe_sheet_name = sheet.replace("\\", "_").replace("/", "_").replace(":", "")
        pid = f"{path_id_prefix}_{safe_sheet_name}"
        element_str = build_path_element(d, active_style, pid)

        try:
            ok = inject_into_svg(svg_file, element_str, path_id_prefix)
        except Exception as e:
            result["errors"].append(f"[{sheet}] Error writing: {e}")
            continue

        if ok:
            result["written_files"].append({
                "svg":           svg_file,
                "sheet":         sheet,
                "segment_count": len(segs),
            })
            any_written = True
        else:
            result["errors"].append(f"[{sheet}] svg does not hav </svg>-tag, file was not changed.")

    result["success"] = any_written
    return result

def draw_path_to_pcb_svg(
    nets: list,
    svg_path: str,
    pcb_path: str,
    path_id_prefix: str = "mcp_pcb_path",
    style: Optional[Dict] = None,
) -> Dict[str, Any]:
    result = {"success": False, "written_files": [], "errors": []}

    try:
        board = Board.from_file(pcb_path)
    except Exception as e:
        result["errors"].append(f"Could not read PCB file: {e}")
        return result

    net_map = {n.number: n.name for n in board.nets}
    active_style = {**DEFAULT_STYLE, **(style or {})}

    d = tracks_to_svg_path(board.traceItems, net_map, nets)
    if not d:
        result["errors"].append("No matching tracks found for given nets")
        return result

    element = build_path_element(d, active_style, path_id_prefix)
    ok = inject_into_svg(svg_path, element, path_id_prefix)

    if ok:
        result["success"] = True
        result["written_files"].append(svg_path)
    else:
        result["errors"].append("inject_into_svg failed")

    return result