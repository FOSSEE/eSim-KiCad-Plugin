# Quick Reference - eSim Simulation Bridge

*eSim-BRIDGE v2.1.0 / eSim-SPICE v1.0.0 | FOSSEE IIT Bombay | May 2026*

---

## 5-Step Simulation Workflow

```
1. KiCad → draw schematic → Ctrl+S (save)
2. Switch to PCB Editor → click eSim Bridge toolbar icon
3. Select analysis type and parameters in the 6-tab dialog
4. Click Convert → → eSim-SPICE shows Model Coverage Report → Continue
5. Click "Run with ngspice →" → interact with waveform viewer
```

> The plugin button is in the **PCB Editor** toolbar, NOT the Schematic Editor.

---

## Analysis Types Quick Reference

| Analysis | Key Parameters | Result |
|---|---|---|
| Transient | Step=0.1ms, Stop=10ms | Waveform viewer |
| AC Sweep | dec, 1Hz-1MEGHz, 100pts | Waveform viewer |
| DC Sweep | V1, 0-5V, step 0.1 | Waveform viewer |
| Operating Point | (none) | DC voltages popup |
| Noise | output node, source, freq range | inoise/onoise values |
| Transfer Function | output node, input source | Gain + impedances popup |
| Sensitivity | output variable | Component ranking popup |

---

## Waveform Viewer Buttons

| Button | Shows For | What It Does |
|---|---|---|
| 📊 Show FFT | Transient | Frequency spectrum via numpy FFT |
| 📈 Bode Plot | AC | Dual-pane: gain (dB) + phase (°) |
| 📏 Measure | Transient | RMS, peak, average, frequency |
| 🖱 Cursor | All | Click-to-read voltage/time crosshair |
| 🔁 Sweep | Transient | Vary R/C/L, overlay results |
| 💾 Save PNG | All | Export waveform image |
| ⟳ Refresh | All | Reload .raw file |

---

## VSIN Source Setup in KiCad

Double-click V1 → Simulation Model → set:

```
Device type:  Sine
Sim.Params:   dc=0 ampl=1 f=1k ac=1
```

For Sensitivity Analysis - set `dc=1` to provide a DC operating point.

---

## Source Types Supported in Source Details Tab

| Type | Key Fields |
|---|---|
| dc | DC value |
| sine | Offset, Amplitude, Frequency, Delay, Damping |
| pulse | V1, V2, Td, Tr, Tf, PW, Period |
| ac | Amplitude, Phase |
| pwl | Time-value pairs (t1 v1 t2 v2 ...) |
| exp | V1, V2, Rise delay, Rise tau, Fall delay, Fall tau |

---

## Model Status Codes

| Code | Meaning | Action needed? |
|---|---|---|
| FOUND | Exact match in eSim library | None |
| EQUIV | Pin-compatible substitute used | None |
| TEXTBK | Generated from textbook parameters | None (sim will run) |
| MISSING | No model found - MCU/mic/unknown IC | Expected for MCUs |
| OK | Passive/source - no model needed | None |

---

## Preflight Checker - What It Catches

| Check | Error if... |
|---|---|
| Ground node | No GND/0 net in schematic |
| Floating nodes | A net has only one pin connected |
| Voltage source short | Two sources share both terminals |
| Orphan components | A component has no net connections |
| DC path violation | A net is connected only through capacitors |
| `.spiceinit` | Automatically creates/updates for PSPICE compatibility |

---

## Demo Circuit (Voltage Divider - Proven Test)

| Component | Value |
|---|---|
| R1 | 10k |
| R2 | 10k |
| V1 (VSIN) | dc=0 ampl=1 f=1k ac=1 |

Expected results:

- **Transient:** output node shows 0.5V peak sine wave
- **Transfer Function:** gain = 5.000000e-01, input impedance = 20k, output impedance = 5k
- **FFT:** single spike at 1kHz, magnitude ~0.5V
- **Sensitivity (with dc=1):** v1 = 5.00e-01, r1 negative, r2 positive

---

## Key File Paths

| Item | Path |
|---|---|
| Plugin folder | `~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/` |
| Plugin log | `~/.local/share/kicad/esim_bridge.log` |
| Generated SPICE | `~/eSim-Workspace/esim_bridge_project/esim_bridge_project.cir.out` |
| External models | `~/.esim-bridge/models/` |
| MCU hex paths | `~/.esim-bridge/mcu_previous_values.xml` |
| eSim workspace | `~/eSim-Workspace/esim_bridge_project/` |

---

## Useful Terminal Commands

```bash
# View the generated SPICE file
cat ~/eSim-Workspace/esim_bridge_project/esim_bridge_project.cir.out

# Watch plugin log live
tail -f ~/.local/share/kicad/esim_bridge.log

# Run ngspice manually
ngspice -b ~/eSim-Workspace/esim_bridge_project/esim_bridge_project.cir.out

# Launch eSim manually
cd ~/Downloads/eSim-2.5/src/frontEnd
PYTHONPATH=/home/$(whoami)/Downloads/eSim-2.5/src \
    ~/.esim/env/bin/python3 Application.py

# Delete stale .raw file (fixes UTF-8 popup)
rm -f ~/eSim-Workspace/esim_bridge_project/esim_bridge_project.raw

# Clear plugin cache (after code changes)
rm -rf ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/__pycache__

# Refresh plugin without KiCad restart
# KiCad → Tools → External Plugins → Refresh Plugins

# Add custom SPICE models (drop .lib files here)
ls ~/.esim-bridge/models/
```

---

## Installation Verification Checklist

```bash
kicad-cli --version                    # Should show 8.0.x
ngspice --version                      # Should show 35+
ls ~/.esim/env/bin/python3             # Must exist
ls ~/Downloads/eSim-2.5/src/frontEnd/Application.py   # Must exist

cat ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/__init__.py
# Must show: from .esim_bridge import ESimBridgePlugin

grep "imran-farhat" \
    ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/esim_bridge.py
# Must return NO output (no old username remaining)
```

---

## Common Fixes

| Problem | Fix |
|---|---|
| Plugin not in toolbar | Tools → External Plugins → Refresh Plugins |
| eSim blank icons (VirtualBox) | VM Settings → Display → VMSVGA + 256 MB + 3D acceleration |
| UTF-8 popup in eSim | Dismiss + re-simulate (cosmetic only, known eSim 2.5 bug) |
| Flat graph at 0V | Add VSIN with Sim.Type=SIN and Sim.Params properly set |
| Sensitivity all zeros | Set V1 dc=1 in Source Details tab |
| `imran-farhat` in paths | Run: `sed -i "s/imran-farhat/$(whoami)/g" esim_bridge.py` |
| ngspice not found | `sudo apt install ngspice` |
| `libngspice-kicad` conflict | `sudo dpkg --remove --force-depends ngspice && sudo apt install ngspice -y` |

---

## Component Prefix Reference

| Prefix | Type | SPICE Handling |
|---|---|---|
| R | Resistor | Direct value (sanitized) |
| C | Capacitor | Direct value |
| L | Inductor | Direct value |
| V | Voltage source | Sim.Type + Sim.Params |
| I | Current source | DC value |
| D | Diode/LED | Auto-model |
| Q | BJT | Auto-model NPN/PNP |
| M | MOSFET | Auto-model NMOS/PMOS |
| J | JFET | Auto-model NJF/PJF |
| U / X | IC / Subcircuit | eSim library search |
| BT | Battery | DC voltage source |
| MK | Microphone | 10mV AC source |
| SW | Switch | 1Ω resistor |
| F | Fuse | 0.01Ω resistor |
