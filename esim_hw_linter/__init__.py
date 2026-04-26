from .linter import ESimHardwareLinter

try:
    ESimHardwareLinter().register()
except Exception as e:
    import pcbnew
    import wx
    wx.LogMessage(f"Failed to register eSim Hardware Linter: {e}")
