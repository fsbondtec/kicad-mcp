import sexpdata
import os
import sys
import subprocess
import tempfile

from kicad_mcp.utils.cli_drc import find_kicad_cli

def sexp_children(node, tag):
    """Return every child of `node` whose head symbol equals `tag`."""
    if not isinstance(node, list):
        return []
    return [
        child
        for child in node[1:]
        if isinstance(child, list) and child and isinstance(child[0], sexpdata.Symbol) and str(child[0]) == tag
    ]

def sexp_child(node, tag):
    """Return the first child of `node` whose head symbol equals `tag`, or None."""
    matches = sexp_children(node, tag)
    return matches[0] if matches else None


def sexp_value(node):
    """Extract the value of a (tag "value") node as a string, or None."""
    if node is None or len(node) < 2:
        return None
    val = node[1]
    return str(val) if isinstance(val, sexpdata.Symbol) else val


class NetlistParser:
    """
    Exports a schematic's netlist via kicad-cli and parses it into components and nets
    """

    def __init__(self, schematic_path: str):
        self.components = {}
        self.nets = {}
        self.schematic_path = schematic_path
        self.netlist = None

    def export_netlist(self):
        """
        Exports the schematic to a temporary KiCad s-expression netlist file
        """
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                output_file = os.path.join(temp_dir, "netlist.net")

                kicad_cli = find_kicad_cli()
                if not kicad_cli:
                    raise FileNotFoundError(
                        "kicad-cli not found. Ensure KiCad 9.0+ is installed and in PATH."
                    )

                cmd = [
                    kicad_cli,
                    "sch",
                    "export",
                    "netlist",
                    "--format",
                    "kicadsexpr",
                    "--output",
                    output_file,
                    self.schematic_path,
                ]

                process = subprocess.run(cmd, capture_output=True, text=True)

                if process.returncode != 0:
                    print(f"Netlist export failed: {process.stderr.strip()}", file=sys.stderr)

                if os.path.exists(output_file):
                    with open(output_file, "r", encoding="latin-1") as f:
                        self.netlist = f.read()
                else:
                    print("Output file does not exist", file=sys.stderr)

        except Exception as e:
            print(f"Error during netlist export: {str(e)}", file=sys.stderr)

    def structure_data(self):
        """
        Converts the raw netlist s-expression tree into component and net dictionaries, dropping unconnected nets.
        """
        if not self.netlist:
            return {"components": self.components, "nets": self.nets}

        tree = sexpdata.loads(self.netlist)

        components_node = sexp_child(tree, "components")
        if components_node:
            for comp in sexp_children(components_node, "comp"):
                ref = sexp_value(sexp_child(comp, "ref"))
                value = sexp_value(sexp_child(comp, "value"))

                libsource = sexp_child(comp, "libsource")
                lib = sexp_value(sexp_child(libsource, "lib")) if libsource else None
                part = sexp_value(sexp_child(libsource, "part")) if libsource else None
                desc = sexp_value(sexp_child(libsource, "description")) if libsource else None

                # collect simulation fields (properties named "Sim.*"), e.g. Sim.Device
                sim_fields = {} 
                for prop in sexp_children(comp, "property"):
                    prop_name = sexp_value(sexp_child(prop, "name"))
                    if prop_name and prop_name.startswith("Sim."):
                        sim_fields[prop_name] = sexp_value(sexp_child(prop, "value"))

                self.components[ref] = {
                    "lib_id": f"{lib}:{part}" if lib and part else None,
                    "value": value,
                    "description": desc,
                    "name": part,
                    "sim_fields": sim_fields,
                }

        nets_node = sexp_child(tree, "nets")
        if nets_node:
            for net in sexp_children(nets_node, "net"):
                name = sexp_value(sexp_child(net, "name"))

                if not name or "unconnected" in name:
                    continue

                net_pins = [
                    {
                        "component": sexp_value(sexp_child(node, "ref")),
                        "pin": sexp_value(sexp_child(node, "pin")),
                        "pinfunction": sexp_value(sexp_child(node, "pinfunction")),
                        "electrical_type": sexp_value(sexp_child(node, "pintype")),
                    }
                    for node in sexp_children(net, "node")
                ]

                self.nets[name] = net_pins

       
        return {"components": self.components, "nets": self.nets}
