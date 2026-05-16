from .utils import *
def Current_violations(netGraph, CURRENT_CONFIG, COPPER_OZ, nets):
    violations = []
    for net, data in netGraph.items():
        if net not in CURRENT_CONFIG:
            continue
        
        required_current = CURRENT_CONFIG[net]
        actual_width = data["avg_width"]
        safe_current = max_current(actual_width, COPPER_OZ)
        
        if safe_current < required_current:
            thinnest = min(nets[net], key=lambda t: t.GetWidth())
            mid = thinnest.GetStart()
            
            violations.append({
                "net": net,
                "type": "width",
                "severity": "red",
                "actual_width_mm": actual_width,
                "safe_current_A": safe_current,
                "required_current_A": required_current,
                "message": f"{net} trace too thin: supports {safe_current:.2f}A but needs {required_current}A",
                "position": (mid.x / 1e6, mid.y / 1e6), # mm
            })
    return violations
# def Current_violations(netGraph, CURRENT_CONFIG, COPPER_OZ,nets):
#     violations = []
#     for net, data in netGraph.items():
#             if net not in CURRENT_CONFIG:
#                 continue
            
#             required_current = CURRENT_CONFIG[net] 
#             actual_width = data["avg_width"]
            
#             safe_current = max_current(actual_width, COPPER_OZ)
            
#             if safe_current < required_current:
#                 violations.append({
#                     "net": net,
#                     "type": "width",
#                     "severity": "red",
#                     "actual_width_mm": actual_width,
#                     "safe_current_A": safe_current,
#                     "required_current_A": required_current,
#                     "message": f"{net} trace too thin: supports {safe_current:.2f}A but given {required_current}A",
#                 })

#     return violations

def Voltage_violations(netGraph, nets, CURRENT_CONFIG, VOLTAGE_CONFIG):
    violations = []
    for net,data in netGraph.items():
        if net not in CURRENT_CONFIG:
            continue
        current = CURRENT_CONFIG[net]
        length = data["total_length"]
        width = min(t.GetWidth() for t in nets[net]) / 1e6

        v_drop = ir_drop(length, width, current)
        if net in VOLTAGE_CONFIG:
            v_supply = VOLTAGE_CONFIG[net]
            drop_pct = (v_drop / v_supply) * 100
            
            severity = None
            if drop_pct > 5:
                severity = "red"
            elif drop_pct > 3:
                severity = "amber"
            
            if severity:
                longest = max(nets[net], key=lambda t: t.GetLength())
                mid = longest.GetStart()

                violations.append({
                    "net": net,
                    "type": "ir_drop",
                    "severity": severity,
                    "voltage_drop": v_drop,
                    "drop_pct": drop_pct,
                    "message": f"{net}: drop {drop_pct:.2f}% ({v_drop:.3f}V)",
                    "position": (mid.x / 1e6, mid.y / 1e6),
                })
    return violations

def Capacitor_violations(footMaps, POWER_NETS):
    violations = []
    ics = {k: v for k, v in footMaps.items() if k.startswith("U")}
    caps = {k: v for k, v in footMaps.items() if k.startswith("C")}

    for ref, pads in ics.items():
        net_positions = {}

        # group positions by net
        for (pos, net) in pads:
            if net not in POWER_NETS:
                continue
            net_positions.setdefault(net, []).append(pos)

        for net, positions in net_positions.items():
            ic_pos = positions[0]          # ← IC pad position, safe reference
            nearest = float("inf")
            nearest_cref = None

            for cref, cpads in caps.items():
                for (cpos, cnet) in cpads:
                    if cnet == net:
                        for pos in positions:
                            d = distance(pos, cpos)
                            if d < nearest:
                                nearest = d
                                nearest_cref = cref

            if nearest == float("inf"):
                violations.append({
                    "net": net,
                    "type": "decap",
                    "severity": "red",
                    "message": f"{ref}: no capacitor on {net}",
                    "position": ic_pos,    # ← FIXED
                })
            elif nearest > 3:
                violations.append({
                    "net": net,
                    "type": "decap",
                    "severity": "red",
                    "distance": nearest,
                    "message": f"{ref}: nearest cap {nearest_cref} at {nearest:.2f} mm",
                    "position": ic_pos,    # ← FIXED
                })
    return violations