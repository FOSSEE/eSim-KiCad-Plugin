import numpy as np


# =========================
# 📌 BASIC UTILITIES
# =========================

def convert_nm_to_mm(widths):
    return [w / 1e6 for w in widths]


def analyze_traces(widths):
    if len(widths) == 0:
        return 0, 0, 0
    avg = np.mean(widths)
    std = np.std(widths)
    min_w = np.min(widths)
    return avg, std, min_w


# =========================
# 🔥 HEATMAP REGION ANALYSIS
# =========================

def analyze_heatmap_regions(heatmap, xedges, yedges):

    regions = []

    max_density = np.max(heatmap) if np.max(heatmap) > 0 else 1
    high_threshold = 0.6 * max_density
    low_threshold = 0.05 * max_density

    for i in range(len(heatmap)):
        for j in range(len(heatmap[i])):

            val = heatmap[i][j]

            x1 = xedges[i]
            x2 = xedges[i + 1]
            y1 = yedges[j]
            y2 = yedges[j + 1]

            if val >= high_threshold:
                regions.append(
                    f"HIGH density → X[{x1:.1f}-{x2:.1f}] mm, Y[{y1:.1f}-{y2:.1f}] mm"
                )

            elif val <= low_threshold:
                regions.append(
                    f"LOW density (unused area) → X[{x1:.1f}-{x2:.1f}] mm, Y[{y1:.1f}-{y2:.1f}] mm"
                )


    return regions[:10]

def generate_explainable_insights(advanced_results):

    insights = set()

    for r in advanced_results:

        if r["thermal_level"] == "HIGH":
            insights.append("High thermal risk due to dense routing and thin traces")

        if r["emi"] == "HIGH":
            insights.append("High EMI risk due to signal coupling in dense regions")

        if r["current"] == "HIGH":
            insights.append("Current overload risk due to insufficient trace width")

    return list(set(insights))[:5]
# =========================
# 🔥 ADVANCED ANALYSIS ENGINE
# =========================
def detect_width_outliers(widths):

    if len(widths) == 0:
        return []

    mean = np.mean(widths)
    std = np.std(widths)

    outliers = [w for w in widths if abs(w - mean) > 2 * std]

    return outliers
def compute_global_risk(advanced_results):

    thermal = sum(1 for r in advanced_results if r["thermal_level"] == "HIGH")
    emi = sum(1 for r in advanced_results if r["emi"] == "HIGH")
    current = sum(1 for r in advanced_results if r["current"] == "HIGH")

    total = len(advanced_results)

    if total == 0:
        return 0

    # Weighted score
    score = (2 * thermal + 1.5 * emi + current) / (total * 2)
    return min(score, 1)
def classify_board_zones(advanced_results):
    safe = 0
    moderate = 0
    high = 0

    for r in advanced_results:
        if r["thermal_level"] == "HIGH" or r["emi"] == "HIGH":
            high += 1
        elif r["thermal_level"] == "MEDIUM" or r["emi"] == "MEDIUM":
            moderate += 1
        else:
            safe += 1
def analyze_advanced(heatmap, widths_mm):

    results = []

    avg_width = np.mean(widths_mm) if len(widths_mm) > 0 else 0.2
    max_density = np.max(heatmap) if np.max(heatmap) > 0 else 1

    for i in range(len(heatmap)):
        for j in range(len(heatmap[i])):

            density = heatmap[i][j]

            # Normalize density (0 to 1)
            norm_density = density / max_density

            # =========================
            # 🌡️ THERMAL RISK
            # =========================
            thermal_score = (norm_density ** 2) * (1 / (avg_width + 1e-6))
 
            if thermal_score > 4:
                thermal_level = "HIGH"
            elif thermal_score > 2:
                thermal_level = "MEDIUM"
            else:
                thermal_level = "LOW"

            # =========================
            # ⚡ CURRENT RISK
            # =========================
            if avg_width < 0.18 and norm_density > 0.5:
                current_risk = "HIGH"
            elif avg_width < 0.25:
                current_risk = "MEDIUM"
            else:
                current_risk = "LOW"

            # =========================
            # 📡 EMI RISK
            # =========================
            if norm_density > 0.7:
                emi_risk = "HIGH"
            elif norm_density > 0.4:
                emi_risk = "MEDIUM"
            else:
                emi_risk = "LOW"

            # =========================
            # 🔌 COMPONENT DENSITY (APPROX)
            # =========================
            if norm_density > 0.6:
                comp_risk = "HIGH"
            elif norm_density > 0.3:
                comp_risk = "MEDIUM"
            else:
                comp_risk = "LOW"

            results.append({
                "i": i,
                "j": j,
                "density": density,
                "norm_density": norm_density,
                "thermal_score": thermal_score,
                "thermal_level": thermal_level,
                "current": current_risk,
                "emi": emi_risk,
                "component": comp_risk
            })

    return results


