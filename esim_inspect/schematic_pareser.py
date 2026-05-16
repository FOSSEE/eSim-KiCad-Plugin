from sexpdata import loads
import math
'''
find_componenets return this : 
[{'type': 'Device:R', 'ref': 'R1', 'value': '470'}, {'type': 'Device:Battery', 'ref': 'BT1', 'value': '9V', 'Sim.Device': 'V', 'Sim.Type': 'DC', 'Sim.Pins': '1=+ 2=-'}, {'type': 'Device:LED', 'ref': 'D1', 'value': 'LED', 'Sim.Pins': '1=K 2=A'}]

get_wires return this : 
[([114.3, 82.55], [116.84, 82.55]),([106.68, 82.55], [106.68, 92.71]), ([124.46, 82.55], [128.27, 82.55]), ([106.68, 92.71], [128.27, 92.71]])]
'''
class Extract_Information():
    
    def __init__(self,sch_data):
        self.sch_data = sch_data
        
    def find_components(self):
        data = loads(self.sch_data)
        
        components = []
        for item in data:
            if isinstance(item,list):
                if len(item) > 0 and item[0].value() == "symbol":
                    comp = {}
                    for element in item:
                        if isinstance(element,list):

                            key = element[0].value()

                            if key == "lib_id":
                                comp["type"] = element[1]

                            if key == "property":

                                prop_name = element[1]
                                prop_val = element[2]

                                if prop_name == "Reference":
                                    comp["ref"] = prop_val

                                if prop_name == "Value":
                                    comp["value"] = prop_val
                                
                                if prop_name.startswith("Sim"):
                                    comp[prop_name] = prop_val

                            if key == "at":
                                comp["pos"] = (element[1], element[2])
                                comp["angle"] = element[3]
                                components.append(comp)
        return components

    def get_wires(self):

        data = loads(self.sch_data)

        wires = []

        for item in data:

            if isinstance(item,list):

                if len(item) > 0 and item[0].value() == "wire":

                    for element in item:

                        if isinstance(element,list):

                            if element[0].value() == "pts":

                                p1 = element[1][1:]
                                p2 = element[2][1:]

                                wires.append((p1,p2))

        return wires
    
    def extract_symbol_pins(self):
        data = loads(self.sch_data)

        symbol_pins = {}

        for item in data:
            if isinstance(item, list) and item[0].value() == "lib_symbols":

                for sym in item:
                    if isinstance(sym, list) and sym[0].value() == "symbol":
                        
                        lib_name = sym[1]  # e.g. Device:R
                        pins = []

                        for sub in sym:
                            if isinstance(sub, list) and sub[0].value() == "symbol":
                                ############# 
                                has_pin = any(
                                    isinstance(e, list) and e[0].value() == "pin"
                                    for e in sub
                                )
                                if not has_pin:
                                    continue
                                ############# 
                                for element in sub:
                                    if isinstance(element, list) and element[0].value() == "pin":

                                        pin_num = None
                                        pos = None

                                        for e in element:
                                            if isinstance(e, list):

                                                if e[0].value() == "at":
                                                    pos = (e[1], e[2])
                                                    rot = e[2]

                                                if e[0].value() == "number":
                                                    pin_num = e[1]

                                        if pin_num and pos:
                                            pins.append({
                                                "num": pin_num,
                                                "pos": pos,
                                                "rotation":rot
                                            })

                        symbol_pins[lib_name] = pins

        return symbol_pins
    
    def get_absolute_pins(self,components, symbol_pins):

        comp_pin_positions = []

        for comp in components:

            lib = comp["type"]
            base_x, base_y = comp["pos"]
            angle = comp.get("angle", 0)

            pins = symbol_pins.get(lib, [])

            for pin in pins:

                px, py = pin["pos"]

                # rotation
                theta = math.radians(angle)

                x_rot = px * math.cos(theta) - py * math.sin(theta)
                y_rot = px * math.sin(theta) + py * math.cos(theta)

                # translation
                x_final = base_x + x_rot
                y_final = base_y + y_rot

                comp_pin_positions.append({
                    "comp": comp["ref"],
                    "pin": pin["num"],
                    "pos": (round(x_final,4), round(y_final,4))
                })

        return comp_pin_positions


    
