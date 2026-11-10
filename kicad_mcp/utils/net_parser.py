import sexpdata
import sys

from kicad_mcp.utils.cli_drc import export_netlist

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
        """Export the schematic as KiCad s-expression netlist into self.netlist."""
        self.netlist, error = export_netlist(self.schematic_path, "kicadsexpr")
        if error:
            print(f"Netlist export: {error}", file=sys.stderr)

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

                self.components[ref] = {
                    "lib_id": f"{lib}:{part}" if lib and part else None,
                    "value": value,
                    "description": desc,
                    "name": part,
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
