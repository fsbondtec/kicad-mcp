"""
Netlist extraction, graph creation anf analysis of project
"""
import os
from typing import Dict, Any
from mcp.server.fastmcp import FastMCP, Context
import hashlib

from kicad_mcp.utils.net_parser import NetlistParser
from kicad_mcp.utils.graph_analysis import CircuitGraph

project_cache: Dict[str, Dict[str, Any]] = {}
highlight_cache = {} #cache for all highlighted KIIDs

def get_data(project_path: str, schematic_path: str) -> tuple[CircuitGraph, Dict]:
    """Get cached graph or create new one if not exists.
    
    Args:
        project_path: Path to the project
        schematic_path: Path to the schematic file
        
    Returns:
        Tuple of (CircuitGraph, structured_data)
    """
    cache_key = f"{project_path}:{schematic_path}"
    
    # Check if cache and file hasn't been modified
    if cache_key in project_cache:
        cached = project_cache[cache_key]  
        current_hash = hash_file(schematic_path)
      

        if cached['hash'] == current_hash:
            return cached['graph'], cached['structured_data']
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
        'graph': graph,
        'structured_data': structured_data,
        'hash': current_hash
    }
    
    return graph, structured_data

def hash_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()
        


def register_graph_tools(mcp: FastMCP) -> None:
    """Register graph-related tools with the MCP server.
    
    Args:
        mcp: The FastMCP server instance
    """
    
    @mcp.tool()
    async def get_netGraph(project_path: str, schematic_path: str, ctx: Context | None):
        """Get the complete network graph of a KiCad schematic.
        
        Args:
            schematic_path: Path to the KiCad schematic file (.kicad_sch)
            ctx: MCP context for progress reporting
            
        Returns:
            Dictionary with nodes, edges, and adjacency list or error message
        """
        try:
            if not schematic_path:
                return {
                    "success": False,
                    "error": "Schematic path cannot be empty"
                }
            
            if not schematic_path.endswith('.kicad_sch'):
                return {
                    "success": False,
                    "error": "Invalid file type. Expected .kicad_sch file"
                }
            
            if not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "error": f"Schematic file not found: {schematic_path}"
                }
            
            graph, _ = get_data(project_path, schematic_path)
    
            if not graph.nodes:
                return {
                    "success": False,
                    "error": "No components found in schematic"
                }
            
            response = {
                "success": True,
                "nodes": graph.nodes,
                "adjacency_list": graph.adjacency_list
            }
            
            return response
            
        except FileNotFoundError as e:
            return {
                "success": False,
                "error": f"File not found: {str(e)}"
            }
        except PermissionError as e:
            return {
                "success": False,
                "error": f"Permission denied: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error creating circuit graph: {str(e)}",
                "error_type": type(e).__name__
            }



    @mcp.tool()
    async def get_circuit_path(project_path: str, schematic_path: str, start_component: str, 
                            end_component: str, max_depth: int, ignore_power:bool, ctx: Context | None) -> Dict:
        """Find the shortest path between two components in a circuit.
    
        This tool analyzes the circuit netlist and finds the connection path
        between two specified components.
        
        Args:
            schematic_path: Path to the KiCad schematic file (.kicad_sch)
            start_component: Starting component reference (e.g., "R1")
            end_component: Ending component reference (e.g., "U3")
            abstraction_level: high | medium | low -> filter the graph based on abstraction level
            max_depth: Maximum number of components in the path
            ctx: MCP context for progress reporting
            
        Returns:
            Dictionary with path information or error message
        """

        if not os.path.exists(schematic_path):
            if ctx:
                ctx.info(f"Schematic not found: {schematic_path}")
            return {"success": False, "error": f"Schematic not found: {schematic_path}"}
        
        # Validate component references
        if not start_component or not start_component.strip():
            if ctx:
                ctx.info("Start component reference is empty")
            return {"success": False, "error": "Start component reference cannot be empty"}
        
        if not end_component or not end_component.strip():
            if ctx:
                ctx.info("End component reference is empty")
            return {"success": False, "error": "End component reference cannot be empty"}
        
        try:
                
            graph, _ = get_data(project_path, schematic_path)
            
            if ctx:
                await ctx.report_progress(80, 100)
                ctx.info(f"Finding path from {start_component} to {end_component}...")
                
            path_result = graph.find_path(start_component, end_component, ignore_power, max_depth)
            
            if ctx:
                await ctx.report_progress(100, 100)
            
            if not path_result.get("success"):
                if ctx:
                    ctx.info(f"No path found between {start_component} and {end_component}")
                return {
                    "success": False,
                    "error": f"No path found between {start_component} and {end_component}",
                    "start_component": start_component,
                    "end_component": end_component
                }
            
            if ctx:
                ctx.info(f"Path found with {path_result.get('path_length', 0)} components")
            
            return {
                "success": True,
                "schematic_path": schematic_path,
                "start_component": start_component,
                "end_component": end_component,
                "max_depth": max_depth,
                **path_result  
            }
            
        except FileNotFoundError as e:
            if ctx:
                ctx.info(f"File not found: {str(e)}")
            return {"success": False, "error": f"File not found: {str(e)}"}
        
        except ValueError as e:
            if ctx:
                ctx.info(f"Invalid data encountered: {str(e)}")
            return {"success": False, "error": f"Invalid data: {str(e)}"}
        
        except Exception as e:
            if ctx:
                ctx.info(f"Error finding circuit path: {str(e)}")
            return {"success": False, "error": f"Error finding circuit path: {str(e)}"}
        
    @mcp.tool()
    async def analyze_functional_block(project_path: str, schematic_path: str, center_component: str, ignore_power:bool, radius: int, ctx: Context | None) -> Dict:
        
        """
        Analyze the functional block around a given component in a schematic.

        This function parses a schematic netlist, builds a circuit graph, and performs
        a neighborhood analysis around a specified central component. The goal is to
        identify all components (and optionally nets) within a given connection radius,
        providing the structural basis for Functional Block Analysis.
        """
        
        if not os.path.exists(schematic_path):
            if ctx:
                ctx.info(f"Schematic not found: {schematic_path}")
            return {"success": False, "error": f"Schematic not found: {schematic_path}"}
        
        if not center_component or not center_component.strip():
            if ctx:
                ctx.info("Start component reference is empty")
            return {"success": False, "error": "Start component reference cannot be empty"}
        
        try:
                
            graph, _ = get_data(project_path, schematic_path)
            
            if ctx:
                await ctx.report_progress(80, 100)
                ctx.info(f"Finding path from neighbors {center_component}...")
                
            path_result = graph.get_neighborhood(center_component, ignore_power, radius)
            
            if ctx:
                await ctx.report_progress(100, 100)
            
            if not path_result.get("success"):
                if ctx:
                    ctx.info(f"No neighbors found for {center_component}")
                return {
                    "success": False,
                    "error": f"No neighbors found for {center_component}",
                    "center_component": center_component,
                    "radius": radius
                }
            
            
            return {
                "success": True,
                "schematic_path": schematic_path,
                "center_component": center_component,
                "radius": radius,
                **path_result  
            }
            
        except FileNotFoundError as e:
            if ctx:
                ctx.info(f"File not found: {str(e)}")
            return {"success": False, "error": f"File not found: {str(e)}"}
        
        except ValueError as e:
            if ctx:
                ctx.info(f"Invalid data encountered: {str(e)}")
            return {"success": False, "error": f"Invalid data: {str(e)}"}
        
        except Exception as e:
            if ctx:
                ctx.info(f"Error finding circuit path: {str(e)}")
            return {"success": False, "error": f"Error finding circuit path: {str(e)}"}
        
        
    @mcp.tool()
    async def highlight_path(project_path: str, schematic_path: str, path_nets: list, layer: str | None, ctx: Context | None) -> Dict[str, Any]:
        """
        Mark the given path in KiCad pcb File on a User Layer.

        Args:
            schematic_path: Path to the KiCad schematic file (.kicad_sch)
            path_nets: simple list of nets to mark
            layer: Optional specific layer name (e.g., "Eco1.User"). If None, auto-select.
            ctx: MCP context

        Returns:
            Dictionary with success status
        """
        try:
            if not schematic_path:
                return {
                    "success": False,
                    "error": "Schematic path cannot be empty"
                }
            
            if not schematic_path.endswith('.kicad_sch'):
                return {
                    "success": False,
                    "error": "Invalid file type. Expected .kicad_sch file"
                }
            
            if not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "error": f"Schematic file not found: {schematic_path}"
                }
            
            graph, _ = get_data(project_path, schematic_path)

            layer_info = graph.get_user_layers()

            if layer is None:
                layer = auto_select_layer(project_path, layer_info["available"])

            mark_result = graph.mark_path(path_nets, layer)

            if not mark_result["success"]:
                return {
                    "success": False,
                    "error": "; ".join(mark_result["errors"]),
                    "available_user_layers": layer_info["available"]
                }

            #cache die übergebenen Ids
            cache_key = f"{project_path}:highlights"

            if cache_key not in highlight_cache:
                highlight_cache[cache_key] = []
        
            highlight_cache[cache_key].append({
                "layer": mark_result["used_layer"],
                "nets": path_nets,
                "item_ids": mark_result["created_items"]
            })

            # welche layer werden derzeit verwendet
            used_layers = {h["layer"] for h in highlight_cache[cache_key]}


            if ctx:
                await ctx.report_progress(100, 100)

            
            return {
                "success" : True,
                "project_path": project_path,
                "highlighted_nets": mark_result["highlighted_nets"],
                "used_layer": mark_result["used_layer"],
                "available_user_layers": layer_info["available"],
                "currently_used_layers": list(used_layers),
                "requested_nets": len(path_nets),
                "created_items_len": len(mark_result["created_items"]),
                "suggestion": f"Next path can use one of: {[l for l in layer_info['available'] if l not in used_layers]}"

            }
        
        except Exception as e:
            if ctx:
                ctx.info(f"Error marking path: {str(e)}")
            return {"success": False, "error": str(e)}
    
    @mcp.tool()
    async def unmark_paths(project_path: str, schematic_path: str, layers: list[str] | None, ctx: Context | None) -> Dict[str, Any]:
        """
        Unmark all paths that are on the given layers in the Kicad Project pcb File 

        Args:
            schematic_path: Path to the KiCad schematic file (.kicad_sch)
            ctx: MCP context

        Returns:
            Dictionary with success status
        """
        try:
            if not schematic_path:
                return {
                    "success": False,
                    "error": "Schematic path cannot be empty"
                }
            
            if not schematic_path.endswith('.kicad_sch'):
                return {
                    "success": False,
                    "error": "Invalid file type. Expected .kicad_sch file"
                }
            
            if not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "error": f"Schematic file not found: {schematic_path}"
                }
            
            cache_key = f"{project_path}:highlights"

            if cache_key not in highlight_cache:
                return {
                    "success": False, 
                    "error": "No cached highlights found",  
                    "info": "if something was not deletet just hit Ctr + Z to revert the last changes or remove the highlights manually"
                }
    
            all_item_ids = []
            layers_cleared = set()

            layers_to_keep = []
            layers_to_remove = []

            for entry in highlight_cache[cache_key]:
                if layers is None or entry["layer"] in layers:
                    all_item_ids.extend(entry["item_ids"])
                    layers_cleared.add(entry["layer"])
                    layers_to_remove.append(entry)
                else:
                    layers_to_keep.append(entry)
            
            
            if not all_item_ids:
                del highlight_cache[cache_key]
                return {
                    "success": False,
                    "error": "No items to delete",
                    "info": "if something was not deletet just hit Ctr + Z to revert the last changes or remove the highlights manually"

                }
            
            graph, _ = get_data(project_path, schematic_path)
            unmark_result = graph.unmark_path(all_item_ids)

            paths_cleared = len(layers_to_remove)
            if layers_to_keep:
                highlight_cache[cache_key] = layers_to_keep
            else:
                del highlight_cache[cache_key]


            if ctx:
                await ctx.report_progress(100, 100)
            
            return {
                "success": unmark_result["success"],
                "project_path": project_path,
                "schematic_path": schematic_path,
                "deleted_items": unmark_result["deleted_items"],
                "paths_cleared": paths_cleared,
                "layers_cleared": list(layers_cleared),
                "errors": unmark_result.get("errors", []),
                "layers_remaining": sorted(list({e["layer"] for e in layers_to_keep})) if layers_to_keep else [],
                "info": "if something was not deletet just hit Ctr + Z to revert the last changes or remove the highlights manually"
            }
        
        except Exception as e:
            if ctx:
                ctx.info(f"Error marking path: {str(e)}")
            return {"success": False, "error": str(e)}
        
    def auto_select_layer(project_path: str, available_layers: list[str]) -> str:
        """
        Automatically select next unused user layer for highlighting.
        
        Prefers Eco1.User, Eco2.User, then User.1-9 in order.
        """
        cache_key = f"{project_path}:highlights"
         
        if cache_key in highlight_cache:
            used_layers = {h["layer"] for h in highlight_cache[cache_key]}
            
            for layer in available_layers:
                if layer not in used_layers:
                    return layer
        
        # erster available layer oder default
        return available_layers[0] if available_layers else "Eco1.User"





        
