# eSim Simulation Bridge — KiCad Plugin Suite

![Platform](https://img.shields.io/badge/platform-linux-blue)
![KiCad](https://img.shields.io/badge/KiCad-8%2F9-green)
![License](https://img.shields.io/badge/license-GPL--3.0-orange)
![FOSSEE](https://img.shields.io/badge/FOSSEE-IIT%20Bombay-red)

A single KiCad plugin consisting of two companion files that together eliminate the entire manual workflow of converting a KiCad schematic into a runnable eSim/ngspice simulation — and add a full-featured waveform analysis suite on top.

**Developed for:** FOSSEE Semester Long Internship Spring 2026 — Task 6: KiCad Plugin Development
**Author:** Imran Farhat
**Institution:** IIT Bombay (FOSSEE)
**Contact:** imranfarhat.official@gmail.com | contact-esim@fossee.in

---

## Plugins Files

### eSim-BRIDGE (`esim_bridge.py`) — v2.1.0

One-click simulation bridge. Converts KiCad schematics to valid SPICE format, runs ngspice directly from within KiCad, and launches eSim with the project ready to simulate. Includes a full interactive waveform viewer with FFT, Bode plot, cursor, parametric sweep, and measurement tools.

### eSim-SPICE (`esim_spice_linker.py`) — v1.0.0

Automatic SPICE model linker. Scans eSim's built-in open-source library (1,300+ files) and automatically resolves and injects SPICE models for every active component in the schematic. Eliminates all manual model selection.

Both files together form **one plugin** installed as a single KiCad package.

---

## What They Do Together

Without these plugins, simulating a KiCad circuit in eSim requires **26 manual steps** taking 10–15 minutes — and must be repeated every time a component value changes.

With eSim-BRIDGE + eSim-SPICE, the workflow is:

1. Open KiCad → draw schematic → save (`Ctrl+S`)
2. Switch to PCB Editor → click the **eSim Bridge** toolbar icon
3. Select analysis type and parameters → eSim-SPICE shows Model Coverage Report
4. Click **Convert →** → review SPICE preview → click **Run with ngspice →**
5. Interact with the waveform viewer: FFT, Bode plot, cursor, measurements, parametric sweep

**Total: 5 steps in approximately 30 seconds.**

---

## Analysis Types

| Analysis | Parameters | Result |
|---|---|---|
| Transient | Start, Step, Stop time | Time-domain waveform |
| AC Sweep | Scale, Start/Stop freq, Points | Frequency response |
| DC Sweep | Source, Start, Stop, Step | DC transfer curve |
| Operating Point | None | DC node voltages (popup) |
| Noise | Output node, Source, Freq range | inoise / onoise values |
| Transfer Function | Output node, Input source | Gain + impedances (popup) |
| Sensitivity | Output variable | Component impact ranking (popup) |

---

## Waveform Viewer Features

After running ngspice, the interactive waveform viewer opens with:

| Button | Function |
|---|---|
| 📊 Show FFT | Frequency spectrum of transient data via numpy FFT |
| 📈 Bode Plot | Dual-pane gain (dB) + phase (degrees) for AC analysis |
| 📏 Measure | RMS, Average, Peak, Min, Max, Frequency via zero-crossing |
| 🖱 Cursor | Interactive crosshair with auto-scaled time/frequency readout |
| 🔁 Sweep | Parametric sweep — vary one R/C/L value, overlay results |
| 💾 Save PNG | Save waveform to image file |
| ⟳ Refresh | Reload .raw file |

---

## Preflight Netlist Checker

Before every simulation, the plugin automatically checks:

- Ground node (GND/0) exists in the schematic
- No floating nodes (pins connected to only one component)
- No voltage source short circuits (two sources sharing both terminals)
- No orphan components (components with zero net connections)
- No DC path violations (nets connected only through capacitors)
- `.spiceinit` file created/updated with `set ngbehavior=ps` for PSPICE model compatibility

---

## KiCad-to-Ngspice Dialog (6 Tabs)

Mirrors eSim's own KicadToNgspice window:

| Tab | Purpose |
|---|---|
| Analysis | Select analysis type and parameters |
| Source Details | Configure V/I source waveforms (SIN, PULSE, PWL, EXP, AC, DC) |
| Ngspice Model | Set parameters for U-prefix behavioral models via eSim's modelParamXML |
| Device Modeling | Add external .lib files for Q/D/J/M/S components |
| Subcircuits | Select subcircuit directories for X-prefix components |
| Microcontroller | NGHDL status, .hex file picker, previous values restore |

---

## eSim-SPICE Model Resolution (5-Tier Search)

For every active component, eSim-SPICE searches in priority order:

1. **eSim `deviceModelLibrary/`** — 61 device model categories
2. **eSim `SubcircuitLibrary/`** — 586+ subcircuit folders
3. **User's `~/.esim-bridge/models/`** — drop any `.lib`/`.sub` file here
4. **Known equivalents** — re-searches eSim with compatible substitutes
5. **Textbook parameters** — last-resort `.model` card from published values

Model status codes in the coverage report:

| Status | Meaning |
|---|---|
| FOUND | Exact match in eSim's open-source library |
| EQUIV | Pin-compatible substitute used |
| TEXTBK | Generated from textbook parameters (educational use) |
| MISSING | No model found anywhere — MCU/mic/unknown IC |
| OK | Passive or source — no model needed |

---

## Supported Components

| KiCad Prefix | Component | SPICE Handling |
|---|---|---|
| R | Resistor | Direct value (with space/string sanitization) |
| C | Capacitor | Direct value |
| L | Inductor | Direct value |
| V (VSIN/PULSE/DC/AC/EXP/PWL) | Voltage source | Full Sim.Type + Sim.Params support |
| I | Current source | DC value |
| D / LED | Diode / LED | Auto-model from eSim library |
| Q | BJT Transistor | Auto-model NPN/PNP from eSim library |
| M | MOSFET | Auto-model NMOS/PMOS from eSim library |
| J | JFET | Auto-model NJF/PJF |
| U / X | IC / Op-amp / Subcircuit | eSim SubcircuitLibrary search → textbook fallback |
| BT | Battery | Converted to DC voltage source |
| MK | Microphone | Approximated as 10mV AC source at 1kHz |
| SW | Switch | Modeled as 1Ω resistor (closed state) |
| F | Fuse | Modeled as 0.01Ω resistor |

---

## Built-in Model Library (47+ Components)

| Category | Models |
|---|---|
| Diodes | 1N4148, 1N4007, 1N4001–4004, 1N5817/5819, Zener variants, LED (red/green/blue) |
| NPN BJTs | 2N2222, 2N3904, BC547/B, BC548, 2N2219, TIP31 |
| PNP BJTs | 2N3906, 2N2907, BC557, BC558, TIP32 |
| N-MOSFET | IRF540/N, IRF3205, IRF830, 2N7000, 2N7002, BS170 |
| P-MOSFET | IRF9540, BS250 |
| Op-Amps | LM741, UA741, LM358, LM324 (simplified subcircuits) |
| Timers | NE555 |
| Regulators | 7805, 7812, 78L33 |

---

## System Requirements

| Software | Version | Notes |
|---|---|---|
| Ubuntu Linux | 24.04 LTS | Tested on 24.04 |
| KiCad | 8.0 or 9.x | Must include `kicad-cli` |
| eSim | 2.5 | Must be at `~/Downloads/eSim-2.5/` |
| ngspice | 35+ | Bundled with eSim |
| Python | 3.10+ | Included with Ubuntu |

### Supported Environments

| Environment | Status |
|---|---|
| Ubuntu 24.04 in VirtualBox (Windows host) | ✅ Fully tested — recommended |
| Native Ubuntu 24.04 | ✅ Works perfectly |
| WSL 2 with WSLg (Windows 11) | ⚠️ May work |
| macOS | ❌ eSim 2.5 is Linux-only |

---

## Installation

### Step 1 — Install KiCad 8.0

```bash
sudo apt update && sudo apt install -y kicad
kicad-cli --version   # Expected: Application: kicad-cli 8.0.x
```

### Step 2 — Install eSim 2.5

```bash
cd ~/Downloads
wget https://static.fossee.in/esim/installation-files/eSim-2.5.zip
unzip eSim-2.5.zip && cd eSim-2.5
chmod +x install-eSim.sh && ./install-eSim.sh --install

# Verify
ls ~/Downloads/eSim-2.5/src/frontEnd/Application.py
ls ~/.esim/env/bin/python3
```

### Step 3 — Clone and Install the Plugin

```bash
cd ~
git clone https://github.com/ImranFarhat01/KiCad-Plugin-ImranFarhat.git
cp -r ~/KiCad-Plugin-ImranFarhat/KiCad_Plugin \
    ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge
```

### Step 4 — Fix Username ⚠️ MANDATORY

```bash
sed -i "s/imran-farhat/$(whoami)/g" \
    ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/esim_bridge.py

# Verify — must return NO output
grep "imran-farhat" \
    ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/esim_bridge.py
```

### Step 5 — Fix `__init__.py` and Create Workspace

```bash
echo "from .esim_bridge import ESimBridgePlugin" > \
    ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/__init__.py

mkdir -p ~/eSim-Workspace
echo '{"/home/'$(whoami)'/eSim-Workspace/esim_bridge_project": []}' \
    > ~/eSim-Workspace/.projectExplorer.txt
```

### Step 6 — Restart KiCad and Verify

Open KiCad → PCB Editor → look for the **eSim Bridge** icon in the toolbar.
If not visible: **Tools → External Plugins → Refresh Plugins**

---

## One-Shot Install Script

```bash
sudo apt update && sudo apt install -y kicad git

cd ~/Downloads
wget https://static.fossee.in/esim/installation-files/eSim-2.5.zip
unzip eSim-2.5.zip && cd eSim-2.5
chmod +x install-eSim.sh && ./install-eSim.sh --install

cd ~ && git clone https://github.com/ImranFarhat01/KiCad-Plugin-ImranFarhat.git
cp -r ~/KiCad-Plugin-ImranFarhat/KiCad_Plugin \
    ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge

sed -i "s/imran-farhat/$(whoami)/g" \
    ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/esim_bridge.py

echo "from .esim_bridge import ESimBridgePlugin" > \
    ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/__init__.py

mkdir -p ~/eSim-Workspace
echo '{"/home/'$(whoami)'/eSim-Workspace/esim_bridge_project": []}' \
    > ~/eSim-Workspace/.projectExplorer.txt

echo "Installation complete — launch KiCad with: kicad"
```

---

## Demo Circuit (Recommended for Testing)

Use a voltage divider with a sine source — the mentor-approved test circuit:

| Component | Value |
|---|---|
| R1 | 10kΩ |
| R2 | 10kΩ |
| V1 (VSIN) | Sim.Type=SIN, Sim.Params: dc=0 ampl=1 f=1k ac=1 |

Run **Transient Analysis**: Step=0.1ms, Stop=10ms

Expected: output node shows sine wave at 0.5V peak (half of 1V input).

To test Sensitivity Analysis, set V1 dc=1 to provide a DC operating point.

---

## File Structure

```
KiCad_Plugin/
├── esim_bridge.py          # eSim-BRIDGE v2.1.0 — main plugin
├── esim_spice_linker.py    # eSim-SPICE v1.0.0 — model auto-linker
├── icon.png                # Toolbar icon
└── __init__.py             # Package entry point

Generated project files (~/eSim-Workspace/esim_bridge_project/):
├── esim_bridge_project.cir       # Pure SPICE netlist
├── esim_bridge_project.cir.out   # SPICE with .control block for ngspice
├── esim_bridge_project.proj      # eSim project marker
├── analysis                      # Analysis command for eSim plotter
├── plot_data_v.txt               # Voltage simulation results
├── plot_data_i.txt               # Current simulation results
└── images/                       # Required by eSim
```

---

## Known Limitations

See [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) for the complete list.

Key limitations:
- **MCUs (ATtiny85, Arduino, etc.)**: No SPICE models exist industry-wide. MISSING status is correct and expected.
- **74xx digital ICs**: ngspice is an analog simulator; digital logic cannot be meaningfully simulated.
- **Condenser microphones**: No standard SPICE model exists. Approximated as 10mV AC source.
- **UTF-8 popup (cosmetic)**: A known eSim 2.5 issue — dismiss and re-simulate.
- **Linux only**: eSim 2.5 is Linux-only.

---

## Useful Commands

```bash
# View generated SPICE file
cat ~/eSim-Workspace/esim_bridge_project/esim_bridge_project.cir.out

# Follow plugin log in real time
tail -f ~/.local/share/kicad/esim_bridge.log

# Run simulation manually
ngspice -b ~/eSim-Workspace/esim_bridge_project/esim_bridge_project.cir.out

# Launch eSim manually
cd ~/Downloads/eSim-2.5/src/frontEnd
PYTHONPATH=/home/$(whoami)/Downloads/eSim-2.5/src \
    ~/.esim/env/bin/python3 Application.py

# Delete stale .raw file (if UTF-8 popup persists)
rm -f ~/eSim-Workspace/esim_bridge_project/esim_bridge_project.raw

# Clear plugin cache after code changes
rm -rf ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/__pycache__
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Plugin not in toolbar | Tools → External Plugins → Refresh Plugins |
| `esim_bridge.py` is 0 bytes | Re-clone the repository |
| `__init__.py` empty or wrong | `echo "from .esim_bridge import ESimBridgePlugin" > __init__.py` |
| eSim not found | `ls ~/Downloads/eSim-2.5/src/frontEnd/Application.py` |
| Paths say `imran-farhat` | Run Step 4 from installation |
| eSim blank icons in VirtualBox | Set display to VMSVGA + 256 MB Video Memory |
| UTF-8 popup | Dismiss and re-simulate (cosmetic only) |
| Flat graph at 0V | Add VSIN with Sim.Type=SIN and Sim.Params set |
| Sensitivity all zeros | Set V1 dc=1 in Source Details tab (DC operating point required) |

---

## License

GPL-3.0 — Free to use, modify, and distribute with attribution.

---

*Developed as part of FOSSEE Semester Long Internship Spring 2026, IIT Bombay.*
*Task 6: KiCad Plugin Development*
