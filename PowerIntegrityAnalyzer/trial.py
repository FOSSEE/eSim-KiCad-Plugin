import pcbnew
import wx
import webbrowser

from .utils import * 
from .checkers import *
from .report import generate_report


class PowerIntegrity(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "Power_Intergrity_Analyzer"
        self.category = "PowerAnalyzer"
        self.description = "Is power reaching every component properly, stably, and safely?"
        self.show_toolbar_button = True
        self.icon_file_name = "icon.png"
        self.markers = []

    # def add_marker(self, board, position_mm, severity="red"):
    #     x_nm = int(position_mm[0] * 1e6)
    #     y_nm = int(position_mm[1] * 1e6)
        
    #     seg = pcbnew.PCB_SHAPE(board)
    #     seg.SetShape(pcbnew.SHAPE_T_CIRCLE)
    #     seg.SetCenter(pcbnew.VECTOR2I(x_nm, y_nm))
    #     seg.SetEnd(pcbnew.VECTOR2I(x_nm + int(0.5e6), y_nm))  # 0.5mm radius
    #     seg.SetWidth(int(0.1e6))  # 0.1mm line
        
    #     if severity == "red":
    #         seg.SetLayer(pcbnew.Cmts_User)   # visible layer
    #     else:
    #         seg.SetLayer(pcbnew.Eco1_User)
        
    #     board.Add(seg)
    #     self.markers.append(seg)
    def add_marker(self, board, position_mm, severity="red"):
        x_nm = int(position_mm[0] * 1e6)
        y_nm = int(position_mm[1] * 1e6)
        
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_CIRCLE)
        seg.SetCenter(pcbnew.VECTOR2I(x_nm, y_nm))
        seg.SetEnd(pcbnew.VECTOR2I(x_nm + int(1e6), y_nm))  # 1mm radius, bigger = easier to see
        seg.SetWidth(int(0.2e6))  # 0.2mm line thickness
        seg.SetFilled(False)
        
        if severity == "red":
            seg.SetLayer(pcbnew.F_Cu)   # ← guaranteed visible, on copper layer
        else:
            seg.SetLayer(pcbnew.B_Cu)
        
        board.Add(seg)
        self.markers.append(seg)

    def clear_markers(self, board):
        for m in self.markers:
            board.Remove(m)
        self.markers = []

    def Run(self):
        board = pcbnew.GetBoard()
        lines = []
        self.clear_markers(board)
        
        with open('tracks.txt', 'w') as f: 
            nets = {}
            for t in board.GetTracks():
                w_mm = t.GetWidth() / 1e6
                length_mm = t.GetLength() / 1e6
                net = t.GetNetname()
                if net not in nets:
                    nets[net] = []      
                
                # nets.setdefault(net, []).append(t)
                nets[net].append(t)      
                line = f"Width: {w_mm} mm | Length: {length_mm} mm | Net: {net}\n"
                lines.append(line)
                f.write(line)  

        # wx.MessageBox(str(nets.items()),"Nets")
        netGraph = {}
        for net, tracks in nets.items():
            total_length = 0
            total_width = 0
            netGraph[net] = {}
            for t in tracks:
                total_length += t.GetLength()
                total_width += t.GetWidth()
            avg_width = (total_width / len(tracks)) / 1e6
            total_length_mm = total_length / 1e6
            netGraph[net]["avg_width"] = avg_width
            netGraph[net]["total_length"] = total_length_mm

        with open('footprints.txt','w') as f:
            footMaps = {}
            for fp in board.GetFootprints():
                ref = fp.GetReference()
                footMaps[ref] = []
                for pad in fp.Pads():
                    net = pad.GetNetname()
                    pos = pad.GetPosition()
                    x_mm = pos.x / 1e6
                    y_mm = pos.y / 1e6
                    if ref == "REF**":
                        continue
                    if not net or "unconnected" in net:
                        continue
                    footMaps[ref].append( ( (x_mm,y_mm) ,net )  )
                    line = f"ref:{ref} | net:{net} | posx:{x_mm}mm  {y_mm}mm \n"
                    f.write(line)
            f.write(str(footMaps))
            # wx.MessageBox(str(footMaps), "footprints")
        
        ### user input section - just assumed for now
        """
            1 mm = 39.37 mils
            1 oz copper = 35 µm = 1.378 mils
            IPC 2221 : I = k x (ΔT)^0.44 x (A)^0.725

        """
        COPPER_OZ = 1  # user input , default 1 oz/ft²
        COPPER_THICKNESS_MM = COPPER_OZ * 0.035  # 35µm per oz
        CURRENT_CONFIG = {
            "+9V": 0.5,   # example
            "GND": 0.5
        }
        VOLTAGE_CONFIG = {
            "+9V":9.0
        }
        POWER_NETS = {"+9V", "VCC", "3V3", "5V", "GND"}

        ###
        violations = []
        
        # CURRENT VIOLATIONS
        violations += Current_violations(netGraph=netGraph,CURRENT_CONFIG=CURRENT_CONFIG,COPPER_OZ=COPPER_OZ,nets=nets)
        # violations += Current_violations(netGraph=netGraph,CURRENT_CONFIG=CURRENT_CONFIG,COPPER_OZ=COPPER_OZ,nets=nets)
        
        # VOLTAGE DROP
        violations += Voltage_violations(netGraph=netGraph,nets=nets,CURRENT_CONFIG=CURRENT_CONFIG, VOLTAGE_CONFIG=VOLTAGE_CONFIG)

        # CAPACITOR CHECKS
        violations += Capacitor_violations(footMaps=footMaps, POWER_NETS=POWER_NETS)

        app = wx.GetApp()
        if app is None:
            app = wx.App(False)

        # wx.MessageBox(str(violations),"Violations")
        # pcbnew.Refresh()
        dlg = PIADialog(None, netGraph, nets, footMaps, board, self)
        dlg.ShowModal()
        dlg.Destroy()



