# Quick Reference - eSim Simulation Bridge

*eSim Simulation Bridge v1.0.0 | KiCad 8.0 + eSim 2.5 + ngspice 42 | FOSSEE IIT Bombay | May 2026*

---

## 5-Step Simulation Workflow

```
1. KiCad → draw schematic → Ctrl+S (save)
2. Switch to PCB Editor → click eSim Simulation Bridge toolbar icon
3. Select analysis type and parameters in the 6-tab dialog
4. Click Convert → Auto-Linker shows Model Coverage Report → Continue
5. Click "Run with ngspice →" → interact with waveform viewer
```

> The plugin button is in the **PCB Editor** toolbar, NOT the Schematic Editor.

---

## Analysis Types Quick Reference

| Analysis | Key Parameters | Result |
|---|---|---|
| Transient | Start=0, Step=0.1ms, Stop=10ms | Waveform viewer |
| AC Sweep | Scale=dec, 1Hz-1MEGHz, 100 pts | Waveform viewer + Bode plot |
| DC Sweep | Source, Start, Stop, Step | Waveform viewer |
| Operating Point | (none) | DC node voltages popup |
| Noise | Output node, Input source, Freq range | inoise / onoise popup |
| Transfer Function | Output node, Input source | Gain + impedances popup |
| Sensitivity | Output variable (e.g. `V(vmid)`) | Component impact ranking popup |

> **Note:** Pole-zero analysis is not available - confirmed ngspice 42 bug in `pzan.c` (KLU solver returns `E_UNSUPP`).

---

## Waveform Viewer Buttons (NgspiceWaveformViewer)

| Button | Available For | What It Does |
|---|---|---|
| Show FFT | Transient only | Frequency spectrum via `numpy.fft.rfft`; toggle between spectrum and waveform |
| Bode Plot | AC only | Dual-pane: gain (dB) + phase (°) vs log frequency axis |
| Cursor | All | Left-click = cursor 1 (red), right-click = cursor 2 (blue); auto-scaled time/voltage annotation |
| Sweep | Transient only | Vary any R/C/L across a range (2-10 steps); overlays all results with distinct colours |
| Save PNG | All | Export current figure at 150 DPI |
| Refresh | All | Reload `.raw` file and redraw |
| Open Python Plot | All | Launch PyQt5 `plotWindow` (ngspiceSimulation package) as a separate window |

---

## Python Plot Window (plotWindow - PyQt5)

Launched via **Open Python Plot** button in the Simulation Ready Dialog:

| Feature | Description |
|---|---|
| Three-panel layout | Waveform list (left) + matplotlib figure (centre) + collapsible controls (right) |
| Digital Timing View | Two-level digital waveforms stacked vertically with adjustable logic threshold |
| Cursor measurements | Δt and implied frequency between cursor 1 and cursor 2 |
| Multimeter | RMS computed with Python `Decimal` type (5 sig. figs.) - stays on top |
| Function plotting | Ratio mode (`A vs B`) or arbitrary NumPy expression (e.g. `v(in) - v(out)`) |
| AC logarithmic mode | Frequency response on log-x axis |
| Export | PNG or SVG at 150 DPI; per-trace style persisted to `~/.pythonPlotting/config.json` |

---

## VSIN Source Setup in KiCad Schematic Editor

Double-click V1 → Edit → Simulation Model → set:

```
Simulation type:  SPICE model
Device:           Sine (SIN)
Sim.Params:       dc=0 ampl=1 f=1k ac=1
```

> For **Sensitivity Analysis** - set `dc=1` to provide a DC operating point. Sensitivity requires a non-zero DC bias.

---

## Source Types in Source Details Tab

| Type | Key Fields |
|---|---|
| `dc` | DC value |
| `sine` | Offset, Amplitude, Frequency, Delay, Damping factor |
| `pulse` | V1, V2, Td, Tr, Tf, PW, Period |
| `ac` | Amplitude, Phase |
| `pwl` | Time-value pairs (t1 v1 t2 v2 ...) |
| `exp` | V1, V2, Rise delay, Rise tau, Fall delay, Fall tau |

---

## Model Status Codes

| Code | Colour | Meaning | Action Needed? |
|---|---|---|---|
| FOUND | Green | Exact match in eSim library | None |
| EQUIV | Blue | Pin-compatible substitute used | None |
| TEXTBK | Amber | Generated from textbook parameters | None (sim will run) |
| MISSING | Red | No model found - MCU / mic / unknown IC | Expected for MCUs |
| OK | Grey | Passive (R/C/L) or source (V/I) - no model needed | None |

---

## Preflight Checker - What It Catches

| Check | Blocking? | Error If... |
|---|---|---|
| Ground node | Yes | No GND/0 net in schematic |
| Floating nodes | Yes | A net has only one pin connected |
| Voltage source short | Yes | Two sources share both terminals |
| Orphan components | Warning | A component has zero net connections |
| DC path violation | Warning | A net is connected only through capacitors |
| `.spiceinit` | Silent | Auto-creates/updates `set ngbehavior=ps` |

---

## Validated Demo Circuits

### Three-Phase Bridge Rectifier (Recommended for Full Demo)

| Component | Value |
|---|---|
| D1-D6 | 1N4148 (six-pulse bridge) |
| L1 | 10 mH |
| C1 | 470 µF |
| R1 | 100 Ω (or 10 MΩ in SPICE) |
| V1 | SIN(0 325 50 0 0 0) - Phase A, 0° |
| V2 | SIN(0 325 50 0 0 120) - Phase B, 120° |
| V3 | SIN(0 325 50 0 0 240) - Phase C, 240° |

