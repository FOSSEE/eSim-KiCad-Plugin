import networkx as nx

class TopologyBuilder:

    def __init__(self,components,wires):

        self.components = components
        self.wires = wires

    # def is_point_on_wire(self,point, wire):
    #     (x, y) = point
    #     (x1, y1), (x2, y2) = wire

    #     # horizontal
    #     if y1 == y2 == y:
    #         return min(x1,x2) <= x <= max(x1,x2)

    #     # vertical
    #     if x1 == x2 == x:
    #         return min(y1,y2) <= y <= max(y1,y2)

    #     return False
    def is_point_on_wire(self, point, wire, tol=0.2):
        (x, y) = point
        (x1, y1), (x2, y2) = wire

        # horizontal
        if abs(y1 - y2) < tol and abs(y - y1) < tol:
            return min(x1, x2) - tol <= x <= max(x1, x2) + tol

        # vertical
        if abs(x1 - x2) < tol and abs(x - x1) < tol:
            return min(y1, y2) - tol <= y <= max(y1, y2) + tol

        return False
    
    def build_graph(self, pin_positions):
        G = nx.Graph()

        # Step 1: create nodes
        for pin in pin_positions:
            node = f"{pin['comp']}_{pin['pin']}"
            G.add_node(node)

        # Step 2: create wire graph (IMPORTANT)
        wire_graph = nx.Graph()
        for w in self.wires:
            p1 = tuple(w[0])
            p2 = tuple(w[1])
            wire_graph.add_edge(p1, p2)

        # Step 3: find connected wire groups
        wire_groups = list(nx.connected_components(wire_graph))

        # Build a mapping: wire segment -> which group index it belongs to
        wire_to_group = {}
        wires_list = [(tuple(w[0]), tuple(w[1])) for w in self.wires]

        for idx, group in enumerate(wire_groups):
            for p1, p2 in wires_list:
                if p1 in group or p2 in group:  # both endpoints are in same group by definition
                    wire_to_group[(p1, p2)] = idx

        # Step 4: for each pin, check endpoints AND middle-of-wire
        group_pins = {idx: set() for idx in range(len(wire_groups))}
        
        for pin in pin_positions:
            px, py = pin["pos"]
            pin_node = f"{pin['comp']}_{pin['pin']}"
            matched = False

            # Check endpoint match (original logic)
            for idx, group in enumerate(wire_groups):
                for (x, y) in group:
                    if abs(px - x) < 0.2 and abs(py - y) < 0.2:
                        group_pins[idx].add(pin_node)
                        matched = True
                        break
                if matched:
                    break

            # Check mid-wire match
            if not matched:
                for (p1, p2), idx in wire_to_group.items():
                    if self.is_point_on_wire((px, py), (p1, p2)):
                        group_pins[idx].add(pin_node)
                        break
            
        # Step 5: build net nodes and edges 
        for idx, pins in group_pins.items():
            net_name = f"NET_{idx}"
            G.add_node(net_name, type="net")
            for pin_node in pins:
                G.add_edge(net_name, pin_node)

        return G    
    
    def build_component_graph(self,graph):
        Gc = nx.Graph()
        for node, data in graph.nodes(data=True):

            if data.get("type") == "net":

                connected_pins = list(graph.neighbors(node))

                components = set()

                for pin in connected_pins:
                    comp = pin.split("_")[0]
                    components.add(comp)

                components = list(components)

                for i in range(len(components)):
                    for j in range(i+1, len(components)):
                        Gc.add_edge(components[i], components[j])
        return Gc
    
    # def detect_loop(self,graph):
    #     Gc = self.build_component_graph(graph)
    #     return nx.cycle_basis(Gc)

        # def build_graph(self, pin_positions):

    #     G = nx.Graph()

    #     # Step 1: create nodes
    #     for pin in pin_positions:
    #         node = f"{pin['comp']}_{pin['pin']}"
    #         G.add_node(node)

    #     # Step 2: create wire graph (IMPORTANT)
    #     wire_graph = nx.Graph()
    #     for w in self.wires:
    #         p1 = tuple(w[0])
    #         p2 = tuple(w[1])
    #         wire_graph.add_edge(p1, p2)

    #     # Step 3: find connected wire groups
    #     wire_groups = list(nx.connected_components(wire_graph))

    #     # Step 4: assign pins to wire groups
    #     for idx, group in enumerate(wire_groups):

    #         net_name = f"NET_{idx}"
    #         G.add_node(net_name, type="net")

    #         connected_pins = []

    #         for pin in pin_positions:
    #             px, py = pin["pos"]

    #             for (x, y) in group:
    #                 if abs(px - x) < 0.2 and abs(py - y) < 0.2:
    #                     connected_pins.append(f"{pin['comp']}_{pin['pin']}")
    #                     break
    #             # for wire in self.wires:
    #             #     if self.is_point_on_wire((px, py), wire):
    #             #         connected_pins.append(f"{pin['comp']}_{pin['pin']}")
    #             #         break

    #         for pin_node in connected_pins:
    #             G.add_edge(net_name, pin_node)
    #     return G
    
'''

componenet graph nodes ['D1', 'R1', 'BT1']

componenet graph edges [('D1', 'R1'), ('D1', 'BT1'), ('R1', 'BT1')]

'''