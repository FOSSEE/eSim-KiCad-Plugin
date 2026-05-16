import networkx as nx
try:
    from .topology_builder import TopologyBuilder
except:
    from topology_builder import TopologyBuilder
    
class DesignAnalyzer:
    def __init__(self, components: list, graph: nx.Graph, wires, pin_positions: dict = None):
        self.components    = components
        self.graph         = graph
        self.wires         = wires
        self.pin_positions = pin_positions or {}

        # Need a model, but model is well-known/standard
        # KiCad ships .lib files for these
        self.STANDARD_MODELS = {"Device:D", "Device:LED", "Device:Zener",
                        "Device:BJT_NPN", "Device:BJT_PNP",
                        "Device:NMOS", "Device:PMOS"}

        # Need explicit subcircuit — must have Sim.Device
        self.COMPLEX = {"Device:Opamp", "Device:Opamp_Dual"}

        #  Never simulate
        self.NON_ELECTRICAL = {"Mechanical:MountingHole", "Device:TestPoint",
                        "power:PWR_FLAG"}



    def check_missing_values(self) -> list:
        """Return list of components that have no value or an empty value."""
        issues = []
        for comp in self.components:
            ref = comp.get("ref", "<unknown>")
            val = comp.get("value", "").strip()
            if not val:
                issues.append({
                    "ref": ref,
                    "type": comp.get("type", ""),
                    "issue": "Missing value"
                })
        return issues
 
    def check_missing_refs(self) -> list:
        """Return list of components whose reference starts with '?' (unassigned)."""
        issues = []
        for comp in self.components:
            ref = comp.get("ref", "")
            if ref.startswith("?") or ref == "":
                issues.append({
                    "ref": ref or "<blank>",
                    "type": comp.get("type", ""),
                    "issue": "Unassigned reference"
                })
        return issues
    
    def check_spice_models(self) -> dict:
        result = {
            "executable":     [],
            "incomplete":     [],
            "non_executable": [],
            "non_sim":        []
        }

        for comp in self.components:
            ref      = comp.get("ref", "<unknown>")
            lib_type = comp.get("type", "")
            value    = comp.get("value", "")
            sim_keys = [k for k in comp if k.startswith("Sim.")]

            # 1. Non-electrical
            if lib_type in self.NON_ELECTRICAL:
                result["non_sim"].append({"ref": ref, "type": lib_type})
                continue

            # 2. Passives — just need a value
            if lib_type in {"Device:R", "Device:C", "Device:L"}:
                if value:
                    result["executable"].append({"ref": ref, "type": lib_type})
                else:
                    result["incomplete"].append({
                        "ref": ref, "type": lib_type,
                        "issue": "Missing value"
                    })
                continue

            # 3. Sources — need value AND Sim.Type
            if lib_type in {"Device:Battery", "Device:Voltage_Source", "Device:Current_Source"}:
                if value and "Sim.Type" in comp:
                    result["executable"].append({"ref": ref, "type": lib_type})
                else:
                    result["incomplete"].append({
                        "ref": ref, "type": lib_type,
                        "issue": "Missing value" if not value else "Missing Sim.Type"
                    })
                continue

            # 4. Standard models — need Sim.Device + Sim.Pins
            if lib_type in self.STANDARD_MODELS:
                if "Sim.Device" in comp and "Sim.Pins" in comp:
                    result["executable"].append({"ref": ref, "type": lib_type})
                elif "Sim.Device" in comp:
                    result["incomplete"].append({
                        "ref": ref, "type": lib_type,
                        "issue": "Sim.Device present but Sim.Pins missing"
                    })
                else:
                    result["incomplete"].append({
                        "ref": ref, "type": lib_type,
                        "issue": "No model specified"
                    })
                continue

            # 5. Complex — need Sim.Device (subcircuit)
            if lib_type in self.COMPLEX:
                if "Sim.Device" in comp:
                    result["executable"].append({"ref": ref, "type": lib_type})
                else:
                    result["non_executable"].append({
                        "ref": ref, "type": lib_type,
                        "issue": "Missing subcircuit"
                    })
                continue

            # 6. Fallback — unknown type
            if "Sim.Device" in comp:
                result["executable"].append({"ref": ref, "type": lib_type})
            elif sim_keys:
                result["incomplete"].append({
                    "ref": ref, "type": lib_type,
                    "issue": "Partial Sim.* keys found",
                    "sim_keys_found": sim_keys
                })
            else:
                result["non_executable"].append({
                    "ref": ref, "type": lib_type,
                    "issue": "Unknown type, no Sim.* properties"
                })

        return result
    

    def find_dangling_nets(self, graph):
        issues = []

        for node, data in graph.nodes(data=True):
            if data.get("type") == "net":

                neighbors = list(graph.neighbors(node))
                pin_neighbors = [n for n in neighbors if "_" in n]
                degree = len(pin_neighbors)

                if degree == 0:
                    issues.append({
                        "net": node,
                        "issue": "Floating net (no pins connected)"
                    })

                elif degree == 1:
                    issues.append({
                        "net": node,
                        "connected_pin": pin_neighbors[0],
                        "issue": "Dangling net (only one pin connected)"
                    })

        return issues

    #   ERC 

    def erc_unconnected_pins(self):

        issues = []

        for node in self.graph.nodes:

            if "_" in node:  # pin node

                if self.graph.degree(node) == 0:

                    comp, pin = node.split("_",1)

                    issues.append({
                        "ref": comp,
                        "pin": pin,
                        "issue": "Unconnected pin",
                        "severity": "error"
                    })

        return issues

    def erc_duplicate_refs(self) -> list:
        """Flag any reference designator that appears more than once."""
        seen, dupes = {}, []
        for comp in self.components:
            ref = comp.get("ref", "")
            if ref in seen:
                dupes.append(
                    {"ref": ref, 
                     "type": comp.get("type", ""), 
                     "issue": "Duplicate reference",
                     "severity": "error"
                    }
                )
            else:
                seen[ref] = True
        return dupes

    def erc_no_power_symbol(self):
        has_power = any(
            comp.get("type", "").startswith("power:") or
            comp.get("type", "") in {"Device:Battery", "Device:Voltage_Source", "Device:Current_Source"} or
            comp.get("Sim.Device", "") == "V"
            for comp in self.components
        )
        if not has_power:
            return [{
                "issue": "No ground/reference node (floating circuit)",
                "severity": "warning"
            }]
        return []


    def da_report(self):
        """Returns dict of Design + ERC report."""
        erc_issues = (
            self.erc_unconnected_pins() +
            self.erc_duplicate_refs() +
            self.erc_no_power_symbol()
        )
        
        return {
            "missing_values": self.check_missing_values(),
            "missing_refs":   self.check_missing_refs(),
            "spice_coverage": self.check_spice_models(),
            "dangling_nets":  self.find_dangling_nets(self.graph),
            "erc": {
                "errors": [i for i in erc_issues if i["severity"] == "error"],
                "warnings": [i for i in erc_issues if i["severity"] == "warning"],
                "info": [i for i in erc_issues if i.get("severity") == "info"]
            }      
        }
    






