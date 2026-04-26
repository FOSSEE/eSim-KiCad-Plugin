import pcbnew
import wx
import wx.lib.scrolledpanel as scrolled
import numpy as np

from .analysis_utils import convert_nm_to_mm, analyze_traces
from .heatmap import generate_heatmap, generate_thermal_map, generate_emi_map
from .heatmap import generate_temperature_map

class AnalysisFrame(wx.Frame):
    def _build_hotspot_section(self, panel):
        box = wx.StaticBox(panel, label="Hotspot Analysis")
        box_sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        text = wx.StaticText(panel, label=
            "🔥 Definition:\n"
            "Hotspot = region with high density + high thermal stress\n\n"

            "📊 Result:\n"
            "Red boxes in heatmap indicate critical zones\n\n"

            "⚠️ Problem:\n"
            "These areas may overheat, cause failure or reduce lifespan\n\n"

            "✔ Fix:\n"
            "• Redistribute traces\n"
            "• Increase spacing\n"
            "• Add copper pours / ground planes\n"
            "• Use multi-layer routing"
        )
        text.Wrap(800)
        box_sizer.Add(text, 0, wx.ALL, 5)
        return box_sizer
    def _build_correlation_section(self, panel, heatmap,avg):
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas

        box = wx.StaticBox(panel, label="Correlation Analysis")
        box_sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        header = self._build_section_label(panel, "Density vs Thermal Relationship")
        box_sizer.Add(header, 0, wx.BOTTOM, 8)

        density = heatmap.flatten()
        thermal = generate_thermal_map(heatmap, avg).flatten()
        if np.std(density) == 0 or np.std(thermal) == 0:
            corr = 0
        else:
            corr = np.corrcoef(density, thermal)[0, 1]

        corr_text = wx.StaticText(panel, label=f"Correlation Coefficient: {corr:.2f}")
        corr_text.Wrap(800)
        box_sizer.Add(corr_text, 0, wx.ALL, 5)

        corr = np.corrcoef(density, thermal)[0, 1]


        fig = plt.Figure(figsize=(6, 4), dpi=100)
        ax = fig.add_subplot(111)

        ax.scatter(density, thermal)
        ax.set_xlabel("Density")
        ax.set_ylabel("Thermal")
        ax.set_title("Density vs Temperature")
        ax.grid(True, linestyle='--', alpha=0.5)

        canvas = FigureCanvas(panel, -1, fig)
        box_sizer.Add(canvas, 1, wx.EXPAND | wx.ALL, 5)

        explain = wx.StaticText(panel, label=
            "📘 Definition:\n"
            "Correlation shows relationship between two parameters\n\n"

            "📊 Result:\n"
            "• Upward trend → High density = High heat 🔥\n"
            "• Strong pattern → serious design issue\n\n"

            "⚠️ Problem:\n"
            "Dense routing traps heat and causes hotspots\n\n"

            "✔ Fix:\n"
            "Increase spacing\n"
            "Use multi-layer routing\n"
            "Add copper pours for cooling"
        )
        explain.Wrap(800)
        box_sizer.Add(explain, 0, wx.ALL, 5)
        return box_sizer
    def _build_histogram_section(self, panel):
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas

        box = wx.StaticBox(panel, label="Track Width Distribution")
        box_sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        header = self._build_section_label(panel, "Histogram Analysis")
        box_sizer.Add(header, 0, wx.BOTTOM, 8)

        fig = plt.Figure(figsize=(5, 3), dpi=100)
        ax = fig.add_subplot(111)

        ax.hist(self.widths_mm, bins=15)
        ax.axvline(np.mean(self.widths_mm), linestyle='--')
        ax.set_title("Track Width Histogram")
        ax.set_xlabel("Width (mm)")
        ax.set_ylabel("Frequency")
        ax.grid(True, linestyle='--', alpha=0.5)

        canvas = FigureCanvas(panel, -1, fig)
        box_sizer.Add(canvas, 1, wx.EXPAND | wx.ALL, 5)

        explain = wx.StaticText(panel, label=
            "📘 Definition:\n"
            "Histogram shows distribution of track widths\n\n"

            "📊 Result:\n"
            "• Narrow spread → consistent design ✅\n"
            "• Wide spread → inconsistent routing ❌\n\n"

            "⚠️ Problem:\n"
            "Inconsistent widths can cause uneven current flow\n\n"

            "✔ Fix:\n"
            "Use standard net classes and uniform widths"
        )
        explain.Wrap(800)
        box_sizer.Add(explain, 0, wx.ALL, 5)
        return box_sizer
    def _build_component_section(self, panel):
        box = wx.StaticBox(panel, label="Component & Via Analysis")
        box_sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        text = wx.StaticText(panel, label=
            f"Total Vias: {self.via_count}\n"
            f"Total Capacitors: {self.cap_count}\n\n"
            "Insights:\n"
            "→ High vias = manufacturing stress\n"
            "→ Too many capacitors = congestion risk"
        )
        text.Wrap(800)
        box_sizer.Add(text, 0, wx.ALL, 5)
        return box_sizer
    def _build_problem_section(self, panel, min_w, std):
        box = wx.StaticBox(panel, label="Problems & Solutions")
        box_sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        text = "Detected Issues & Fixes:\n\n"

        if min_w < 0.15:
            text += "❌ Thin traces detected\n"
            text += "✔ Fix:\n"
            text += "  1. Increase track width ≥ 0.2 mm\n"
            text += "  2. Use proper netclass rules\n\n"

        if std > 0.1:
            text += "❌ Inconsistent routing\n"
            text += "✔ Fix:\n"
            text += "  1. Maintain uniform width\n"
            text += "  2. Follow DRC rules\n\n"

        text += "❌ Congestion detected\n"
        text += "✔ Fix:\n"
        text += "  1. Spread traces evenly\n"
        text += "  2. Use multi-layer PCB\n"

        label = wx.StaticText(panel, label=text)
        label.Wrap(800)
        box_sizer.Add(label, 0, wx.ALL, 5)

        return box_sizer
    def _build_theory_section(self, panel, avg, min_w, std):
        box = wx.StaticBox(panel, label="Concept Explanation (For Students)")
        box_sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        text = wx.StaticText(panel, label=
            f"Average Track Width ({avg:.3f} mm):\n"
            "→ Average thickness of all PCB tracks\n"
            "→ Higher = better current carrying capacity\n\n"

            f"Minimum Track Width ({min_w:.3f} mm):\n"
            "→ Thinnest track in PCB\n"
            "→ Too thin = risk of burning or breaking\n\n"

            f"Standard Deviation ({std:.3f}):\n"
            "→ Variation in track widths\n"
            "→ High value = inconsistent design\n\n"

            "EMI (Electromagnetic Interference):\n"
            "→ Disturbance caused by nearby signals\n"
            "→ Happens when traces are too close or dense\n"
            "→ Can cause noise and circuit failure\n\n"

            "What results indicate:\n"
            "→ Green = Safe\n"
            "→ Yellow = Moderate risk\n"
            "→ Red = High risk\n\n"

            "Real-world impact:\n"
            "→ Poor PCB design causes overheating & signal loss\n"
            "→ Good design improves reliability & lifespan"
        )
        text.Wrap(800)
        box_sizer.Add(text, 0, wx.ALL, 5)
        return box_sizer
    def __init__(self, parent, title, avg, std, min_w, heatmap, xedges, yedges, via_count, cap_count, widths_mm):
        super().__init__(parent, title=title, size=(1200, 900))
        self.widths_mm = widths_mm
        self.via_count = via_count
        self.cap_count = cap_count
        self.SetBackgroundColour(wx.Colour(245, 245, 245))
        self.SetMinSize((960, 760))

        panel = scrolled.ScrolledPanel(self, style=wx.TAB_TRAVERSAL)
        panel.SetupScrolling(scroll_x=False, scroll_y=True, rate_x=10, rate_y=10)

        main_sizer = wx.BoxSizer(wx.VERTICAL)

        main_sizer.Add(self._build_metrics_section(panel, avg, std, min_w), 0, wx.EXPAND | wx.ALL, 10)
        main_sizer.Add(self._build_component_section(panel), 0, wx.EXPAND | wx.ALL, 10)
        main_sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        main_sizer.Add(self._build_visualization_section(panel, avg, heatmap, xedges, yedges), 0, wx.EXPAND | wx.ALL, 10)
        main_sizer.Add(self._build_histogram_section(panel), 0, wx.EXPAND | wx.ALL, 10)
        main_sizer.Add(self._build_correlation_section(panel, heatmap,avg), 0, wx.EXPAND | wx.ALL, 10)
        main_sizer.Add(self._build_risk_section(panel, heatmap), 0, wx.EXPAND | wx.ALL, 10)
        main_sizer.Add(self._build_suggestions_section(panel, min_w, std), 0, wx.EXPAND | wx.ALL, 10)
        main_sizer.Add(self._build_final_score_section(panel, min_w, std), 0, wx.EXPAND | wx.ALL, 10)
        main_sizer.Add(self._build_theory_section(panel, avg, min_w, std), 0, wx.EXPAND | wx.ALL, 10)
        main_sizer.Add(self._build_problem_section(panel, min_w, std), 0, wx.EXPAND | wx.ALL, 10)
        main_sizer.Add(self._build_hotspot_section(panel), 0, wx.EXPAND | wx.ALL, 10)

        #self.SetSizer(wx.BoxSizer(wx.VERTICAL)).Add(panel, 1, wx.EXPAND)
        panel.SetSizer(main_sizer)
        panel.SetupScrolling(scroll_x=False, scroll_y=True)
        root_sizer = wx.BoxSizer(wx.VERTICAL)
        root_sizer.Add(panel, 1, wx.EXPAND)

        self.SetSizer(root_sizer)


        self.Centre()
        self.Layout()
        panel.Layout()
        panel.FitInside()

    def _build_section_label(self, panel, title_text):
        label = wx.StaticText(panel, label=title_text)
        label.Wrap(800)
        label_font = label.GetFont()
        label_font.SetPointSize(11)
        label_font.SetWeight(wx.FONTWEIGHT_BOLD)
        label.SetFont(label_font)
        return label

    def _build_metrics_section(self, panel, avg, std, min_w):
        box = wx.StaticBox(panel, label="Metrics")
        box_sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        header = self._build_section_label(panel, "Key manufacturing metrics")
        box_sizer.Add(header, 0, wx.BOTTOM, 8)

        card_sizer = wx.BoxSizer(wx.HORIZONTAL)
        card_sizer.Add(self._build_metric_card(panel, "Average Track Width", f"{avg:.3f} mm"), 1, wx.EXPAND | wx.ALL, 4)
        card_sizer.Add(self._build_metric_card(panel, "Minimum Track Width", f"{min_w:.3f} mm"), 1, wx.EXPAND | wx.ALL, 4)
        card_sizer.Add(self._build_metric_card(panel, "Standard Deviation", f"{std:.3f}"), 1, wx.EXPAND | wx.ALL, 4)

        box_sizer.Add(card_sizer, 1, wx.EXPAND)
        return box_sizer

    def _build_metric_card(self, panel, label_text, value_text):
        card = wx.Panel(panel)
        card.SetBackgroundColour(wx.Colour(255, 255, 255))
        card_sizer = wx.BoxSizer(wx.VERTICAL)

        label = wx.StaticText(card, label=label_text)
        label.Wrap(800)
        label_font = label.GetFont()
        label_font.SetWeight(wx.FONTWEIGHT_BOLD)
        label.SetFont(label_font)

        value = wx.StaticText(card, label=value_text)
        value.Wrap(800)
        value_font = value.GetFont()
        value_font.SetPointSize(10)
        value.SetFont(value_font)

        card_sizer.Add(label, 0, wx.BOTTOM, 4)
        card_sizer.Add(value, 0)
        card.SetSizer(card_sizer)
        # card.SetMinSize((280, 70))
        return card

    def _build_visualization_section(self, panel, avg, heatmap, xedges, yedges):
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas
        from matplotlib.patches import Rectangle
        box = wx.StaticBox(panel, label="Visualization")
        box_sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        header = self._build_section_label(panel, "Embedded PCB analysis charts")
        box_sizer.Add(header, 0, wx.BOTTOM, 8)

        fig = plt.Figure(figsize=(11, 3.8), dpi=100)
        axes = fig.subplots(1, 4)

        extent = [xedges[0], xedges[-1], yedges[0], yedges[-1]]
        density_plot = axes[0].imshow(heatmap.T, origin="lower", extent=extent, cmap="viridis", aspect="auto")
        axes[0].set_title("Density")
        fig.colorbar(density_plot, ax=axes[0], fraction=0.045, pad=0.04)

        heatmap_norm = heatmap / (np.max(heatmap) + 1e-6)
        thermal_map = generate_thermal_map(heatmap_norm, avg)
        emi_map = generate_emi_map(heatmap_norm)


        thermal_plot = axes[1].imshow(thermal_map.T, origin="lower", extent=extent, cmap="inferno", aspect="auto")
        axes[1].set_title("Thermal 🔥")
        fig.colorbar(thermal_plot, ax=axes[1], fraction=0.045, pad=0.04)

        emi_plot = axes[2].imshow(emi_map.T, origin="lower", extent=extent, cmap="coolwarm", aspect="auto")
        axes[2].set_title("EMI (Electromagnetic Interference) 📡")
        fig.colorbar(emi_plot, ax=axes[2], fraction=0.045, pad=0.04)
        temperature_map = generate_temperature_map(thermal_map)

        temp_plot = axes[3].imshow(
            temperature_map.T,
            origin="lower",
            extent=extent,
            cmap="hot",
            aspect="auto"
        )

        axes[3].set_title("Temperature (°C) 🌡️")
        fig.colorbar(temp_plot, ax=axes[3], fraction=0.045, pad=0.04)

        threshold = np.max(heatmap) * 0.6 if heatmap.size > 0 else 0
        for i in range(len(heatmap)):
            for j in range(len(heatmap[i])):
                if heatmap[i][j] >= threshold and heatmap[i][j] > 0:
                    x1 = xedges[i]
                    x2 = xedges[i + 1]
                    y1 = yedges[j]
                    y2 = yedges[j + 1]
                    w = x2 - x1
                    h = y2 - y1

                    if w > 0 and h > 0:
                        rect = Rectangle((x1, y1), w, h, fill=False, edgecolor="red", linewidth=1.5)
                        axes[0].add_patch(rect)
                        axes[1].add_patch(Rectangle((x1, y1), w, h, fill=False, edgecolor="red", linewidth=1.0))
                        axes[2].add_patch(Rectangle((x1, y1), w, h, fill=False, edgecolor="red", linewidth=1.0))
                        axes[3].add_patch(Rectangle((x1, y1), w, h, fill=False, edgecolor="red", linewidth=1.0))

        for axis in axes:
            axis.set_xlabel("X (mm)")
            axis.set_ylabel("Y (mm)")
            axis.grid(True, linestyle="--", linewidth=0.4, alpha=0.6)
             # ✅ FIXED readable labels
            axis.text(0.02, 0.95, "Dark = Low activity",
                    transform=axis.transAxes,
                    fontsize=8,
                    color="black",
                    bbox=dict(facecolor='white', alpha=0.6))

            axis.text(0.02, 0.90, "Bright = High congestion",
                    transform=axis.transAxes,
                    fontsize=8,
                    color="black",
                    bbox=dict(facecolor='white', alpha=0.6))
        fig.tight_layout()
        canvas = FigureCanvas(panel, -1, fig)
        canvas.SetMinSize((1040, 360))
        box_sizer.Add(canvas, 0, wx.EXPAND | wx.ALL, 5)
        # 📘 EXPLANATION TEXT
        explain = wx.StaticText(panel, label=
                "📘 Definition:\n"
                "Density → number of traces per area\n"
                "Thermal → heat generation factor (I²R)\n"
                "Temperature → actual heat in °C\n"
                "EMI → electromagnetic interference\n\n"

                "📊 Result:\n"
                "Bright zones = high temperature & risk\n"
                "Dark zones = safe areas\n\n"

                "⚠️ Problem:\n"
                "High temperature → PCB damage, signal loss\n\n"

                "✔ Fix:\n"
                "Increase trace width\n"
                "Reduce congestion\n"
                "Add cooling layers\n"
        )
        explain.Wrap(800)
        box_sizer.Add(explain, 0, wx.ALL, 5)
        return box_sizer

    def _build_risk_section(self, panel, heatmap):
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas

        box = wx.StaticBox(panel, label="Risk Analysis")
        box_sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        header = self._build_section_label(panel, "Risk distribution across the board")
        box_sizer.Add(header, 0, wx.BOTTOM, 8)

        max_val = np.max(heatmap) if heatmap.size > 0 else 1
        safe = int(np.count_nonzero(heatmap < 0.3 * max_val))
        moderate = int(np.count_nonzero((heatmap >= 0.3 * max_val) & (heatmap <= 0.7 * max_val)))
        risk = int(np.count_nonzero(heatmap > 0.7 * max_val))

        fig = plt.Figure(figsize=(4.5, 4), dpi=100)
        ax = fig.add_subplot(111)
        labels = ["Safe", "Moderate", "Risk"]
        sizes = [safe, moderate, risk]
        colors = ["#4CAF50", "#FFC107", "#F44336"]
        wedges, texts, autotexts = ax.pie(
            sizes,
            labels=None,
            autopct=lambda pct: f"{pct:.1f}%" if pct >= 2 else "",
            pctdistance=0.72,
            textprops={"fontsize": 8, "color": "white"},
            colors=colors,
            startangle=90,
            wedgeprops={"edgecolor": "white"}
        )
        ax.set_title("Risk Distribution")
        ax.axis("equal")
        ax.legend(wedges, labels, title="Zones", loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=8)
        fig.tight_layout()

        canvas = FigureCanvas(panel, -1, fig)
        canvas.SetMinSize((420, 340))
        box_sizer.Add(canvas, 0, wx.EXPAND | wx.ALL, 5)

        summary = wx.StaticText(panel, label=f"Safe: {safe}  •  Moderate: {moderate}  •  Risk: {risk}")
        summary.Wrap(600)
        box_sizer.Add(summary, 0, wx.EXPAND | wx.TOP | wx.LEFT, 5)
        # 📊 BAR GRAPH
        fig2 = plt.Figure(figsize=(4.5, 3), dpi=100)
        ax2 = fig2.add_subplot(111)

        categories = ["Safe", "Moderate", "Risk"]
        values = [safe, moderate, risk]

        ax2.bar(categories, values)
        ax2.set_title("Risk Count Comparison")
        ax2.set_ylabel("Number of Regions")
        ax2.grid(True, linestyle='--', alpha=0.5)

        canvas2 = FigureCanvas(panel, -1, fig2)
        canvas2.SetMinSize((380, 240))
        box_sizer.Add(canvas2, 0, wx.EXPAND | wx.ALL, 5)
        explain = wx.StaticText(panel, label="""📘 Definition:
Risk distribution shows how PCB area is classified

📊 Result:
• Green → Safe zones
• Yellow → Moderate congestion
• Red → High risk regions

⚠️ Problem:
More red zones → poor manufacturability

✔ Fix:
Improve routing distribution and spacing""")
        explain.Wrap(800)

        box_sizer.Add(explain, 0, wx.ALL, 5)

        return box_sizer

    def _build_suggestions_section(self, panel, min_w, std):
        box = wx.StaticBox(panel, label="Suggestions")
        box_sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        header = self._build_section_label(panel, "Actionable guidance for better manufacturability")
        box_sizer.Add(header, 0, wx.BOTTOM, 8)

        if min_w < 0.15:
            box_sizer.Add(self._build_warning_text(panel, "Increase trace width", wx.Colour(204, 0, 0)), 0, wx.EXPAND | wx.ALL, 4)

        if std > 0.1:
            box_sizer.Add(self._build_warning_text(panel, "Routing is inconsistent", wx.Colour(204, 153, 0)), 0, wx.EXPAND | wx.ALL, 4)

        box_sizer.Add(self._build_advice_text(panel, "Avoid routing congestion"), 0, wx.EXPAND | wx.ALL, 4)
        box_sizer.Add(self._build_advice_text(panel, "Distribute traces evenly"), 0, wx.EXPAND | wx.ALL, 4)
        if self.via_count > 100:
            box_sizer.Add(self._build_warning_text(panel, "Too many vias (manufacturing risk)", wx.Colour(255, 140, 0)), 0, wx.EXPAND | wx.ALL, 4)

        if self.cap_count > 50:
            box_sizer.Add(self._build_warning_text(panel, "Too many capacitors (routing congestion)", wx.Colour(255, 140, 0)), 0, wx.EXPAND | wx.ALL, 4)

        return box_sizer

    def _build_warning_text(self, panel, message, colour):
        warning = wx.Panel(panel)
        warning.SetBackgroundColour(colour)
        warning_sizer = wx.BoxSizer(wx.HORIZONTAL)

        text = wx.StaticText(warning, label=message)
        text.Wrap(800)
        text.SetForegroundColour(wx.Colour(255, 255, 255))
        text_font = text.GetFont()
        text_font.SetWeight(wx.FONTWEIGHT_BOLD)
        text.SetFont(text_font)

        warning_sizer.Add(text, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 8)
        warning.SetSizer(warning_sizer)
        return warning

    def _build_advice_text(self, panel, message):
        advice = wx.Panel(panel)
        advice.SetBackgroundColour(wx.Colour(255, 255, 255))
        advice_sizer = wx.BoxSizer(wx.HORIZONTAL)

        bullet = wx.StaticText(advice, label="•")
        text = wx.StaticText(advice, label=message)
        text.Wrap(800)
        text_font = text.GetFont()
        text_font.SetWeight(wx.FONTWEIGHT_BOLD)
        text.SetFont(text_font)

        advice_sizer.Add(bullet, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 8)
        advice_sizer.Add(text, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 8)
        advice.SetSizer(advice_sizer)
        return advice

    def _build_final_score_section(self, panel, min_w, std):
        box = wx.StaticBox(panel, label="Final Score")
        box_sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        header = self._build_section_label(panel, "Manufacturability score")
        box_sizer.Add(header, 0, wx.BOTTOM, 8)

        score = 100
        if min_w < 0.15:
            score -= 30
        if std > 0.1:
            score -= 20
        # ✅ NEW FEATURES
        if self.via_count > 100:
            score -= 10
           # text += "\n❌ Excessive vias\n✔ Fix:\n  Reduce via usage\n  Optimize routing layers\n"

        if self.cap_count > 50:
            score -= 10
           # text += "\n❌ Excessive capacitors\n✔ Fix:\n  Reduce capacitor usage\n  Optimize routing layers\n"

        status = "GOOD PCB"
        status_color = wx.Colour(34, 139, 34)

        if score <= 60:
            status = "HIGH RISK PCB"
            status_color = wx.Colour(204, 0, 0)
        elif score <= 80:
            status = "AVERAGE PCB"
            status_color = wx.Colour(204, 153, 0)
        if score > 90:
            remark = "Excellent Design ✅"
        elif score > 75:
            remark = "Good but can improve ⚠️"
        else:
            remark = "Needs optimization ❌"

        remark_label = wx.StaticText(panel, label=remark)
        remark_label.Wrap(800)
        box_sizer.Add(remark_label, 0, wx.ALL, 4)

        score_label = wx.StaticText(panel, label=f"Score: {score}")
        score_label.Wrap(800)
        score_font = score_label.GetFont()
        score_font.SetPointSize(12)
        score_font.SetWeight(wx.FONTWEIGHT_BOLD)
        score_label.SetFont(score_font)

        status_label = wx.StaticText(panel, label=status)
        status_label.Wrap(800)
        status_font = status_label.GetFont()
        status_font.SetPointSize(11)
        status_font.SetWeight(wx.FONTWEIGHT_BOLD)
        status_label.SetFont(status_font)
        status_label.SetForegroundColour(status_color)

        box_sizer.Add(score_label, 0, wx.ALL, 4)
        box_sizer.Add(status_label, 0, wx.ALL, 4)

        return box_sizer


