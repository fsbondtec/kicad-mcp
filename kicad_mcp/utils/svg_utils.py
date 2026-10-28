import difflib
import os
import re
from typing import Any, Dict, List, Optional, Tuple
import sys
import xml.etree.ElementTree as ET

from kicad_mcp.utils.kicad_cli import *
from kicad_mcp.utils.cli_drc import find_kicad_cli
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
    """
    Exports the project's schematic to SVG via kicad-cli.
    """
    cli_path = find_kicad_cli()
    if not cli_path:
        print("Error searching for cli", file=sys.stderr)
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
        print("export successfull", file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print("error when plotting", file=sys.stderr)
        print(e.stderr if e.stderr else e.stdout, file=sys.stderr)

    
def plot_svg_pcb(project_path: str):
    """
    Exports the PCB's copper layers to SVG via kicad-cli and returns the output path.
    """
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

def tracks_to_svg_path(segments, net_map: dict, nets: list) -> Tuple[str, set]:
    """
    Converts kiutils track segments matching the given nets into an SVG path string and the set of nets actually drawn.
    """
    d_parts = []
    matched_nets = set()
    nets_set = set(nets)
    for seg in segments:
        net_name = net_map.get(seg.net, "")
        if net_name not in nets_set:
            continue
        if not hasattr(seg, 'start'):
            continue
        sx, sy = seg.start.X, seg.start.Y
        ex, ey = seg.end.X, seg.end.Y
        if sx == ex and sy == ey:
            continue
        matched_nets.add(net_name)
        d_parts.append(f"M {sx:.4f} {sy:.4f} L {ex:.4f} {ey:.4f}")
    return " ".join(d_parts), matched_nets


def build_path_element(d: str, style: Dict, path_id: str) -> str:
    """
    Creates an SVG <path> element string with the given style.
    """
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
    """
    Inserts or replaces the overlay path elements in an SVG file before its closing tag.
    """

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

BLOCK_COLOR = "#1F77B4"

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)
_NUMBER = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _element_points(el) -> List[Tuple[float, float]]:
    """
    Corner points of a drawing element in sheet coordinates (kicad-cli writes absolute
    coordinates), empty for elements without geometry.
    """
    tag = el.tag.rsplit("}", 1)[-1]
    a = el.attrib
    if tag == "path":
        points = []
        for cmd, args in re.findall(r"([MLA])([^MLA]*)", a.get("d", ""), re.I):
            nums = [float(n) for n in _NUMBER.findall(args)]
            if cmd in "Aa":
                nums = [n for i in range(0, len(nums), 7) for n in nums[i + 5:i + 7]]
            points += zip(nums[0::2], nums[1::2])
        return points
    if tag in ("text", "rect"):
        x, y = float(a.get("x", 0)), float(a.get("y", 0))
        return [(x, y), (x + float(a.get("width", 0)), y + float(a.get("height", 0)))]
    if tag == "circle":
        x, y, r = float(a["cx"]), float(a["cy"]), float(a.get("r", 0))
        return [(x - r, y - r), (x + r, y + r)]
    return []


def _strip_outside(parent, box: Tuple[float, float, float, float]) -> None:
    """
    Removes every drawing element lying completely outside box (x0, y0, x1, y1).
    """
    x0, y0, x1, y1 = box
    for el in list(parent):
        transform = el.get("transform")
        if transform:
            nums = [float(n) for n in _NUMBER.findall(transform)]
            if len(nums) == 3 and not (x0 <= nums[1] <= x1 and y0 <= nums[2] <= y1):
                parent.remove(el)
            continue
        if len(el):
            _strip_outside(el, box)
            if not len(el):
                parent.remove(el)
            continue
        points = _element_points(el)
        if points and (max(x for x, _ in points) < x0 or min(x for x, _ in points) > x1
                       or max(y for _, y in points) < y0 or min(y for _, y in points) > y1):
            parent.remove(el)


