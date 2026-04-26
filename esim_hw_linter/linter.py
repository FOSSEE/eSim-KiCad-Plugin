import pcbnew
import wx
import math
import os
import sys
import re
import json
import subprocess
import shutil

def load_organization_config(board_path):
    if not board_path: return None
    dir_path = os.path.dirname(board_path)
    if not dir_path: return None
    config_path = os.path.join(dir_path, "esim_security.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def distance_to_segment(p, a, b):
    # p, a, b are expected to have .x and .y attributes (e.g., VECTOR2I)
    dx = b.x - a.x
    dy = b.y - a.y
    l2 = dx*dx + dy*dy
    if l2 == 0:
        return math.hypot(p.x - a.x, p.y - a.y)
    
    t = max(0, min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / l2))
    proj_x = a.x + t * dx
    proj_y = a.y + t * dy
    return math.hypot(p.x - proj_x, p.y - proj_y)
def push_to_github(board_path, crit, warn):
    board_dir = os.path.dirname(board_path)
    board_name = os.path.basename(board_path)
    
    if not board_dir:
        wx.MessageBox("Please save your board first.", "Error", wx.OK | wx.ICON_ERROR)
        return

    # Check if git is initialized
    git_dir = os.path.join(board_dir, ".git")
    if not os.path.exists(git_dir):
        wx.MessageBox("Current project is not a git repository. Please initialize git first.", "Git Not Found", wx.OK | wx.ICON_WARNING)
        return

    # Generate workflow
    workflows_dir = os.path.join(board_dir, ".github", "workflows")
    os.makedirs(workflows_dir, exist_ok=True)
    
    workflow_content = f"""name: eSim Security Audit

on: [push, pull_request]

jobs:
  security-scan:
    runs-on: ubuntu-latest
    container:
      image: kicad/kicad:9.0
      options: --user root

    steps:
      - name: Checkout Code
        uses: actions/checkout@v5

      - name: Install Headless Display Server
        run: |
          apt-get update
          apt-get install -y xvfb

      - name: Run eSim Hardware Security Linter
        run: |
          # Use xvfb-run to simulate a virtual monitor for KiCad/wxPython
          xvfb-run python3 linter.py --board "{board_name}" --crit {crit} --warn {warn}
"""
    with open(os.path.join(workflows_dir, "security.yml"), "w") as f:
        f.write(workflow_content)
        
    # Copy linter.py to target project
    linter_src = os.path.abspath(__file__)
    linter_dst = os.path.join(board_dir, "linter.py")
    try:
        shutil.copy(linter_src, linter_dst)
    except Exception as e:
        wx.MessageBox(f"Failed to copy linter.py: {str(e)}", "Error", wx.OK | wx.ICON_ERROR)
        return
        
    # Run git commands
    try:
        subprocess.run(["git", "add", ".github/workflows/security.yml", "linter.py", board_name], cwd=board_dir, check=True, capture_output=True)
        
        # Git commit throws an error if there are no changes to commit. We should catch it cleanly.
        commit_res = subprocess.run(["git", "commit", "-m", "Auto-triggered eSim Security Audit via Plugin"], cwd=board_dir, capture_output=True)
        if commit_res.returncode != 0:
            output = commit_res.stdout.decode() + commit_res.stderr.decode()
            if "nothing to commit" not in output and "working tree clean" not in output:
                raise Exception(f"Git commit failed: {output}")
                
        subprocess.run(["git", "push", "-u", "origin", "HEAD"], cwd=board_dir, check=True, capture_output=True)
        
        # Try to automatically open the GitHub Actions page for the user
        try:
            import webbrowser
            res = subprocess.run(["git", "remote", "get-url", "origin"], cwd=board_dir, capture_output=True, text=True, check=True)
            url = res.stdout.strip()
            if url.endswith(".git"):
                url = url[:-4]
            if url.startswith("git@github.com:"):
                url = url.replace("git@github.com:", "https://github.com/")
            actions_url = f"{url}/actions"
            
            # 2.5 second non-blocking delay so GitHub has time to generate the Action page!
            wx.CallLater(2500, lambda: webbrowser.open(actions_url))
        except Exception:
            pass # Failsafe in case the URL parsing fails
            
        wx.MessageBox("Successfully deployed to GitHub Actions!\n\nYour browser will automatically open in a few seconds to show the live server logs.", "CI/CD Triggered", wx.OK | wx.ICON_INFORMATION)
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr.decode() if e.stderr else str(e)
        wx.MessageBox(f"Failed to push to GitHub. Make sure your remote is set up.\n\nError: {err_msg}", "Git Error", wx.OK | wx.ICON_ERROR)
    except Exception as e:
        wx.MessageBox(f"An unexpected error occurred:\n{str(e)}", "Error", wx.OK | wx.ICON_ERROR)

