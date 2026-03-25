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
from kicad_mcp.utils.svg_utils import draw_path_to_svg, build_svg_map_from_project_files, plot_svg
from kicad_mcp.utils.file_utils import get_project_files
from kicad_mcp.utils.pcb_highlight_utils import PcbHighlightManager
from kicad_mcp.utils.svg_file_server import IMAGE_VIEW_URI, FILE_SERVER_PORT, start_or_update_file_server

project_cache: Dict[str, Dict[str, Any]] = {}
pcb_manager = PcbHighlightManager()


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
            project_path (str): Path to the KiCad project directory.
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
                    "success": False,
                    "error": f"No path found between {start_component} and {end_component}",
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
        Find a path between two components, generate SVGs and display them in the viewer.

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
            plot_svg(project_path)

            graph, _ = get_data(project_path, schematic_path)

            path_result = graph.find_path_with_wire_segments(
                start=start_component,
                end=end_component,
                ignore_power=ignore_power,
                max_depth=max_depth,
            )

            if not path_result.get("success"):
                return json.dumps({
                    "error": f"No path found between {start_component} and {end_component}",
                })

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

            start_or_update_file_server(os.path.dirname(os.path.abspath(written[0])))
            urls  = [f"http://localhost:{FILE_SERVER_PORT}/{urllib.parse.quote(os.path.basename(p))}" for p in written]
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


    @mcp.tool()
    async def highlight_path(
        project_path: str,
        path_nets: list,
        layer: str | None,
    ) -> Dict[str, Any]:
        """
        Highlight a specified list of nets on the active KiCad PCB layout.

        This tool communicates with the KiCad PCB editor instance to visually mark
        the tracks corresponding to the given nets. The highlights are drawn on a user/eco layer, 
        making them easy to spot. State is cached internally so they can be removed later.

        Args:
            project_path (str): Path to the KiCad project directory (used for caching IDs).
            path_nets (list): A list of net names (strings) that should be highlighted.
            layer (str | None): The specific KiCad layer name to draw on (e.g., "Eco1.User").
                If None is provided, the function will automatically select an available layer.

        Returns:
            Dict[str, Any]: A dictionary containing:
                - success (bool): True if the operation succeeded and items were drawn.
                - project_path (str): The project path reference.
                - highlighted_nets (list): The specific nets that were successfully matched and drawn.
                - used_layer (str): The actual layer on which the highlights were drawn.
                - currently_used_layers (list): Layers currently occupied by highlights in this project.
                - created_items_len (int): The number of individual board segments created.
                - error (str, optional): Aggregated error messages if the operation failed.
        """
        try:
           
            layer_info = pcb_manager.get_user_layers()

            if layer is None:
                layer = auto_select_layer(project_path, layer_info["available"])

            mark_result = pcb_manager.mark_path(path_nets, layer)

            if not mark_result["success"]:
                return {
                    "success": False,
                    "error": "; ".join(mark_result["errors"]),
                    "available_user_layers": layer_info["available"],
                }

            # cache die übergebenen Ids
            cache_key = f"{project_path}:highlights"

            if cache_key not in pcb_manager.highlight_cache:
                pcb_manager.highlight_cache[cache_key] = []

            pcb_manager.highlight_cache[cache_key].append(
                {
                    "layer": mark_result["used_layer"],
                    "nets": path_nets,
                    "item_ids": mark_result["created_items"],
                }
            )

            # welche layer werden derzeit verwendet
            used_layers = {h["layer"] for h in pcb_manager.highlight_cache[cache_key]}

            return {
                "success": True,
                "project_path": project_path,
                "highlighted_nets": mark_result["highlighted_nets"],
                "used_layer": mark_result["used_layer"],
                "available_user_layers": layer_info["available"],
                "currently_used_layers": list(used_layers),
                "requested_nets": len(path_nets),
                "created_items_len": len(mark_result["created_items"]),
                "suggestion": f"Next path can use one of: {[l for l in layer_info['available'] if l not in used_layers]}",
            }

        except Exception as e:
            return {"success": False, "error": str(e)}
        

    @mcp.tool()
    async def unmark_paths(
        project_path: str, layers: list[str] | None
    ) -> Dict[str, Any]:
        """
        Remove highlighted paths from the active KiCad PCB layout.

        Uses the internal cache generated by `highlight_path` to find the KiCad object IDs
        of the previously drawn highlight segments and deletes them. Can target specific 
        layers or clear all highlights for the given project.

        Args:
            project_path (str): Path to the KiCad project directory (used to access the cache).
            layers (list[str] | None): A list of layer names to clear (e.g., ["Eco1.User"]). 
                If None is provided, highlights across ALL tracked layers are deleted.

        Returns:
            Dict[str, Any]: A dictionary containing:
                - success (bool): True if items were successfully removed.
                - project_path (str): The relevant project path.
                - deleted_items (int): Total number of board segments deleted.
                - paths_cleared (int): Number of distinct path groupings removed.
                - layers_cleared (list): The names of the layers that were cleared.
                - error/errors (list/str, optional): Error messages or failure reasons.
        """
        try:

            cache_key = f"{project_path}:highlights"

            if cache_key not in pcb_manager.highlight_cache:
                return {
                    "success": False,
                    "error": "No cached highlights found",
                    "info": "if something was not deletet just hit Ctr + Z to revert the last changes or remove the highlights manually",
                }

            all_item_ids = []
            layers_cleared = set()

            layers_to_keep = []
            layers_to_remove = []

            for entry in pcb_manager.highlight_cache[cache_key]:
                if layers is None or entry["layer"] in layers:
                    all_item_ids.extend(entry["item_ids"])
                    layers_cleared.add(entry["layer"])
                    layers_to_remove.append(entry)
                else:
                    layers_to_keep.append(entry)

            if not all_item_ids:
                del pcb_manager.highlight_cache[cache_key]
                return {
                    "success": False,
                    "error": "No items to delete",
                    "info": "if something was not deletet just hit Ctr + Z to revert the last changes or remove the highlights manually",
                }

            unmark_result = pcb_manager.unmark_path(all_item_ids)

            paths_cleared = len(layers_to_remove)
            if layers_to_keep:
                pcb_manager.highlight_cache[cache_key] = layers_to_keep
            else:
                del pcb_manager.highlight_cache[cache_key]

            return {
                "success": unmark_result["success"],
                "project_path": project_path,
                "deleted_items": unmark_result["deleted_items"],
                "paths_cleared": paths_cleared,
                "layers_cleared": list(layers_cleared),
                "errors": unmark_result.get("errors", []),
                "layers_remaining": sorted(list({e["layer"] for e in layers_to_keep}))
                if layers_to_keep
                else [],
                "info": "if something was not deletet just hit Ctr + Z to revert the last changes or remove the highlights manually",
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def auto_select_layer(project_path: str, available_layers: list[str]) -> str:
        """
        Automatically select the next unused user/eco layer for PCB highlighting.

        Checks the active project's highlight cache to determine which layers are 
        currently occupied by drawn paths. It iterates through the provided available 
        layers and returns the first one that is completely empty.

        If all preferred layers are in use or the list is empty, it falls back to 
        returning the first available layer or a hardcoded default ("Eco1.User").

        Args:
            project_path (str): Path to the KiCad project (used as the cache key).
            available_layers (list[str]): A list of all enabled user/eco layers on the board, 
                ideally ordered by preference (e.g., ["Eco1.User", "Eco2.User", ...]).

        Returns:
            str: The canonical name of the selected target layer.
        """
        cache_key = f"{project_path}:highlights"

        if cache_key in pcb_manager.highlight_cache:
            used_layers = {h["layer"] for h in pcb_manager.highlight_cache[cache_key]}

            for layer in available_layers:
                if layer not in used_layers:
                    return layer

        # erster available layer oder default
        return available_layers[0] if available_layers else "Eco1.User"