**Transient:** Start=0, Step=0.1ms, Stop=100ms  
**Expected:** v(out) average ≈ 49.86 V, ripple frequency ≈ 149.93 Hz (6-pulse rectification)

### Voltage Divider (Quickest Test)

| Component | Value |
|---|---|
| R1 | 10 kΩ |
| R2 | 10 kΩ |
| V1 (VSIN) | dc=0 ampl=1 f=1k ac=1 |

**Transient:** Step=0.1ms, Stop=10ms → output shows 0.5 V peak sine  
**Transfer Function:** gain = 5.000e-01, Zin = 20 kΩ, Zout = 5 kΩ  
**FFT:** single spike at 1 kHz, magnitude ≈ 0.5 V  
**Sensitivity (with dc=1):** v1 = 5.00e-01, r1 negative, r2 positive

---

## Key File Paths

| Item | Path |
|---|---|
| Plugin folder | `~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/` |
| Plugin log | `~/.local/share/kicad/esim_bridge.log` |
| Generated SPICE | `~/eSim-Workspace/esim_bridge_project/esim_bridge_project.cir.out` |
| Binary waveform | `~/eSim-Workspace/esim_bridge_project/esim_bridge_project.raw` |
| External models | `~/.esim-bridge/models/` |
| Previous dialog values | `~/.esim-bridge/KicadToNgspice_Previous_Values.xml` |
| MCU hex paths | `~/.esim-bridge/mcu_previous_values.xml` |
| Python plot config | `~/.pythonPlotting/config.json` |
| eSim workspace | `~/eSim-Workspace/esim_bridge_project/` |

---

## Useful Terminal Commands

```bash
# View the generated SPICE file
cat ~/eSim-Workspace/esim_bridge_project/esim_bridge_project.cir.out

# Watch plugin log live
tail -f ~/.local/share/kicad/esim_bridge.log

# Run ngspice manually (without the plugin)
ngspice -b ~/eSim-Workspace/esim_bridge_project/esim_bridge_project.cir.out

# Launch eSim manually
cd ~/Downloads/eSim-2.5/src/frontEnd
PYTHONPATH=/home/$(whoami)/Downloads/eSim-2.5/src \
    ~/.esim/env/bin/python3 Application.py

# Delete stale .raw file (fixes UTF-8 popup in eSim)
rm -f ~/eSim-Workspace/esim_bridge_project/esim_bridge_project.raw

# Clear plugin bytecode cache (MANDATORY after any code change)
rm -rf ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/__pycache__

# Refresh plugin in KiCad without full restart
# KiCad → Tools → External Plugins → Refresh Plugins

# Add custom SPICE models (drop .lib / .sub files here)
ls ~/.esim-bridge/models/

# Check plugin is loading correctly
cat ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/__init__.py
# Must show: from .esim_bridge import ESimBridgePlugin
```

---

## Installation Verification Checklist

```bash
kicad-cli --version              # Should show 8.0.x
ngspice --version                # Should show ngspice-42
ls ~/.esim/env/bin/python3       # Must exist
ls ~/Downloads/eSim-2.5/src/frontEnd/Application.py    # Must exist

# Plugin files
ls ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/
# Must include: esim_bridge.py, esim_spice_linker.py, icon.png,
#               __init__.py, configuration/, ngspiceSimulation/

cat ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/__init__.py
# Must show: from .esim_bridge import ESimBridgePlugin
```

---

## Common Fixes

| Problem | Fix |
|---|---|
| Plugin not in toolbar | Tools → External Plugins → Refresh Plugins |
| eSim blank icons (VirtualBox) | VM Settings → Display → VMSVGA + 256 MB + 3D Acceleration |
| UTF-8 popup in eSim | Dismiss + re-simulate - cosmetic only, known eSim 2.5 bug |
| Flat graph at 0 V | Check that V1 has `Sim.Type=SIN` and `Sim.Params` properly set in KiCad |
| Sensitivity all zeros | Set `dc=1` on voltage source in Source Details tab |
| ngspice not found | `sudo apt install ngspice` |
| `libngspice-kicad` conflict | `sudo dpkg --remove --force-depends ngspice && sudo apt install ngspice -y` |
| Code changes not visible | `rm -rf ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/__pycache__` then restart KiCad |
| Python plot window doesn't open | Check `ngspiceSimulation/` folder exists in plugin directory |
| Parametric sweep residual values | Reset component values in schematic before running AC analysis |

---

## Component Prefix Reference

| Prefix | Type | SPICE Handling |
|---|---|---|
| `R` | Resistor | Direct value (sanitised; fallback to `1k`) |
| `C` | Capacitor | Direct value |
| `L` | Inductor | Direct value |
| `V` | Voltage source | Full `Sim.Type` + `Sim.Params` support |
| `I` | Current source | DC value |
| `D` / LED | Diode / LED | Auto-model from eSim library |
| `Q` | BJT Transistor | Auto-model NPN/PNP from eSim library |
| `M` | MOSFET | Auto-model NMOS/PMOS from eSim library |
| `J` | JFET | Auto-model NJF/PJF |
| `U` / `X` | IC / Subcircuit | eSim SubcircuitLibrary search → textbook fallback |
| `BT` | Battery | Converted to DC voltage source |
| `MK` | Microphone | Approximated as 10 mV AC source at 1 kHz |
| `SW` | Switch | Modelled as 1 Ω resistor (closed state) |
| `F` | Fuse | Modelled as 0.01 Ω resistor |
| `T` | Transformer | Unsupported - add manual `.subckt` to `~/.esim-bridge/models/` |