class SettingsDialog(wx.Dialog):
    def __init__(self, parent, init_crit=5.0, init_warn=15.0):
        super(SettingsDialog, self).__init__(parent, title="eSim Security Linter Settings", size=(380, 280))
        self.panel = wx.Panel(self)
        self.vbox = wx.BoxSizer(wx.VERTICAL)
        
        lbl_info = wx.StaticText(self.panel, label="Set your physical security thresholds:")
        self.vbox.Add(lbl_info, flag=wx.ALL, border=15)
        
        hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        lbl_crit = wx.StaticText(self.panel, label="Critical Risk Distance (mm):")
        self.spin_crit = wx.SpinCtrlDouble(self.panel, value=str(init_crit), min=0.1, max=100.0, inc=1.0)
        hbox1.Add(lbl_crit, flag=wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, border=8)
        hbox1.Add(self.spin_crit, proportion=1)
        
        hbox2 = wx.BoxSizer(wx.HORIZONTAL)
        lbl_warn = wx.StaticText(self.panel, label="Security Warning Distance (mm):")
        self.spin_warn = wx.SpinCtrlDouble(self.panel, value=str(init_warn), min=0.1, max=100.0, inc=1.0)
        hbox2.Add(lbl_warn, flag=wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, border=8)
        hbox2.Add(self.spin_warn, proportion=1)
        self.checkbox_github = wx.CheckBox(self.panel, label="Push to GitHub Actions (CI/CD)")
        self.checkbox_github.SetValue(False)
        
        btn_box = wx.StdDialogButtonSizer()
        self.btn_ok = wx.Button(self.panel, wx.ID_OK, label="Run Audit")
        self.btn_cancel = wx.Button(self.panel, wx.ID_CANCEL, label="Cancel")
        btn_box.AddButton(self.btn_ok)
        btn_box.AddButton(self.btn_cancel)
        btn_box.Realize()
        
        self.vbox.Add(hbox1, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, border=15)
        self.vbox.Add(hbox2, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, border=15)
        self.vbox.Add(self.checkbox_github, flag=wx.LEFT|wx.BOTTOM, border=15)
        self.vbox.Add(btn_box, flag=wx.EXPAND|wx.ALL, border=15)
        self.panel.SetSizer(self.vbox)
        
    def GetThresholds(self):
        return self.spin_crit.GetValue(), self.spin_warn.GetValue()

    def GetGitHubFlag(self):
        return self.checkbox_github.GetValue()


