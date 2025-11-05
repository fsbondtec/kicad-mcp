"""
Circuit pattern recognition tools for KiCad schematics.
"""
import os
from typing import Dict, List, Any, Optional
from mcp.server.fastmcp import FastMCP, Context
import logging

from kicad_mcp.utils.file_utils import get_project_files
from kicad_mcp.utils.netlist_parser import extract_netlist, analyze_netlist
from kicad_mcp.utils.pattern_recognition import (
    identify_power_supplies,
    identify_amplifiers,
    identify_filters,
    identify_oscillators,
    identify_digital_interfaces,
    identify_microcontrollers,
    identify_sensor_interfaces
)

def register_pattern_tools(mcp: FastMCP) -> None:
    """Register circuit pattern recognition tools with the MCP server.
    
    Args:
        mcp: The FastMCP server instance
    """
    
    @mcp.tool()
    async def identify_circuit_patterns(schematic_path: str, ctx: Context | None) -> Dict[str, Any]:
        """Identify common circuit patterns in a KiCad schematic.
        
        This tool analyzes a schematic to recognize common circuit blocks such as:
        - Power supply circuits (linear regulators, switching converters)
        - Amplifier circuits (op-amps, transistor amplifiers)
        - Filter circuits (RC, LC, active filters)
        - Digital interfaces (I2C, SPI, UART)
        - Microcontroller circuits
        - And more
        
        Args:
            schematic_path: Path to the KiCad schematic file (.kicad_sch)
            ctx: MCP context for progress reporting
            
        Returns:
            Dictionary with identified circuit patterns
        """
        if not os.path.exists(schematic_path):
            if ctx:
                ctx.info(f"Schematic file not found: {schematic_path}")
            return {"success": False, "error": f"Schematic file not found: {schematic_path}"}
        
        # Report progress
        if ctx:
            await ctx.report_progress(10, 100)
            ctx.info(f"Loading schematic file: {os.path.basename(schematic_path)}")
        
        try:
            # Extract netlist information
            if ctx:
                await ctx.report_progress(20, 100)
                ctx.info("Parsing schematic structure...")
            
            netlist_data = extract_netlist(schematic_path)
            logging.debug("Extracted Netlist")
            
            if "error" in netlist_data:
                if ctx:
                    ctx.info(f"Error extracting netlist: {netlist_data['error']}")
                return {"success": False, "error": netlist_data['error']}
            
            # Analyze components and nets
            if ctx:
                await ctx.report_progress(30, 100)
                ctx.info("Analyzing components and connections...")
            
            components = netlist_data.get("components", {})
            nets = netlist_data.get("nets", {})
            
            # Start pattern recognition
            if ctx:
                await ctx.report_progress(50, 100)
                ctx.info("Identifying circuit patterns...")
            
            identified_patterns = {
                "power_supply_circuits": [],
                "amplifier_circuits": [],
                "filter_circuits": [],
                "oscillator_circuits": [],
                "digital_interface_circuits": [],
                "microcontroller_circuits": [],
                "sensor_interface_circuits": [],
                "other_patterns": []
            }

            logging.debug("After identified patterns")
            
            # Identify power supply circuits
            if ctx:
                await ctx.report_progress(60, 100)
            identified_patterns["power_supply_circuits"] = identify_power_supplies(components, nets)
            
            # Identify amplifier circuits
            if ctx:
                await ctx.report_progress(70, 100)
            identified_patterns["amplifier_circuits"] = identify_amplifiers(components, nets)
            
            # Identify filter circuits
            if ctx:
                await ctx.report_progress(75, 100)
            identified_patterns["filter_circuits"] = identify_filters(components, nets)
            
            # Identify oscillator circuits
            if ctx:
                await ctx.report_progress(80, 100)
            identified_patterns["oscillator_circuits"] = identify_oscillators(components, nets)
            
            # Identify digital interface circuits
            if ctx:
                await ctx.report_progress(85, 100)
            identified_patterns["digital_interface_circuits"] = identify_digital_interfaces(components, nets)
            
            # Identify microcontroller circuits
            if ctx:
                await ctx.report_progress(90, 100)
            identified_patterns["microcontroller_circuits"] = identify_microcontrollers(components)
            
            # Identify sensor interface circuits
            if ctx:
                await ctx.report_progress(95, 100)
            identified_patterns["sensor_interface_circuits"] = identify_sensor_interfaces(components, nets)
            
            # Build result
            result = {
                "success": True,
                "schematic_path": schematic_path,
                "component_count": netlist_data["component_count"],
                "identified_patterns": identified_patterns
            }
            
            # Count total patterns
            total_patterns = sum(len(patterns) for patterns in identified_patterns.values())
            result["total_patterns_found"] = total_patterns
            
            # Complete progress
            if ctx:
                await ctx.report_progress(100, 100)
                ctx.info(f"Pattern recognition complete. Found {total_patterns} circuit patterns.")
            
            return result
            
        except Exception as e:
            if ctx:
                ctx.info(f"Error identifying circuit patterns: {str(e)}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    async def analyze_project_circuit_patterns(project_path: str, ctx: Context | None) -> Dict[str, Any]:
        """Identify circuit patterns in a KiCad project's schematic.
        
        Args:
            project_path: Path to the KiCad project file (.kicad_pro)
            ctx: MCP context for progress reporting
            
        Returns:
            Dictionary with identified circuit patterns
        """
        if not os.path.exists(project_path):
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
                if ctx:
                    ctx.info("Schematic file not found in project")
                return {"success": False, "error": "Schematic file not found in project"}
            
            # if project has Hierarchical Sheets in kicad
            schematic_paths = files["schematic"] 
            if isinstance(schematic_paths, str):
                schematic_paths = [schematic_paths]

            all_patterns = []
            failed_files = []

            if ctx:
                await ctx.report_progress(20, 100)
                ctx.info(f"Analyzing circuit patterns from {len(schematic_paths)} schematic file(s)...")

            for schematic_path in schematic_paths:
                if ctx:
                    ctx.info(f"Processing: {os.path.basename(schematic_path)}")

                try:
                    result = await identify_circuit_patterns(schematic_path, ctx)

                    if result.get("success"):
                        pattern_groups = result.get("identified_patterns", {})
                        for category, patterns in pattern_groups.items():
                            for pattern in patterns:
                                pattern["category"] = category
                                pattern["source_schematic"] = os.path.basename(schematic_path)
                                all_patterns.append(pattern)
                    else:
                        failed_files.append({
                            "schematic": os.path.basename(schematic_path),
                            "error": result.get("error", "Unknown error")
                        })

                except Exception as sub_e:
                    failed_files.append({
                        "schematic": os.path.basename(schematic_path),
                        "error": str(sub_e)
                    })

            await ctx.report_progress(100, 100)

            return {
                "success": True,
                "project_path": project_path,
                "patterns": all_patterns,
                "failed_schematics": failed_files,
                "total_patterns_found": len(all_patterns)
            }

            
        except Exception as e:
            ctx.info(f"Error analyzing project circuit patterns: {str(e)}")
            return {"success": False, "error": str(e)}