class PCBAnalyzer(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "Smart PCB Manufacturability Analyzer"
        self.category = "Analysis"
        self.description = "Launch smart PCB manufacturability analysis inside KiCad"
        print("Plugin defaults called")

    def Run(self):
        wx.MessageBox("Plugin executed successfully!", "Debug")
        try:
            board = pcbnew.GetBoard()
            if board is None:
                wx.MessageBox("No PCB loaded. Please open a PCB first.", "Error")
                return
            tracks = board.GetTracks()
            # ✅ VIA COUNT
            vias = [t for t in tracks if hasattr(t, "GetDrillValue")]
            via_count = len(vias)

            # ✅ CAPACITOR COUNT
            modules = board.GetFootprints()
            cap_count = 0
            for m in modules:
                if m.GetReference().startswith("C"):
                    cap_count += 1
            widths_nm = [t.GetWidth() for t in tracks if hasattr(t, "GetWidth")]

            if len(widths_nm) == 0:
                wx.MessageBox("No trace widths detected on this board.", "Error", wx.OK)
                return

            widths_mm = convert_nm_to_mm(widths_nm)
            avg, std, min_w = analyze_traces(widths_mm)

            data = generate_heatmap(board)
            if data is None or len(data[0]) == 0:
                wx.MessageBox("Could not generate heatmap from the current board.", "Error", wx.OK)
                return

            heatmap, xedges, yedges = data
            frame = AnalysisFrame(None,"Smart PCB Manufacturability Analyzer",
                      avg, std, min_w,
                      heatmap, xedges, yedges,
                      via_count, cap_count,
                      widths_mm)
            frame.Show()

        except Exception as e:
            wx.MessageBox(str(e), "Error", wx.OK)