class PIADialog(wx.Dialog):
    def __init__(self, parent, netGraph, nets, footMaps, board, plugin):

        super().__init__(parent, title="Power Integrity Analyzer", size=(600, 500))
        
        self.netGraph = netGraph
        self.nets = nets
        self.footMaps = footMaps
        self.board = board        # ← ADD
        self.plugin = plugin
        # in __init__, add:
        self.report_path = None
        self.board_path = board.GetFileName()   # full path to .kicad_pcb

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        grid = wx.FlexGridSizer(4, 2, 5, 10)
        
        grid.Add(wx.StaticText(panel, label="Copper Weight (oz):"))
        self.copper_input = wx.TextCtrl(panel, value="1")
        grid.Add(self.copper_input, 1, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Power Net name (e.g. +9V):"))
        self.net_input = wx.TextCtrl(panel, value="+9V")
        grid.Add(self.net_input, 1, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Supply Voltage (V):"))
        self.voltage_input = wx.TextCtrl(panel, value="9")
        grid.Add(self.voltage_input, 1, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Expected Current (A):"))
        self.current_input = wx.TextCtrl(panel, value="0.5")
        grid.Add(self.current_input, 1, wx.EXPAND)

        vbox.Add(grid, 0, wx.ALL | wx.EXPAND, 10)

        self.run_btn = wx.Button(panel, label="▶ Run Analysis")
        self.run_btn.Bind(wx.EVT_BUTTON, self.on_run)
        vbox.Add(self.run_btn, 0, wx.CENTER | wx.BOTTOM, 10)
        

        self.clear_btn = wx.Button(panel, label="🗑 Clear Markers")   # ← ADD
        self.clear_btn.Bind(wx.EVT_BUTTON, self.on_clear)              # ← ADD
        vbox.Add(self.clear_btn, 0, wx.CENTER | wx.BOTTOM, 10)         # ← ADD
      
        self.report_btn = wx.Button(panel, label="📄 Open Report")
        self.report_btn.Bind(wx.EVT_BUTTON, self.on_open_report)
        self.report_btn.Disable()   # disabled until a run completes
        vbox.Add(self.report_btn, 0, wx.CENTER | wx.BOTTOM, 10)

        self.results_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.results_list.InsertColumn(0, "Type",     width=80)
        self.results_list.InsertColumn(1, "Severity", width=70)
        self.results_list.InsertColumn(2, "Net",      width=80)
        self.results_list.InsertColumn(3, "Message",  width=330)
        vbox.Add(self.results_list, 1, wx.EXPAND | wx.ALL, 10)

        # Summary label 
        self.summary = wx.StaticText(panel, label="")
        vbox.Add(self.summary, 0, wx.ALL, 5)

        panel.SetSizer(vbox)
    def on_open_report(self, event):
        if self.report_path:
            webbrowser.open(f"file://{self.report_path}")
    
    def on_clear(self, event):
        self.plugin.clear_markers(self.board)
        self.results_list.DeleteAllItems()
        self.summary.SetLabel("")
        pcbnew.Refresh()

    def on_run(self, event):
        try:
            copper_oz = float(self.copper_input.GetValue())
            voltage   = float(self.voltage_input.GetValue())
            net_name  = self.net_input.GetValue().strip()
            current   = float(self.current_input.GetValue())
        except ValueError:
            wx.MessageBox("Invalid input — check numbers", "Error")
            return

        CURRENT_CONFIG = {net_name: current, "GND": current}
        VOLTAGE_CONFIG = {net_name: voltage}
        POWER_NETS     = {"+9V", "VCC", "3V3", "5V", "GND", net_name}

        violations = []
        violations += Current_violations(self.netGraph, CURRENT_CONFIG, copper_oz,self.nets)
        violations += Voltage_violations(self.netGraph, self.nets, CURRENT_CONFIG, VOLTAGE_CONFIG)
        violations += Capacitor_violations(self.footMaps, POWER_NETS)

        self.results_list.DeleteAllItems()
        self.plugin.clear_markers(self.board)
        # wx.MessageBox(str(violations),"v")
        for v in violations:
            if "position" in v:
                self.plugin.add_marker(self.board, v["position"], v["severity"])
        pcbnew.Refresh()                           # ← makes arrows appear live

        red   = wx.Colour(255, 220, 220)
        amber = wx.Colour(255, 240, 180)

        for v in violations:
            idx = self.results_list.InsertItem(self.results_list.GetItemCount(), v.get("type",""))
            self.results_list.SetItem(idx, 1, v.get("severity",""))
            self.results_list.SetItem(idx, 2, v.get("net",""))
            self.results_list.SetItem(idx, 3, v.get("message",""))
            
            color = red if v.get("severity") == "red" else amber
            self.results_list.SetItemBackgroundColour(idx, color)

        reds   = sum(1 for v in violations if v.get("severity") == "red")
        ambers = sum(1 for v in violations if v.get("severity") == "amber")
        self.summary.SetLabel(f"Found {len(violations)} issues — 🔴 {reds} critical  🟡 {ambers} warnings")
        # after populating results_list:
        self.report_path = generate_report(violations, self.board_path)
        self.report_btn.Enable()

PowerIntegrity().register()