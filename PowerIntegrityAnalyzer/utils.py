import math

def distance(p1, p2):
    dx = p1[0] - p2[0]
    dy = p1[1] - p2[1]
    return math.sqrt(dx*dx + dy*dy)
    
def max_current(width_mm, copper_oz=1, dT=10, layer='ext'):
    k = 0.048 if layer == 'ext' else 0.024
    
    width_mils = width_mm * 39.37
    thickness_mils = copper_oz * 1.378
    
    A = width_mils * thickness_mils
    
    return k * (dT ** 0.44) * (A ** 0.725)
rho = 1.72e-8

def ir_drop(length_mm, width_mm, current_A, copper_mm=0.035):
    length_m = length_mm / 1000
    width_m = width_mm / 1000
    thickness_m = copper_mm / 1000
    
    A = width_m * thickness_m
    R = rho * length_m / A
    
    return current_A * R

