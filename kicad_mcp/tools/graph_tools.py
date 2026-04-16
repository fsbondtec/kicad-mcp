"""
Netlist extraction, graph creation anf analysis of project
"""

import json
import os
import urllib.parse
from typing import Dict, Any
from fastmcp import FastMCP
from fastmcp.server.apps import AppConfig
import hashlib

from kicad_mcp.utils.net_parser import NetlistParser
from kicad_mcp.utils.graph_analysis import CircuitGraph
from kicad_mcp.utils.svg_utils import draw_path_to_svg, build_svg_map_from_project_files, plot_svg_schematic, plot_svg_pcb, draw_path_to_pcb_svg
from kicad_mcp.utils.file_utils import get_project_files
from kicad_mcp.utils.svg_file_server import IMAGE_VIEW_URI, FILE_SERVER_PORT, start_or_update_file_server

project_cache: Dict[str, Dict[str, Any]] = {}


def get_data(project_path: str, schematic_path: str) -> tuple[CircuitGraph, Dict]:
    """
    Get a cached circuit graph or create a new one if it does not exist or has changed.

    This function parses the KiCad schematic into a structured format and builds a 
    logical CircuitGraph. If the file hasn't changed, the 
    cached graph is returned immediately.

    Args:
        project_path (str): Absolute or relative path to the KiCad project directory.
        schematic_path (str): Path to the specific KiCad schematic file (.kicad_sch).

    Returns:
        tuple[CircuitGraph, Dict]: A tuple containing:
            - The instantiated CircuitGraph object representing the schematic logic.
            - A dictionary containing the structured raw data parsed from the netlist.
    """

    cache_key = f"{project_path}:{schematic_path}"

    # Check if cache and file hasn't been modified
    if cache_key in project_cache:
        cached = project_cache[cache_key]
        current_hash = hash_file(schematic_path)

        if cached["hash"] == current_hash:
            return cached["graph"], cached["structured_data"]
    else:
        current_hash = None

    # Parse and create new graph
    parser = NetlistParser(schematic_path)
    parser.export_netlist()
    structured_data = parser.structure_data()
    graph = CircuitGraph(structured_data, project_path)

    if current_hash is None:
        current_hash = hash_file(schematic_path)

    # Cache the results
    project_cache[cache_key] = {
        "graph": graph,
        "structured_data": structured_data,
        "hash": current_hash,
    }

    return graph, structured_data