# import networkx as nx
# from .topology_builder import TopologyBuilder
# class DesignAnalyzer:
#     """
#     Runs sanity checks on extracted schematic data.
#     Consumes: components (list of dicts), graph (nx.Graph)
#     Produces: a structured report dict ready for the Report Generator
#     """
 
#     def __init__(self, components: list, graph: nx.Graph,wires):
#         self.components = components
#         self.graph = graph
#         self.wires = wires
 
#     def check_missing_values(self) -> list:
#         """Return list of components that have no value or an empty value."""
#         issues = []
#         for comp in self.components:
#             ref = comp.get("ref", "<unknown>")
#             val = comp.get("value", "").strip()
#             if not val:
#                 issues.append({
#                     "ref": ref,
#                     "type": comp.get("type", ""),
#                     "issue": "Missing value"
#                 })
#         return issues
 
#     def check_missing_refs(self) -> list:
#         """Return list of components whose reference starts with '?' (unassigned)."""
#         issues = []
#         for comp in self.components:
#             ref = comp.get("ref", "")
#             if ref.startswith("?") or ref == "":
#                 issues.append({
#                     "ref": ref or "<blank>",
#                     "type": comp.get("type", ""),
#                     "issue": "Unassigned reference"
#                 })
#         return issues
 

#     def check_spice_models(self) -> dict:
#         """
#         Classify every component as:
#           - 'full'    : has Sim.Device  (ready for simulation)
#           - 'partial' : has some Sim.* keys but not Sim.Device
#           - 'missing' : no Sim.* keys at all
#         Returns a dict with three lists.
#         """
#         result = {"full": [], "partial": [], "missing": []}
 
#         for comp in self.components:
#             ref = comp.get("ref", "<unknown>")
#             sim_keys = [k for k in comp if k.startswith("Sim.")]
 
#             if "Sim.Device" in comp:
#                 result["full"].append({
#                     "ref": ref,
#                     "type": comp.get("type", ""),
#                     "sim_device": comp.get("Sim.Device"),
#                     "sim_type": comp.get("Sim.Type", ""),
#                     "sim_pins": comp.get("Sim.Pins", "")
#                 })
#             elif sim_keys:
#                 result["partial"].append({
#                     "ref": ref,
#                     "type": comp.get("type", ""),
#                     "sim_keys_found": sim_keys
#                 })
#             else:
#                 result["missing"].append({
#                     "ref": ref,
#                     "type": comp.get("type", "")
#                 })
 
#         return result
    
#     def find_dangling_nets(self,graph):
#         issues = []
#         for node, data in graph.nodes(data=True):
#             if data.get("type") == "net":

#                 if graph.degree(node) == 1:
#                     issues.append({
#                         "net": node,
#                         "issue": "Dangling net (only one pin connected)"
#                     })

#         return issues
    
#     def da_report(self):
#         '''
#         Returns dict of Design report
#         '''
#         report = {}
#         missing_values = self.check_missing_values()
#         missing_refs   = self.check_missing_refs()
#         spice_coverage = self.check_spice_models()
#         dangling_nets = self.find_dangling_nets(self.graph)

#         report['missing_values'] = missing_values
#         report['missing_refs'] = missing_refs
#         report['spice_coverage'] = spice_coverage
#         report['dangling_nets'] = dangling_nets
#         return report
    
    
'''
def check_spice_models(self) -> dict:
        """
        Classify every component as:
          - 'full'    : has Sim.Device  (ready for simulation)
          - 'partial' : has some Sim.* keys but not Sim.Device
          - 'missing' : no Sim.* keys at all
        """
        result = {"full": [], "partial": [], "missing": []}
        for comp in self.components:
            ref      = comp.get("ref", "<unknown>")
            sim_keys = [k for k in comp if k.startswith("Sim.")]
            if "Sim.Device" in comp:
                result["full"].append({
                    "ref": ref,
                    "type": comp.get("type", ""),
                    "sim_device": comp.get("Sim.Device"),
                    "sim_type":   comp.get("Sim.Type", ""),
                    "sim_pins":   comp.get("Sim.Pins", "")
                })
            elif sim_keys:
                result["partial"].append({
                    "ref": ref,
                    "type": comp.get("type", ""),
                    "sim_keys_found": sim_keys
                })
            else:
                result["missing"].append({
                    "ref": ref,
                    "type": comp.get("type", "")
                })
        return result

'''