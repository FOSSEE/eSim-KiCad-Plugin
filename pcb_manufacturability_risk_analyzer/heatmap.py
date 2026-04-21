import numpy as np
import matplotlib.pyplot as plt

# =========================
# 📌 GENERATE DENSITY HEATMAP
# =========================
def generate_temperature_map(thermal_map):

    # Base ambient temperature
    ambient_temp = 25  # °C

    # Scale factor (tunable)
    scale = 20  

    temperature_map = ambient_temp + (thermal_map * scale)

    return temperature_map
def generate_heatmap(board):

    tracks = board.GetTracks()
    bbox = board.ComputeBoundingBox()
    if bbox is None:
        return None
    min_x = bbox.GetX()
    min_y = bbox.GetY()
    width = bbox.GetWidth()
    height = bbox.GetHeight()

    if width == 0 or height == 0:
        return None

    nm_to_mm = 1e-6

    xs = []
    ys = []

    for track in tracks:
        try:
            for p in [track.GetStart(), track.GetEnd()]:
                x = (p.x - min_x) * nm_to_mm
                y = (p.y - min_y) * nm_to_mm
                if np.isnan(x) or np.isnan(y):
                    continue
                xs.append(x)
                ys.append(y)
        except:
            continue

    if len(xs) == 0:
        return None

    xs = np.array(xs)
    ys = np.array(ys)

    width_mm = width * nm_to_mm
    height_mm = height * nm_to_mm

    heatmap, xedges, yedges = np.histogram2d(
        xs, ys,
        bins=20,
        range=[[0, width_mm], [0, height_mm]]
    )

    return heatmap, xedges, yedges


# =========================
# 🔥 GENERATE THERMAL MAP
# =========================
def generate_thermal_map(heatmap, avg_width):

    thermal_map = np.zeros_like(heatmap)

    for i in range(len(heatmap)):
        for j in range(len(heatmap[i])):
            density = heatmap[i][j]

            # 🌡️ Thermal model
            # 🔥 Improved Thermal Model (Power-based approximation)
            current_factor = density  # proxy for current concentration
            resistance_factor = 1 / (avg_width + 1e-6)

            thermal_map[i][j] = min((current_factor ** 2) * resistance_factor, 100)

    return thermal_map


# =========================
# 📡 GENERATE EMI MAP
# =========================
def generate_emi_map(heatmap):

    emi_map = np.zeros_like(heatmap)

    max_density = np.max(heatmap) if np.max(heatmap) > 0 else 1

    rows, cols = heatmap.shape

    for i in range(rows):
        for j in range(cols):

            density = heatmap[i][j]

            # 👇 Neighbor coupling (VERY IMPORTANT for EMI)
            neighbors = []

            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    ni, nj = i + dx, j + dy
                    if 0 <= ni < rows and 0 <= nj < cols:
                        neighbors.append(heatmap[ni][nj])

            coupling = np.mean(neighbors)

            emi_score = (density / max_density) + (coupling / max_density)

            # Normalize into levels
            if emi_score > 1.2:
                emi_map[i][j] = 3  # HIGH
            elif emi_score > 0.7:
                emi_map[i][j] = 2  # MEDIUM
            elif emi_score > 0.2:
                emi_map[i][j] = 1  # LOW

    return emi_map

def generate_via_density_map(board, xedges, yedges):

    vias = [t for t in board.GetTracks() if hasattr(t, "GetDrillValue")]

    nm_to_mm = 1e-6
    bbox = board.ComputeBoundingBox()

    min_x = bbox.GetX()
    min_y = bbox.GetY()

    via_x = []
    via_y = []

    for v in vias:
        pos = v.GetPosition()
        x = (pos.x - min_x) * nm_to_mm
        y = (pos.y - min_y) * nm_to_mm
        via_x.append(x)
        via_y.append(y)

    if len(via_x) == 0:
        return np.zeros((len(xedges)-1, len(yedges)-1))

    via_map, _, _ = np.histogram2d(
        via_x, via_y,
        bins=[xedges, yedges]
    )
    
    return via_map
