"""
Netlist extraction and analysis tools for KiCad schematics.
"""
import os
from typing import Dict, Any
from mcp.server.fastmcp import FastMCP, Context

from kicad_mcp.utils.file_utils import get_project_files
from kicad_mcp.utils.netlist_parser import extract_netlist, analyze_netlist

def register_netlist_tools(mcp: FastMCP) -> None:
    """Register netlist-related tools with the MCP server.
    
    Args:
        mcp: The FastMCP server instance
    """
    
    @mcp.tool()
    async def extract_schematic_netlist(schematic_path: str, ctx: Context | None) -> Dict[str, Any]:
        """Extract netlist information from a KiCad schematic.
        
        This tool parses a KiCad schematic file and extracts comprehensive
        netlist information including components, connections, and labels.
        
        Args:
            schematic_path: Path to the KiCad schematic file (.kicad_sch)
            ctx: MCP context for progress reporting
            
        Returns:
            Dictionary with netlist information
        """
        print(f"Extracting netlist from schematic: {schematic_path}")
        
        if not os.path.exists(schematic_path):
            print(f"Schematic file not found: {schematic_path}")
            ctx.info(f"Schematic file not found: {schematic_path}")
            return {"success": False, "error": f"Schematic file not found: {schematic_path}"}
        
        # Report progress
        if ctx:
            await ctx.report_progress(10, 100)
            ctx.info(f"Loading schematic file: {os.path.basename(schematic_path)}")
        
        # Extract netlist information
        try:
            if ctx:
                await ctx.report_progress(20, 100)
                ctx.info("Parsing schematic structure...")
            
            netlist_data = extract_netlist(schematic_path)
            
            if "error" in netlist_data:
                print(f"Error extracting netlist: {netlist_data['error']}")
                ctx.info(f"Error extracting netlist: {netlist_data['error']}")
                return {"success": False, "error": netlist_data['error']}
            
            if ctx:
                await ctx.report_progress(60, 100)
                ctx.info(f"Extracted {netlist_data['component_count']} components and {netlist_data['net_count']} nets")
            
            # Analyze the netlist
            if ctx:
                await ctx.report_progress(70, 100)
                ctx.info("Analyzing netlist data...")
            
            analysis_results = analyze_netlist(netlist_data)
            
            if ctx:
                await ctx.report_progress(90, 100)
            
            # Build result
            result = {
                "success": True,
                "schematic_path": schematic_path,
                "component_count": netlist_data["component_count"],
                "net_count": netlist_data["net_count"],
                "components": netlist_data["components"],
                "nets": netlist_data["nets"],
                "analysis": analysis_results
            }
            
            # Complete progress
            if ctx:
                await ctx.report_progress(100, 100)
                ctx.info("Netlist extraction complete")
            
            return result
            
        except Exception as e:
            print(f"Error extracting netlist: {str(e)}")
            ctx.info(f"Error extracting netlist: {str(e)}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    async def extract_project_netlist(project_path: str, ctx: Context | None) -> Dict[str, Any]:
        """Extract netlist from a KiCad project's schematic.
        
        This tool finds the schematic associated with a KiCad project
        and extracts its netlist information.
        
        Args:
            project_path: Path to the KiCad project file (.kicad_pro)
            ctx: MCP context for progress reporting
            
        Returns:
            Dictionary with netlist information
        """
        
        if not os.path.exists(project_path):
            print(f"Project not found: {project_path}")
            if ctx:
                ctx.info(f"Project not found: {project_path}")
            return {"success": False, "error": f"Project not found: {project_path}"}
        
        # Report progress
        if ctx:
            await ctx.report_progress(10, 100)
        
        # Get the schematic file
        try:
            files = get_project_files(project_path)
            
            if "schematic" not in files:
                print("Schematic file not found in project")
                if ctx:
                    ctx.info("Schematic file not found in project")
                return {"success": False, "error": "Schematic file not found in project"}
            
            schematic_paths = files["schematic"]

            if isinstance(schematic_paths, str):
                schematic_paths = [schematic_paths]

            all_components = {}
            all_nets = {}

            for schematic_path in schematic_paths:
                if ctx:
                    ctx.info(f"Processing: {os.path.basename(schematic_path)}")
                result = await extract_schematic_netlist(schematic_path, ctx)

                if not result.get("success"):
                    if ctx:
                        ctx.info(f"Error extracting netlist from {schematic_path}: {result.get('error', 'Unknown error')}")
                    return {"success": False, "error": f"Failed to extract netlist from {schematic_path}: {result.get('error')}"}

                for ref, comp in result.get("components", {}).items():
                    if ref not in all_components:
                        all_components[ref] = comp
                    else:
                        if ctx:
                            ctx.info(f"Duplicate component reference '{ref}' found in multiple schematics. Using first occurrence.")

                # Merge nets
                for net_name, pins in result.get("nets", {}).items():
                    if net_name not in all_nets:
                        all_nets[net_name] = pins
                    else:
                        all_nets[net_name].extend(pins)

            if ctx:
                await ctx.report_progress(100, 100)

            return {
                "success": True,
                "project_path": project_path,
                "components": all_components,
                "nets": all_nets
            }
            
        except Exception as e:
            ctx.info(f"Error extracting project netlist: {str(e)}")
            return {"success": False, "error": str(e)}

            
        except Exception as e:
            print(f"Error extracting project netlist: {str(e)}")
            ctx.info(f"Error extracting project netlist: {str(e)}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    async def analyze_schematic_connections(schematic_path: str, ctx: Context | None) -> Dict[str, Any]:
        """Analyze connections in a KiCad schematic.
        
        This tool provides detailed analysis of component connections,
        including power nets, signal paths, and potential issues.
        
        Args:
            schematic_path: Path to the KiCad schematic file (.kicad_sch)
            ctx: MCP context for progress reporting
            
        Returns:
            Dictionary with connection analysis
        """
        
        if not os.path.exists(schematic_path):
            print(f"Schematic file not found: {schematic_path}")
            if ctx:
                ctx.info(f"Schematic file not found: {schematic_path}")
            return {"success": False, "error": f"Schematic file not found: {schematic_path}"}
        
        # Report progress
        if ctx:
            await ctx.report_progress(10, 100)
            ctx.info(f"Extracting netlist from: {os.path.basename(schematic_path)}")
        
        # Extract netlist information
        try:
            netlist_data = extract_netlist(schematic_path)
            
            if "error" in netlist_data:
                print(f"Error extracting netlist: {netlist_data['error']}")
                if ctx:
                    ctx.info(f"Error extracting netlist: {netlist_data['error']}")
                return {"success": False, "error": netlist_data['error']}
            
            if ctx:
                await ctx.report_progress(40, 100)
            
            # Advanced connection analysis
            if ctx:
                ctx.info("Performing connection analysis...")
            
            analysis = {
                "component_count": netlist_data["component_count"],
                "net_count": netlist_data["net_count"],
                "component_types": {},
                "power_nets": [],
                "signal_nets": [],
                "potential_issues": []
            }
            
            # Analyze component types
            components = netlist_data.get("components", {})
            for ref, component in components.items():
                # Extract component type from reference (e.g., R1 -> R)
                import re
                comp_type_match = re.match(r'^([A-Za-z_]+)', ref)
                if comp_type_match:
                    comp_type = comp_type_match.group(1)
                    if comp_type not in analysis["component_types"]:
                        analysis["component_types"][comp_type] = 0
                    analysis["component_types"][comp_type] += 1
            
            if ctx:
                await ctx.report_progress(60, 100)
            
            # Identify power nets
            nets = netlist_data.get("nets", {})
            for net_name, pins in nets.items():
                if any(net_name.startswith(prefix) for prefix in ["VCC", "VDD", "GND", "+5V", "+3V3", "+12V"]):
                    analysis["power_nets"].append({
                        "name": net_name,
                        "pin_count": len(pins)
                    })
                else:
                    analysis["signal_nets"].append({
                        "name": net_name,
                        "pin_count": len(pins)
                    })
            
            if ctx:
                await ctx.report_progress(80, 100)
            
            # Check for potential issues
            # 1. Nets with only one connection (floating)
            for net_name, pins in nets.items():
                if len(pins) <= 1 and not any(net_name.startswith(prefix) for prefix in ["VCC", "VDD", "GND", "+5V", "+3V3", "+12V"]):
                    analysis["potential_issues"].append({
                        "type": "floating_net",
                        "net": net_name,
                        "description": f"Net '{net_name}' appears to be floating (only has {len(pins)} connection)"
                    })
            
            # 2. Power pins without connections
            # This would require more detailed parsing of the schematic
            
            if ctx:
                await ctx.report_progress(90, 100)
            
            # Build result
            result = {
                "success": True,
                "schematic_path": schematic_path,
                "analysis": analysis
            }
            
            # Complete progress
            if ctx:
                await ctx.report_progress(100, 100)
                ctx.info("Connection analysis complete")
            
            return result
            
        except Exception as e:
            print(f"Error analyzing connections: {str(e)}")
            ctx.info(f"Error analyzing connections: {str(e)}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    async def find_component_connections(project_path: str, component_ref: str, ctx: Context) -> Dict[str, Any]:
        """Find all connections for a specific component in a KiCad project.
        
        This tool extracts information about how a specific component
        is connected to other components in the schematic.
        
        Args:
            project_path: Path to the KiCad project file (.kicad_pro)
            component_ref: Component reference (e.g., "R1", "U3")
            ctx: MCP context for progress reporting
            
        Returns:
            Dictionary with component connection information
        """
        
        if not os.path.exists(project_path):
            if ctx:
                ctx.info(f"Project not found: {project_path}")
            return {"success": False, "error": f"Project not found: {project_path}"}
        
        # Report progress
        await ctx.report_progress(10, 100)
        
        # Get the schematic file
        try:
            files = get_project_files(project_path)
            
            if "schematic" not in files:
                if ctx:
                    ctx.info("Schematic file not found in project")
                return {"success": False, "error": "Schematic file not found in project"}
            
            schematic_paths = files["schematic"]
            
            if isinstance(schematic_paths, str):
                schematic_paths = [schematic_paths]

            found = False
            result = {}

        
            # Extract netlist
            if ctx:
                await ctx.report_progress(30, 100)
                ctx.info(f"Extracting netlist to find connections for {component_ref}...")
                
            netlist_data = []
            for schematic_path in schematic_paths:
                netlist = extract_netlist(schematic_path)
            
                if "error" in netlist:
                    if ctx:
                        ctx.info(f"Failed to extract netlist: {netlist['error']}")
                    return {"success": False, "error": netlist['error']}
            
                # Check if component exists in the netlist
                components = netlist.get("components", {})
                if component_ref not in components:
                    continue
            
                # Get component information
                found = True
                component_info = components[component_ref]
                nets = netlist.get("nets", {})
                connections = []
                connected_nets = []
                
                # Find connections
                if ctx:
                    await ctx.report_progress(50, 100)
                    ctx.info("Finding connections...")
            

                for net_name, pins in nets.items():
                    # Check if any pin belongs to our component
                    component_pins = []
                    for pin in pins:
                        if pin.get('component') == component_ref:
                            component_pins.append(pin)
                        
                    if component_pins:
                        # This net has connections to our component
                        net_connections = []
                        
                        for pin in component_pins:
                            pin_num = pin.get('pin', 'Unknown')
                            # Find other components connected to this pin
                            connected_components = [
                                {
                                    "component": other_pin.get('component'),
                                    "pin": other_pin.get('pin', 'Unknown')
                                }
                                for other_pin in pins
                                if other_pin.get('component') and other_pin.get('component') != component_ref
                            ]
                            
                            net_connections.append({
                                "pin": pin_num,
                                "net": net_name,
                                "connected_to": connected_components
                            })
                        
                        connections.extend(net_connections)
                        connected_nets.append(net_name)
            
                # Analyze the connections
                if ctx:
                    await ctx.report_progress(70, 100)
                    ctx.info("Analyzing connections...")
            
                # Categorize connections by pin function (if possible)
                pin_functions = {}
                if "pins" in component_info:
                    for pin in component_info["pins"]:
                        pin_num = pin.get('num')
                        pin_name = pin.get('name', '')
                        
                        # Try to categorize based on pin name
                        pin_type = "unknown"
                        
                        if any(power_term in pin_name.upper() for power_term in ["VCC", "VDD", "VEE", "VSS", "GND", "PWR", "POWER"]):
                            pin_type = "power"
                        elif any(io_term in pin_name.upper() for io_term in ["IO", "I/O", "GPIO"]):
                            pin_type = "io"
                        elif any(input_term in pin_name.upper() for input_term in ["IN", "INPUT"]):
                            pin_type = "input"
                        elif any(output_term in pin_name.upper() for output_term in ["OUT", "OUTPUT"]):
                            pin_type = "output"
                        
                        pin_functions[pin_num] = {
                            "name": pin_name,
                            "type": pin_type
                        }
                
                # Build result
                result = {
                    "success": True,
                    "project_path": project_path,
                    "schematic_path": schematic_path,
                    "component": component_ref,
                    "component_info": component_info,
                    "connections": connections,
                    "connected_nets": connected_nets,
                    "pin_functions": pin_functions,
                    "total_connections": len(connections)
                }
                
                if ctx:
                    await ctx.report_progress(100, 100)
                    ctx.info(f"Found {len(connections)} connections for component {component_ref}")
                    
                break

            if not found:
                # Collect all available components to assist debugging
                all_components = []
                for schematic_path in schematic_paths:
                    netlist_data = extract_netlist(schematic_path)
                    all_components.extend(netlist_data.get("components", {}).keys())

                return {
                    "success": False,
                    "error": f"Component {component_ref} not found in any schematic",
                    "available_components": sorted(set(all_components))
                }

            return result

        except Exception as e:
            if ctx:
                ctx.info(f"Error finding component connections: {str(e)}")
            return {"success": False, "error": str(e)}