class ESimHardwareLinter(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "eSim Hardware Security Linter"
        self.category = "Security"
        self.description = "Audits PCB layouts for IoT physical vulnerabilities"
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")

    def Run(self):
        board = pcbnew.GetBoard()
        board_path = board.GetFileName()
        
        # Auto-save the board to disk so the GitHub push has the latest changes
        if board_path:
            try:
                pcbnew.SaveBoard(board_path, board)
            except Exception:
                pass
                
        config = load_organization_config(board_path)
        
        init_crit, init_warn = 5.0, 15.0
        if config:
            init_crit = config.get("critical_threshold_mm", 5.0)
            init_warn = config.get("warning_threshold_mm", 15.0)
            
        # Open Settings GUI Window
        dlg = SettingsDialog(None, init_crit, init_warn)
        result = dlg.ShowModal()
        crit_threshold, warn_threshold = dlg.GetThresholds()
        push_github = dlg.GetGitHubFlag()
        dlg.Destroy()
        if result != wx.ID_OK:
            return
            
        # Run local audit first as a Pre-Push Hook
        passed = audit_board(board, crit_threshold, warn_threshold, headless=False)

        if push_github:
            if passed:
                push_to_github(board_path, crit_threshold, warn_threshold)
            else:
                wx.MessageBox("GitHub Deployment Blocked!\n\nThe eSim Linter detected hardware vulnerabilities. You must fix these issues before the code can be pushed to the cloud.", "Pre-Push Hook Triggered", wx.OK | wx.ICON_ERROR)

def audit_board(board, crit_threshold, warn_threshold, headless=False):
    
    # Deselect all footprints so only the vulnerable ones are highlighted
    for fp in board.GetFootprints():
        fp.ClearSelected()
    for track in board.GetTracks():
        track.ClearSelected()
    
    # 0. Clean up old markers from previous runs
    user_drawings_layer = board.GetLayerID("User.Drawings")
    target_width = int(pcbnew.FromMM(0.3))
    items_to_remove = []
    
    for d in board.GetDrawings():
        if d.GetLayer() == user_drawings_layer and isinstance(d, pcbnew.PCB_SHAPE):
            try:
                if d.GetShape() == pcbnew.SHAPE_T_SEGMENT and d.GetWidth() == target_width:
                    items_to_remove.append(d)
            except Exception:
                pass
                
    for item in items_to_remove:
        board.Remove(item)
    
    # 1. Component Analysis: Identify targets
    target_strings = [
        "UART", "JTAG", "DEBUG", "CONSOLE", "PROG", "ISP", "ICSP",
        "24C", "AT24C", "EEPROM",  # I2C EEPROM targets
        "W25Q", "MX25L", "SPI",    # SPI Flash targets
        "TEST"                     # Test pads
    ]
    suspicious_components = []
    
    
    for fp in board.GetFootprints():
        ref = fp.GetReference().upper()
        val = fp.GetValue().upper()
        
        is_suspicious = False
        
        # Explicitly catch Test Points (e.g. "TP1", "TP23") without false flagging "TPA3116"
        if ref.startswith("TP") and len(ref) > 2 and ref[2:].isdigit():
            is_suspicious = True
            
        if not is_suspicious:
            for target in target_strings:
                if target in ref or target in val:
                    is_suspicious = True
                    break
        
        # DEEP SCAN: If the component isn't named suspiciously, check its individual pins (Pads)
        # Find generic headers that happen to be wired into sensitive debug data lines!
        if not is_suspicious:
            sensitive_nets = [
                "TX", "RX", "TXD", "RXD", "SWDIO", "SWCLK", 
                "MISO", "MOSI", "TCK", "TMS", "TDI", "TDO",
                "SDA", "SCL", "I2C", "DBG", "PROG", "BOOT", "VPP"
            ]
            for pad in fp.Pads():
                net_name = pad.GetNetname().upper()
                if net_name:  # If the pad is actually connected to a copper wire
                    for sn in sensitive_nets:
                        # Use regex word boundaries (\b) to perfectly match "TX" or "/TX" 
                        # but completely ignore false positives like "MATRIX"
                        if re.search(rf'\b{sn}\b', net_name) or fp.GetValue().startswith("CONN"):
                            is_suspicious = True
                            # Change the label so the report tells the user WHY it was flagged!
                            fp.SetValue(f"Generic Header -> {sn} Net")
                            break
                if is_suspicious:
                    break
                    
        if is_suspicious:
            suspicious_components.append(fp)
            
    # 2. Identify Edge.Cuts boundary segments
    edge_layer = board.GetLayerID("Edge.Cuts")
    edge_shapes = []
    for drawing in board.GetDrawings():
        if drawing.GetLayer() == edge_layer:
            edge_shapes.append(drawing)
            
    if not edge_shapes:
        if headless:
            print("[WARNING] No Edge.Cuts drawings found! Please define a board outline.")
            sys.exit(0)
        else:
            wx.MessageBox("No Edge.Cuts drawings found! Please define a board outline.", "eSim Security Linter", wx.OK | wx.ICON_WARNING)
        return

    # 3. Spatial Logic & Risk Evaluation
    findings = []
    user_drawings_layer = board.GetLayerID("User.Drawings")
    markers_to_add = []
    
    # Determine the shape type constant for lines
    shape_type = getattr(pcbnew, 'SHAPE_SEGMENT', getattr(pcbnew, 'SHAPE_T_SEGMENT', getattr(pcbnew, 'S_SEGMENT', 0)))
    
    for fp in suspicious_components:
        pos = fp.GetPosition()
        min_dist_iu = float('inf')
        closest_direction = "Unknown"
        
        for shape in edge_shapes:
            try:
                box = shape.GetBoundingBox()
                left, right = box.GetX(), box.GetRight()
                top, bottom = box.GetY(), box.GetBottom()
                
                TL = pcbnew.VECTOR2I(left, top)
                TR = pcbnew.VECTOR2I(right, top)
                BL = pcbnew.VECTOR2I(left, bottom)
                BR = pcbnew.VECTOR2I(right, bottom)
                
                distances = [
                    (distance_to_segment(pos, TL, TR), "Top"),
                    (distance_to_segment(pos, BL, BR), "Bottom"),
                    (distance_to_segment(pos, TL, BL), "Left"),
                    (distance_to_segment(pos, TR, BR), "Right")
                ]
                
                best_d, best_dir = min(distances, key=lambda x: x[0])
                
                if best_d < min_dist_iu:
                    min_dist_iu = best_d
                    closest_direction = best_dir
                    
            except Exception:
                pass
                
        # Convert Internal Units to mm
        min_dist_mm = min_dist_iu / pcbnew.FromMM(1)
        
        if min_dist_mm < crit_threshold:
            risk = "CRITICAL SECURITY RISK"
        elif min_dist_mm < warn_threshold:
            risk = "SECURITY WARNING"
        else:
            risk = "SAFE"
            
        findings.append(f"[{risk}] {fp.GetReference()} '{fp.GetValue()}' is {min_dist_mm:.2f} mm from the {closest_direction} edge")
        
        # 4. Visual Feedback: Draw 2mm Red "X" if vulnerable (CRITICAL or WARNING implies distance < warn_threshold)
        if min_dist_mm < warn_threshold:
            fp.SetSelected()
            
            cross_size = int(pcbnew.FromMM(1.0)) # 1mm from center = 2mm total width
            
            line1 = pcbnew.PCB_SHAPE(board)
            line1.SetShape(pcbnew.SHAPE_T_SEGMENT)
            line1.SetStart(pcbnew.VECTOR2I(int(pos.x - cross_size), int(pos.y - cross_size)))
            line1.SetEnd(pcbnew.VECTOR2I(int(pos.x + cross_size), int(pos.y + cross_size)))
            line1.SetLayer(user_drawings_layer)
            line1.SetWidth(int(pcbnew.FromMM(0.3)))
            markers_to_add.append(line1)
            
            line2 = pcbnew.PCB_SHAPE(board)
            line2.SetShape(pcbnew.SHAPE_T_SEGMENT)
            line2.SetStart(pcbnew.VECTOR2I(int(pos.x - cross_size), int(pos.y + cross_size)))
            line2.SetEnd(pcbnew.VECTOR2I(int(pos.x + cross_size), int(pos.y - cross_size)))
            line2.SetLayer(user_drawings_layer)
            line2.SetWidth(int(pcbnew.FromMM(0.3)))
            markers_to_add.append(line2)

    # 5. EMFI Trace Routing Analysis
    sensitive_nets = [
        "TX", "RX", "TXD", "RXD", "SWDIO", "SWCLK", 
        "MISO", "MOSI", "TCK", "TMS", "TDI", "TDO",
        "SDA", "SCL", "I2C", "DBG", "PROG", "BOOT", "VPP"
    ]
    
    for track in board.GetTracks():
        net_name = "SWDIO"
        if not net_name: continue
        
        is_sensitive_trace = False
        for sn in sensitive_nets:
            if re.search(rf'\b{sn}\b', net_name):
                is_sensitive_trace = True
                break
                
        if not is_sensitive_trace: continue
        
        # Check track coordinates against edge 
        start_pos = track.GetStart()
        end_pos = track.GetEnd()
        
        min_dist_iu = float('inf')
        closest_direction = "Unknown"
        worst_pos = start_pos
        
        for shape in edge_shapes:
            try:
                box = shape.GetBoundingBox()
                left, right = box.GetX(), box.GetRight()
                top, bottom = box.GetY(), box.GetBottom()
                
                TL = pcbnew.VECTOR2I(left, top)
                TR = pcbnew.VECTOR2I(right, top)
                BL = pcbnew.VECTOR2I(left, bottom)
                BR = pcbnew.VECTOR2I(right, bottom)
                
                for p in [start_pos, end_pos]:
                    distances = [
                        (distance_to_segment(p, TL, TR), "Top", p),
                        (distance_to_segment(p, BL, BR), "Bottom", p),
                        (distance_to_segment(p, TL, BL), "Left", p),
                        (distance_to_segment(p, TR, BR), "Right", p)
                    ]
                    
                    best_d, best_dir, best_p = min(distances, key=lambda x: x[0])
                    
                    if best_d < min_dist_iu:
                        min_dist_iu = best_d
                        closest_direction = best_dir
                        worst_pos = best_p
            except Exception:
                pass
        
        min_dist_mm = min_dist_iu / pcbnew.FromMM(1)
        if min_dist_mm < warn_threshold:
            risk = "CRITICAL SECURITY RISK" if min_dist_mm < crit_threshold else "SECURITY WARNING"
            findings.append(f"[{risk}] EMFI Trace '{net_name}' routed {min_dist_mm:.2f} mm from the {closest_direction} edge (Glitch Vuln!)")
            track.SetSelected()
            
            # Draw marker exactly on the part of the track that is vulnerable
            cross_size = int(pcbnew.FromMM(1.0))
            line1 = pcbnew.PCB_SHAPE(board)
            line1.SetShape(pcbnew.SHAPE_T_SEGMENT)
            line1.SetStart(pcbnew.VECTOR2I(int(worst_pos.x - cross_size), int(worst_pos.y - cross_size)))
            line1.SetEnd(pcbnew.VECTOR2I(int(worst_pos.x + cross_size), int(worst_pos.y + cross_size)))
            line1.SetLayer(user_drawings_layer)
            line1.SetWidth(int(pcbnew.FromMM(0.3)))
            markers_to_add.append(line1)
            
            line2 = pcbnew.PCB_SHAPE(board)
            line2.SetShape(pcbnew.SHAPE_T_SEGMENT)
            line2.SetStart(pcbnew.VECTOR2I(int(worst_pos.x - cross_size), int(worst_pos.y + cross_size)))
            line2.SetEnd(pcbnew.VECTOR2I(int(worst_pos.x + cross_size), int(worst_pos.y - cross_size)))
            line2.SetLayer(user_drawings_layer)
            line2.SetWidth(int(pcbnew.FromMM(0.3)))
            markers_to_add.append(line2)

    for m in markers_to_add:
        board.Add(m)
        
    pcbnew.Refresh()

    if not findings:
        if headless:
            print("[PASS] No vulnerabilities found! Board passed all security checks.")
            sys.exit(0)
        else:
            wx.MessageBox("No vulnerabilities found! Board passed all security checks.", "eSim Security Audit Passed", wx.OK | wx.ICON_INFORMATION)
        return

    criticals = [f.replace("[CRITICAL SECURITY RISK] ", "") for f in findings if "CRITICAL" in f]
    warnings = [f.replace("[SECURITY WARNING] ", "") for f in findings if "WARNING" in f]
    safes = [f.replace("[SAFE] ", "") for f in findings if "SAFE" in f]
    

    if headless:
        print("\n================ eSIM SECURITY AUDIT ================")
        if criticals:
            print("⛔ CRITICAL RISKS:")
            for c in criticals: print(f"   • {c}")
        if warnings:
            print("⚠️ WARNINGS:")
            for w in warnings: print(f"   • {w}")
        if safes:
            print("✅ SECURE:")
            for s in safes: print(f"   • {s}")
        print("=====================================================\n")
        
        if criticals or warnings:
            print("[FAIL] Security Audit Failed. Halting CI/CD Pipeline.")
            sys.exit(1)
        else:
            print("[PASS] Security Audit Passed.")
            sys.exit(0)
    msg_parts = []
    if criticals:
        msg_parts.append("⛔ CRITICAL RISKS:\n" + "\n".join(f"   • {c}" for c in criticals))
    if warnings:
        msg_parts.append("⚠️ WARNINGS:\n" + "\n".join(f"   • {w}" for w in warnings))
    if safes:
        msg_parts.append("✅ SECURE:\n" + "\n".join(f"   • {s}" for s in safes))
        
    ext_msg = "\n\n".join(msg_parts)
    
    if criticals or warnings:
        title = "eSim Security Audit Failed"
        main_text = f"The security linter found {len(criticals)} critical risks and {len(warnings)} warnings."
        icon = wx.ICON_WARNING
    else:
        title = "eSim Security Audit Passed"
        main_text = "All requested debug interfaces are safely placed."
        icon = wx.ICON_INFORMATION
        
    dlg = wx.MessageDialog(None, main_text, title, wx.OK | icon)
    dlg.SetExtendedMessage(ext_msg)
    dlg.ShowModal()
    dlg.Destroy()
    
    return not (criticals or warnings)
if __name__ == "__main__":
    app = wx.App(False)  # Suppress C++ wxWidgets "traits" missing errors in headless mode
    import argparse
    parser = argparse.ArgumentParser(description="eSim Hardware Security Linter CLI")
    parser.add_argument("--board", required=True, help="Path to the .kicad_pcb file")
    parser.add_argument("--crit", type=float, default=5.0, help="Critical distance threshold (mm)")
    parser.add_argument("--warn", type=float, default=15.0, help="Warning distance threshold (mm)")
    args = parser.parse_args()
    
    if not os.path.exists(args.board):
        print(f"Error: Board file '{args.board}' not found.")
        sys.exit(1)
        
    print(f"Starting Headless Audit on: {args.board}")
    try:
        board = pcbnew.LoadBoard(args.board)
        
        crit = args.crit
        warn = args.warn
        config = load_organization_config(args.board)
        if config:
            print("[INFO] Found esim_security.json! Enforcing organization rules.")
            crit = config.get("critical_threshold_mm", crit)
            warn = config.get("warning_threshold_mm", warn)
            print(f"       -> Critical: {crit} mm | Warning: {warn} mm")
            
        audit_board(board, crit_threshold=crit, warn_threshold=warn, headless=True)
    except Exception as e:
        print(f"[ERROR] Failed to load board: {e}")
        sys.exit(1)
