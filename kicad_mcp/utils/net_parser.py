from kinparse import parse_netlist
import os
from typing import Any, Dict, List
from collections import defaultdict
import subprocess
import tempfile

from kicad_mcp.utils.cli_drc import find_kicad_cli

class NetlistParser:
    def __init__(self, schematic_path: str):
        self.components = {}
        self.nets = {}
        self.schematic_path = schematic_path
        self.netlist = None

    def export_netlist(self):
        try:
            #temporary directory for output
            with tempfile.TemporaryDirectory() as temp_dir:

                output_ext = ".net" #standard output, kinparse works with .net
                
                output_file = os.path.join(temp_dir, f"netlist{output_ext}")

                kicad_cli = find_kicad_cli()
                if not kicad_cli:
                    raise FileNotFoundError("kicad-cli not found. Ensure KiCad 9.0+ is installed and in PATH.")
                
                cmd = [
                    kicad_cli,
                    "sch", "export", "netlist",
                    "--format", "kicadsexpr",
                    "--output", output_file,
                    self.schematic_path
                ]

                process = subprocess.run(cmd, capture_output=True, text=True)

                if process.returncode != 0:
                    print(f"Netlist export failed: {process.stderr.strip()}")

                if not os.path.exists(output_file):
                    print(f"Netlist file not created: {output_file}")

                if output_file and os.path.exists(output_file):
                    with open(output_file, 'r') as f:
                        self.netlist = f.read()
                else:
                    print("Output file does not exist")
        
        except Exception as e:
            print(f"Error during netlist export: {str(e)}")


    def structure_data(self): 
        nlst = parse_netlist(self.netlist)     
        for part in nlst.parts:
            component_data = {
                "lib_id": f"{part.lib}:{part.name}",
                "value": part.value,
                "description": part.desc,
                "name": part.name,
            }
            
            self.components[part.ref] = component_data

        for net in nlst.nets:
            net_pins = []
            
            #filter not connected nets
            if "unconnected" not in net.name:
                for pin in net.pins:
                    net_pins.append({
                        "component": pin.ref,
                        "pin": pin.num,
                        "electrical_type": pin.type
                    })
                
                self.nets[net.name] = net_pins

        return {
            "components": self.components,
            "nets": self.nets
        }
        
    
        

            
            

            