def detect_hotspots(heatmap, thermal_map):

    hotspots = np.zeros_like(heatmap)

    for i in range(len(heatmap)):
        for j in range(len(heatmap[i])):

            if heatmap[i][j] > 0.6 * np.max(heatmap) and \
               thermal_map[i][j] > 0.6 * np.max(thermal_map):

                hotspots[i][j] = 1

    return hotspots
def compute_density_thermal_correlation(heatmap, thermal_map):

    d = heatmap.flatten()
    t = thermal_map.flatten()

    if len(d) == 0:
        return 0
    if np.std(d) == 0 or np.std(t) == 0:
        return 0
    corr = np.corrcoef(d, t)[0, 1]
    return corr
# =========================
# 🎨 SHOW ALL HEATMAPS
# =========================
def show_all_maps(heatmap, xedges, yedges, avg_width):

    if plt is None:
        return

    # Generate maps
    thermal_map = generate_thermal_map(heatmap, avg_width)
    emi_map = generate_emi_map(heatmap)

    fig, axs = plt.subplots(1, 4, figsize=(20, 5))

    # =========================
    # 🔴 DENSITY MAP
    # =========================
    im1 = axs[0].imshow(
        heatmap.T,
        origin='lower',
        extent=[xedges[0], xedges[-1], yedges[0], yedges[-1]],
        cmap="viridis"
    )
    axs[0].set_title("Density Heatmap")
    fig.colorbar(im1, ax=axs[0])

    # =========================
    # 🌡️ THERMAL MAP
    # =========================
    im2 = axs[1].imshow(
        thermal_map.T,
        origin='lower',
        extent=[xedges[0], xedges[-1], yedges[0], yedges[-1]],
        cmap="inferno"
    )
    axs[1].set_title("Thermal Heatmap")
    fig.colorbar(im2, ax=axs[1], label="Thermal Intensity")


    # 📡 EMI MAP (3rd)
    im3 = axs[2].imshow(
        emi_map.T,
        origin='lower',
        extent=[xedges[0], xedges[-1], yedges[0], yedges[-1]],
        cmap="coolwarm"
    )
    axs[2].set_title("EMI Risk Map")
    fig.colorbar(im3, ax=axs[2])

    # 🌡️ TEMPERATURE MAP (4th)
    temperature_map = generate_temperature_map(thermal_map)

    im4 = axs[3].imshow(
        temperature_map.T,
        origin='lower',
        extent=[xedges[0], xedges[-1], yedges[0], yedges[-1]],
        cmap='hot'
    )
    axs[3].set_title("Temperature (°C)")
    fig.colorbar(im4, ax=axs[3], label="Temperature (°C)")

    # =========================
    # 🔴 HIGHLIGHT HIGH DENSITY
    # =========================
    threshold = np.max(heatmap) * 0.6

    for i in range(len(heatmap)):
        for j in range(len(heatmap[i])):

            if heatmap[i][j] >= threshold and heatmap[i][j] > 0:

                x1 = xedges[i]
                x2 = xedges[i + 1]
                y1 = yedges[j]
                y2 = yedges[j + 1]

                for ax in axs:
                    ax.add_patch(
                        plt.Rectangle(
                            (x1, y1),
                            x2 - x1,
                            y2 - y1,
                            fill=False,
                            edgecolor='red',
                            linewidth=1.5
                        )
                    )

    for ax in axs:
        ax.set_xlabel("X (mm)")
        ax.set_ylabel("Y (mm)")
        ax.grid(True, linestyle='--', linewidth=0.5)

    plt.tight_layout()
    plt.show()


# =========================
# 🔁 BACKWARD COMPATIBILITY
# =========================
def show_heatmap(heatmap, xedges, yedges):
    # Old function → still works
    show_all_maps(heatmap, xedges, yedges, avg_width=0.2)