def render_block_sheet(svg_file: str, parts: List[List[Tuple[float, float]]],
                       wires: List[Dict], markers: List[Tuple[float, float, str]],
                       margin: float = 12.0) -> str:
    """
    Crops a schematic sheet SVG to a block and draws the block on top.

    Args:
        svg_file: sheet SVG exported by kicad-cli.
        parts: pin positions of each block component, each drawn as a box.
        wires: wire segments of the port nets (start/end like CircuitGraph.format_node).
        markers: (x, y, text) labels, e.g. the port numbers.
        margin: space around the block in mm.

    Returns:
        SVG markup cropped to the block, with a white background.
    """
    elements = []
    points = [(x, y) for x, y, _ in markers]

    for pins in parts:
        xs, ys = [x for x, _ in pins], [y for _, y in pins]
        x0, y0 = min(xs) - 1.5, min(ys) - 1.5
        w, h = max(xs) - min(xs) + 3, max(ys) - min(ys) + 3
        elements.append(f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{w:.2f}" height="{h:.2f}" '
                        f'fill="{BLOCK_COLOR}" fill-opacity="0.15" stroke="none" />')
        points += pins

    d = segments_to_svg_path(wires)
    if d:
        elements.append(build_path_element(d, {**DEFAULT_STYLE, "stroke_width": 0.6}, "port_nets"))

    font_size = 1.2
    for x, y, text in markers:
        elements.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="0.9" fill="{DEFAULT_STYLE["stroke"]}" />')
        elements.append(f'<text x="{x:.2f}" y="{y + 0.35 * font_size:.2f}" font-size="{font_size}" '
                        f'font-family="sans-serif" text-anchor="middle" fill="white" '
                        f'stroke="none">{text}</text>')

    x0 = min(x for x, _ in points) - margin
    y0 = min(y for _, y in points) - margin
    w = max(x for x, _ in points) + margin - x0
    h = max(y for _, y in points) + margin - y0

    with open(svg_file, "r", encoding="utf-8") as f:
        svg = f.read()
    root = ET.fromstring(svg[svg.find("<svg"):])
    _strip_outside(root, (x0, y0, x0 + w, y0 + h))

    root.set("width", "100%")
    root.attrib.pop("height", None)
    root.set("style", "max-height: 400px")
    root.set("viewBox", f"{x0:.2f} {y0:.2f} {w:.2f} {h:.2f}")
    root.insert(0, ET.Element(f"{{{SVG_NS}}}rect", x=f"{x0:.2f}", y=f"{y0:.2f}",
                              width=f"{w:.2f}", height=f"{h:.2f}", fill="white"))
    root.append(ET.fromstring(f'<g xmlns="{SVG_NS}">{"".join(elements)}</g>'))
    return ET.tostring(root, encoding="unicode")


def draw_path_to_svg(
    wire_segments:  List[Dict],
    project_path:   str,
    path_id_prefix: str         = "mcp_path",
    style:          Optional[Dict] = None,
    svg_map: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Draws wire segments onto their matching schematic SVG files.
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

def resolve_pcb_nets(requested: List[str], board_net_names: set) -> Tuple[List[str], List[str], Dict[str, str]]:
    """Match requested net names against the PCB's actual net names.
    """
    known_nets: List[str] = []
    not_found_nets: List[str] = []
    resolved_nets: Dict[str, str] = {}

    for n in requested:
        if n in board_net_names:
            known_nets.append(n)
            continue

        leaf = n.rpartition("/")[2]
        leaf_matches = [bn for bn in board_net_names if leaf and bn.rpartition("/")[2] == leaf]

        if len(leaf_matches) == 1:
            known_nets.append(leaf_matches[0])
            resolved_nets[n] = leaf_matches[0]
        else:
            not_found_nets.append(n)

    return known_nets, not_found_nets, resolved_nets


def draw_path_to_pcb_svg(
    nets: list,
    svg_path: str,
    pcb_path: str,
    path_id_prefix: str = "mcp_pcb_path",
    style: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Resolves the requested nets against the PCB and injects matching track highlights into the PCB SVG.
    """
    result = {
        "success": False,
        "written_files": [],
        "errors": [],
        "highlighted_nets": [],
        "not_found_nets": [],
        "unrouted_nets": [],
        "resolved_nets": {},
    }

    try:
        board = Board.from_file(pcb_path)
    except Exception as e:
        result["errors"].append(f"Could not read PCB file: {e}")
        return result

    net_map = {n.number: n.name for n in board.nets}
    board_net_names = set(net_map.values())
    active_style = {**DEFAULT_STYLE, **(style or {})}

    known_nets, not_found_nets, resolved_nets = resolve_pcb_nets(nets, board_net_names)
    result["resolved_nets"] = resolved_nets

    for n in not_found_nets:
        suggestions = difflib.get_close_matches(n, board_net_names, n=3)
        if suggestions:
            result["errors"].append(f"Net '{n}' not found on PCB. Did you mean: {', '.join(suggestions)}?")
        else:
            result["errors"].append(f"Net '{n}' not found on PCB.")

    d, matched_nets = tracks_to_svg_path(board.traceItems, net_map, known_nets)

    unrouted_nets = [n for n in known_nets if n not in matched_nets]
    for n in unrouted_nets:
        result["errors"].append(
            f"Net '{n}' exists on the PCB but has no routed tracks/vias (pad-to-pad connection only?)."
        )

    result["not_found_nets"] = not_found_nets
    result["unrouted_nets"] = unrouted_nets
    result["highlighted_nets"] = sorted(matched_nets)

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