def hash_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def register_graph_tools(mcp: FastMCP) -> None:
    """
    Register all graph-related and PCB-highlighting tools with the FastMCP server.

    Registers tools for extracting network graphs, 
    finding paths, analyzing functional blocks, and marking/unmarking paths on the PCB.

    Args:
        mcp (FastMCP): The active FastMCP server instance.
    """

    @mcp.tool()
    async def get_netGraph(project_path: str, schematic_path: str):
        """
        Extract the complete network graph (nodes and edges) of a KiCad schematic.

        Args:
            project_path (str): Path to the base KiCad project directory.
            schematic_path (str): Path to the target KiCad schematic file (.kicad_sch).

        Returns:
            Dict[str, Any]: A dictionary containing:
                - success (bool): True if the graph was successfully extracted.
                - nodes (list): A list of all component nodes in the circuit.
                - adjacency_list (dict): The connectivity mapping between components.
                - error (str, optional): Error message if extraction failed.
        """

        try:
            if not schematic_path:
                return {"success": False, "error": "Schematic path cannot be empty"}

            if not schematic_path.endswith(".kicad_sch"):
                return {"success": False, "error": "Invalid file type. Expected .kicad_sch file"}

            if not os.path.exists(schematic_path):
                return {"success": False, "error": f"Schematic file not found: {schematic_path}"}

            graph, _ = get_data(project_path, schematic_path)

            if not graph.nodes:
                return {"success": False, "error": "No components found in schematic"}

            response = {
                "success": True,
                "nodes": graph.nodes,
                "adjacency_list": graph.adjacency_list,
            }

            return response

        except FileNotFoundError as e:
            return {"success": False, "error": f"File not found: {str(e)}"}
        except PermissionError as e:
            return {"success": False, "error": f"Permission denied: {str(e)}"}
        except Exception as e:
            return {
                "success": False,
                "error": f"Error creating circuit graph: {str(e)}",
                "error_type": type(e).__name__,
            }

    @mcp.tool()
    async def get_circuit_path(
        project_path: str,
        schematic_path: str,
        start_component: str,
        end_component: str,
        max_depth: int,
        ignore_power: bool,
    ) -> Dict:
        """
        Find the shortest logical path between two components in a circuit.

        This tool traverses the logical circuit graph to find a connection route 
        between a start and an end component.

        Args:
            project_path (str): Path to the KiCad project directory (.kicad_pro).
            schematic_path (str): Path to the KiCad schematic file (.kicad_sch).
            start_component (str): The reference designator of the starting component (e.g., "R1").
            end_component (str): The reference designator of the ending component (e.g., "U3").
            max_depth (int): The maximum number of hops/components to traverse before aborting.
            ignore_power (bool): If True, ignores common power nets (GND, VCC, etc.) to 
                prevent returning trivial but useless paths across the power plane.

        Returns:
            Dict[str, Any]: A dictionary containing:
                - success (bool): True if a path was found.
                - path (list): The list of component references forming the path.
                - path_length (int): The number of components in the path.
                - error (str, optional): Error message if no path was found or invalid data.
        """

        if not os.path.exists(schematic_path):
            return {"success": False, "error": f"Schematic not found: {schematic_path}"}

        # Validate component references
        if not start_component or not start_component.strip():
            return {"success": False, "error": "Start component reference cannot be empty"}

        if not end_component or not end_component.strip():
            return {"success": False, "error": "End component reference cannot be empty"}

        try:
            graph, _ = get_data(project_path, schematic_path)


            path_result = graph.find_path(start_component, end_component, ignore_power, max_depth)


            if not path_result.get("success"):
                return {
                    **path_result,
                    "start_component": start_component,
                    "end_component": end_component,
                }


            return {
                "success": True,
                "schematic_path": schematic_path,
                "start_component": start_component,
                "end_component": end_component,
                "max_depth": max_depth,
                **path_result,
            }

        except FileNotFoundError as e:
            return {"success": False, "error": f"File not found: {str(e)}"}

        except ValueError as e:
            return {"success": False, "error": f"Invalid data: {str(e)}"}

        except Exception as e:
            return {"success": False, "error": f"Error finding circuit path: {str(e)}"}

    @mcp.tool()
    async def analyze_functional_block(
        project_path: str,
        schematic_path: str,
        center_component: str,
        ignore_power: bool,
        radius: int,
    ) -> Dict:
        """
        Analyze the functional block (neighborhood) around a given component.

        Builds the circuit graph and extracts all adjacent components and nets 
        within a specified connection radius from a central component. Useful for 
        understanding sub-circuits (e.g., finding all parts belonging to a voltage regulator).

        Args:
            project_path (str): Path to the KiCad project directory.
            schematic_path (str): Path to the KiCad schematic file (.kicad_sch).
            center_component (str): The reference designator of the central component.
            ignore_power (bool): If True, power nets are ignored during traversal.
            radius (int): The maximum connection depth (hops) to explore around the center.

        Returns:
            Dict[str, Any]: A dictionary containing:
                - success (bool): True if neighbors were successfully identified.
                - neighborhood (dict): Detailed mapping of connected components and nets.
                - center_component (str): The specified center component.
                - radius (int): The explored radius.
                - error (str, optional): Error message if extraction failed.
        """

        if not os.path.exists(schematic_path):
            return {"success": False, "error": f"Schematic not found: {schematic_path}"}

        if not center_component or not center_component.strip():
            return {"success": False, "error": "Start component reference cannot be empty"}

        try:
            graph, _ = get_data(project_path, schematic_path)


            path_result = graph.get_neighborhood(center_component, ignore_power, radius)


            if not path_result.get("success"):
                return {
                    "success": False,
                    "error": f"No neighbors found for {center_component}",
                    "center_component": center_component,
                    "radius": radius,
                }

            return {
                "success": True,
                "schematic_path": schematic_path,
                "center_component": center_component,
                "radius": radius,
                **path_result,
            }

        except FileNotFoundError as e:
            return {"success": False, "error": f"File not found: {str(e)}"}

        except ValueError as e:
            return {"success": False, "error": f"Invalid data: {str(e)}"}

        except Exception as e:
            return {"success": False, "error": f"Error finding circuit path: {str(e)}"}
    
    @mcp.tool(app=AppConfig(resource_uri=IMAGE_VIEW_URI))
    async def get_circuit_path_with_wires(
        project_path: str,
        schematic_path: str,
        start_component: str,
        end_component: str,
        max_depth: int,
        ignore_power: bool,
        svg_stroke_color: str = "#FF4400",
        svg_stroke_width: float = 1.0,
    ) -> str:
        """
        Find a path between two components in the schematic, generate SVGs and display them in the viewer.

        Args:
            project_path (str): Path to the KiCad project file (.kicad_pro).
            schematic_path (str): Path to the KiCad schematic file (.kicad_sch).
            start_component (str): Starting component reference (e.g., "R1").
            end_component (str): Ending component reference (e.g., "U3").
            max_depth (int): Maximum component hops in path finding.
            ignore_power (bool): If True, ignore power connections.
            svg_stroke_color (str, optional): Hex color for the path highlight. Defaults to "#FF4400".
            svg_stroke_width (float, optional): Stroke weight for the path highlight. Defaults to 0.4.

        Returns:
            str: JSON payload for the SVG viewer.
        """

        if not project_path.endswith('.kicad_pro'):
            project_path = f"{project_path}.kicad_pro"

        if not os.path.exists(project_path):
            return json.dumps({"error": f"Project not found: {project_path}"})

        if not schematic_path.endswith('.kicad_sch'):
            schematic_path = f"{schematic_path}.kicad_sch"

        if not os.path.exists(schematic_path):
            return json.dumps({"error": f"Schematic not found: {schematic_path}"})

        if not start_component or not start_component.strip():
            return json.dumps({"error": "Start component reference cannot be empty"})

        if not end_component or not end_component.strip():
            return json.dumps({"error": "End component reference cannot be empty"})

        try:
            plot_svg_schematic(project_path)

            graph, _ = get_data(project_path, schematic_path)

            path_result = graph.find_path_with_wire_segments(
                start=start_component,
                end=end_component,
                ignore_power=ignore_power,
                max_depth=max_depth,
            )

            if not path_result.get("success"):
                return json.dumps(path_result, ensure_ascii=False)            

            wire_segments_formatted = path_result.get("wire_segments_formatted", [])
            wire_only = [
                s for s in wire_segments_formatted
                if s["type"] == "wire" and s.get("sheet", "virtual") != "virtual"
            ]

            summary = (
                f"{start_component} → {end_component} "
                f"({path_result.get('path_length', 0)} components): "
                f"{' → '.join(path_result.get('path', []))}"
            )

            if not wire_only:
                return json.dumps({"error": f"No wire segments found. {summary}"})

            project_files = get_project_files(project_path)
            svg_map = build_svg_map_from_project_files(project_files)

            svg_result = draw_path_to_svg(
                wire_segments=wire_only,
                project_path=project_path,
                path_id_prefix=f"{start_component}_to_{end_component}",
                style={"stroke": svg_stroke_color, "stroke_width": svg_stroke_width},
                svg_map=svg_map,
            )

            if not svg_result or not svg_result.get("success"):
                errors = svg_result.get("errors", []) if svg_result else []
                return json.dumps({"error": f"SVG generation failed: {errors}"})

            written = [f["svg"] for f in svg_result.get("written_files", []) if os.path.exists(f["svg"])]

            if not written:
                return json.dumps({"error": "SVG files were not written to disk."})

            project_root = os.path.dirname(os.path.abspath(project_path))
            server_root  = start_or_update_file_server(project_root)

            def make_url(svg_file: str) -> str:
                rel = os.path.relpath(svg_file, server_root).replace("\\", "/")
                return f"http://localhost:{FILE_SERVER_PORT}/" + "/".join(urllib.parse.quote(p) for p in rel.split("/"))

            urls  = [make_url(p) for p in written]
            names = [os.path.basename(p) for p in written]

            return json.dumps({"urls": urls, "names": names, "summary": summary})

        except FileNotFoundError as e:
            return json.dumps({"error": f"File not found: {str(e)}"})

        except Exception as e:
            import traceback
            return json.dumps({
                "error": f"Error: {str(e)}",
                "traceback": traceback.format_exc(),
            })


    @mcp.tool(app=AppConfig(resource_uri=IMAGE_VIEW_URI))
    async def highlight_pcb_path(
        project_path: str,
        path_nets: list,
        svg_stroke_color: str = "#FF1493",
        svg_stroke_width: float = 2.0,
    ) -> str:
        """
        Highlight a specified list of nets on the PCB layout and display the result as SVG.

        Args:
            project_path (str): Path to the KiCad project file (.kicad_pro).
            path_nets (list): A list of net names (strings) that should be highlighted.
            svg_stroke_color (str, optional): Hex color for the path highlight. Defaults to "#FF4400".
            svg_stroke_width (float, optional): Stroke weight for the path highlight. Defaults to 1.0.

        Returns:
            str: JSON payload for the SVG viewer.
        """

        try:
            if not project_path.endswith('.kicad_pro'):
                project_path = f"{project_path}.kicad_pro"

            if not os.path.exists(project_path):
                return json.dumps({"error": f"Project not found: {project_path}"})

            svg_path = plot_svg_pcb(project_path)
            if not svg_path or not os.path.exists(svg_path):
                return json.dumps({
                    "error": "PCB SVG export failed. KiCad CLI could not export the PCB file."
                })
            
            pcb_path = os.path.splitext(project_path)[0] + ".kicad_pcb"
            svg_result = draw_path_to_pcb_svg(
                nets=path_nets,
                svg_path=svg_path,
                pcb_path=pcb_path,
                path_id_prefix="pcb_highlight",
                style={"stroke": svg_stroke_color, "stroke_width": svg_stroke_width},
            )

            if not svg_result.get("success"):
                return json.dumps({"error": f"SVG draw failed: {svg_result.get('errors')}"})

            summary = f"Highlighted nets: {', '.join(path_nets)}"

            project_root = os.path.dirname(os.path.abspath(project_path))
            server_root  = start_or_update_file_server(project_root)
            rel = os.path.relpath(svg_path, server_root).replace("\\", "/")
            url = f"http://localhost:{FILE_SERVER_PORT}/" + "/".join(urllib.parse.quote(p) for p in rel.split("/"))

            return json.dumps({
                "urls": [url],
                "names": [os.path.basename(svg_path)],
                "summary": summary,
            })

        except Exception as e:
            import traceback
            return json.dumps({
                "error": str(e),
                "traceback": traceback.format_exc(),
            })