# =========================
# 📊 SMART REPORT GENERATOR
# =========================

def generate_smart_report(avg, std, min_w, region_issues, advanced_results):

    report = []

    report.append("🚀 SMART PCB ANALYSIS (ADVANCED MODE)\n")

    # =========================
    # 📊 BASIC METRICS
    # =========================
    report.append("📊 BASIC METRICS:")
    report.append(f"• Average Width  : {avg:.3f} mm")
    report.append(f"• Minimum Width  : {min_w:.3f} mm")
    report.append(f"• Variation      : {std:.3f}\n")

    # =========================
    # ❗ BASIC PROBLEMS
    # =========================
    report.append("❗ PROBLEMS DETECTED:\n")

    if min_w < 0.15:
        report.append("🔴 Thin traces → Overheating / break risk")
    else:
        report.append("🟢 Trace thickness safe")

    if std > 0.1:
        report.append("🔴 Non-uniform widths → Thermal imbalance")
    else:
        report.append("🟢 Uniform widths")

    if region_issues:
        report.append("🔴 Routing imbalance detected")

    # =========================
    # 🔥 ADVANCED SUMMARY
    # =========================
    high_thermal = sum(1 for r in advanced_results if r["thermal_level"] == "HIGH")
    high_emi = sum(1 for r in advanced_results if r["emi"] == "HIGH")
    high_current = sum(1 for r in advanced_results if r["current"] == "HIGH")
    high_comp = sum(1 for r in advanced_results if r["component"] == "HIGH")

    total_cells = len(advanced_results)

    report.append("\n🔥 ADVANCED ANALYSIS:")

    report.append(f"• Thermal Hotspots      : {high_thermal} / {total_cells}")
    report.append(f"• EMI Risk Zones        : {high_emi} / {total_cells}")
    report.append(f"• Current Risk Regions  : {high_current} / {total_cells}")
    report.append(f"• Component Hotspots    : {high_comp} / {total_cells}\n")

    # =========================
    # 📍 REGIONS
    # =========================
    report.append("📍 CRITICAL REGIONS:")

    if region_issues:
        for r in region_issues[:6]:
            report.append(f"→ {r}")
    else:
        report.append("No major spatial issues")

    # =========================
    # 🛠 SMART FIXES
    # =========================
    report.append("\n🛠 SMART FIXES:\n")

    report.append("1. Increase thin traces ≥ 0.2 mm (reduces heating)")
    report.append("2. Maintain uniform widths (avoids thermal imbalance)")
    report.append("3. Spread traces evenly (reduces congestion)")
    report.append("4. Increase spacing between traces (reduces EMI)")
    report.append("5. Avoid dense component clustering")
    report.append("6. Utilize empty PCB regions effectively")
    global_score = compute_global_risk(advanced_results)

    report.append(f"\n📊 Global Risk Score: {global_score:.2f}")
    insights = generate_explainable_insights(advanced_results)

    report.append("\n🧠 AI Insights:")
    for i in insights:
        report.append(f"→ {i}")
    # =========================
    # 🏁 FINAL STATUS
    # =========================
    report.append("\n🏁 FINAL STATUS:")

    risk_ratio = (high_thermal + high_emi + high_current) / total_cells

    if risk_ratio > 0.2:
        report.append("⚠ HIGH RISK PCB DESIGN")
    else:
        report.append("✅ SAFE / OPTIMIZED PCB")

    return "\n".join(report)