"""
Netlist extraction, graph creation anf analysis of project
"""
import os
from typing import Dict, Any
from mcp.server.fastmcp import FastMCP, Context

from kicad_mcp.utils.net_parser import NetlistParser
from kicad_mcp.utils.graph_analysis import CircuitGraph

def register_graph_tools(mcp: FastMCP) -> None:
    """Register graph-related tools with the MCP server.
    
    Args:
        mcp: The FastMCP server instance
    """
    

    @mcp.tool()
    async def get_netGraph(schematic_path: str, ctx: Context | None):
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
            

            parser = NetlistParser(schematic_path)
            parser.export_netlist()            
            structured_data = parser.structure_data()
            graph = CircuitGraph(structured_data)
            
            if not graph.nodes:
                return {
                    "success": False,
                    "error": "No components found in schematic"
                }
            
            response = {
                "success": True,
                "nodes": graph.nodes,
                "edges": graph.edges,
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
    async def get_circuit_path(schematic_path: str, start_component: str, 
                            end_component: str, max_depth: int, ctx: Context | None, abstraction_level = "medium") -> Dict:
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
            if ctx:
                await ctx.report_progress(10, 100)
                ctx.info(f"Parsing netlist from: {os.path.basename(schematic_path)}")
                
            parser = NetlistParser(schematic_path)
            parser.export_netlist()
            
            if ctx:
                await ctx.report_progress(40, 100)
                ctx.info("Structuring netlist data...")
            
            structured_data = parser.structure_data()
            
            if not structured_data:
                if ctx:
                    ctx.info("Failed to structure netlist data")
                return {"success": False, "error": "Failed to structure netlist data"}
            
            if ctx:
                await ctx.report_progress(60, 100)
                ctx.info("Building circuit graph...")
            
            graph = CircuitGraph(structured_data, abstraction_level)
            
            if ctx:
                await ctx.report_progress(80, 100)
                ctx.info(f"Finding path from {start_component} to {end_component}...")
                
            path_result = graph.find_path(start_component, end_component,  max_depth)
            
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
                "abstraction_level": abstraction_level,
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
    async def analyze_functional_block(schematic_path: str, center_component: str,  ctx: Context | None,
                                    radius: int = 2) -> Dict:
        
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
            if ctx:
                await ctx.report_progress(10, 100)
                ctx.info(f"Parsing netlist from: {os.path.basename(schematic_path)}")
                
            parser = NetlistParser(schematic_path)
            parser.export_netlist()
            
            if ctx:
                await ctx.report_progress(40, 100)
                ctx.info("Structuring netlist data...")
                
            structured_data = parser.structure_data()
            
            if not structured_data:
                if ctx:
                    ctx.info("Failed to structure netlist data")
                return {"success": False, "error": "Failed to structure netlist data"}
            
            if ctx:
                await ctx.report_progress(60, 100)
                ctx.info("Building circuit graph...")
                
            graph = CircuitGraph(structured_data)
            
            if ctx:
                await ctx.report_progress(80, 100)
                ctx.info(f"Finding path from neighbors {center_component}...")
                
            path_result = graph.get_neighborhood(center_component, radius)
            
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
    async def parse_netlist(schematic_path: str, ctx: Context | None) -> Dict[str, Any]:
        """Parse a KiCad schematic and return a basic netlist summary.
        
        Args:
            schematic_path: Path to the KiCad schematic file (.kicad_sch)
            ctx: MCP context for progress reporting
            
        Returns:
            Dictionary with basic component and net counts
        """
        try:
            if not schematic_path.endswith('.kicad_sch'):
                return {"success": False, "error": "Invalid file type. Expected .kicad_sch file"}
            
            if not os.path.exists(schematic_path):
                return {"success": False, "error": f"Schematic file not found: {schematic_path}"}
            
            parser = NetlistParser(schematic_path)
            parser.export_netlist()
            structured_data = parser.structure_data()
            
            if not structured_data:
                return {"success": False, "error": "Failed to structure netlist data"}
            
            components = structured_data.get('components', {})
            nets = structured_data.get('nets', {})
            
            return {
                "success": True,
                "total_components": len(components),
                "total_nets": len(nets),
                "components": list(components.keys())
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
                





        
