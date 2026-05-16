# eSim Simulation Bridge

![Platform](https://img.shields.io/badge/platform-linux-blue)
![KiCad](https://img.shields.io/badge/KiCad-8.0-green)
![eSim](https://img.shields.io/badge/eSim-2.5-orange)
![ngspice](https://img.shields.io/badge/ngspice-42-yellow)
![License](https://img.shields.io/badge/license-GPL--3.0-red)
![FOSSEE](https://img.shields.io/badge/FOSSEE-IIT%20Bombay-darkred)

A single KiCad 8.0 action plugin that eliminates the entire manual workflow of converting a KiCad schematic into a runnable eSim/ngspice simulation - and adds a full-featured professional waveform analysis suite on top.

**Developed for:** FOSSEE Semester Long Internship Spring 2026 - eSim: KiCad Plugin Development  
**Author:** Imran Farhat, B.Tech CSE (AI/ML), VIT Bhopal University  
**Mentor:** Sumanto Kar (Eyantra698Sumanto), IIT Bombay  
**Principal Investigator:** Prof. Prabhu Ramachandran, IIT Bombay  
**Contact:** imranfarhat.official@gmail.com | contact-esim@fossee.in

---

## What Is This?

Without this plugin, simulating a KiCad circuit in eSim requires a lengthy manual process - exporting a netlist, opening eSim, creating a project, manually linking SPICE models for every active component, configuring analysis parameters, running ngspice, and switching to a separate plotter. This takes 10-15 minutes per schematic and must be repeated from scratch whenever a component value changes.

**With eSim Simulation Bridge, the workflow is:**

1. Open KiCad → draw schematic → save (`Ctrl+S`)
2. Switch to PCB Editor → click the **eSim Simulation Bridge** toolbar icon
3. Select analysis type and parameters in the 6-tab dialog → Auto-Linker shows Model Coverage Report
4. Click **Convert** → review SPICE preview → click **Run with ngspice**
5. Interact with the waveform viewer: FFT, Bode plot, cursor, parametric sweep

**Total: 5 steps in approximately 30 seconds.**

---

## Plugin Files

This is a **single KiCad action plugin** installed as a single package:

| File | Version | Role |
|---|---|---|
| `esim_bridge.py` | v1.0.0 | Core plugin: netlist export, SPICE conversion, 6-tab dialog, 7 analysis types, ngspice execution, embedded waveform viewer, eSim project generation, eSim launch |
| `esim_spice_linker.py` | v1.0.0 | SPICE Model Auto-Linker: scans eSim's built-in open-source library (647 files, 1317 total), automatically resolves and injects SPICE models for every active component |
| `ngspiceSimulation/` | (integrated) | Python plot window package: full PyQt5 waveform viewer integrated dynamically via importlib - compatible with eSim's text output format |
| `configuration/Appconfig.py` | (integrated) | eSim Appconfig compatibility layer for session logging and error display |

---

## Analysis Types

| Analysis | Parameters | Result |
|---|---|---|
| Transient | Start, Step, Stop time | Embedded waveform viewer |
| AC Sweep | Scale (Lin/Dec/Oct), Start/Stop freq, Points | Embedded waveform viewer (+ Bode plot) |
| DC Sweep | Source, Start, Stop, Step (+ optional 2nd source) | Embedded waveform viewer |
| Operating Point | None | DC node voltages popup |
| Noise | Output node, Input source, Freq range | inoise / onoise values popup |
| Transfer Function | Output node, Input source | Gain + input/output impedances popup |
| Sensitivity | Output variable | Component impact ranking popup |

---

## Embedded Waveform Viewer Features

After running ngspice, the interactive `NgspiceWaveformViewer` opens automatically:

| Feature | Description |
|---|---|
| Trace toggles | Colour-coded checkboxes for each variable; toggling hides/shows traces with immediate redraw |
| FFT spectrum | `numpy.fft.rfft` on time-domain data; magnitude = `|rfft|×2/N`; toggle between spectrum and waveform |
| Bode plot | Dual-pane: gain (dB) + phase (degrees) vs. log frequency axis (AC analysis only) |
| Cursor measurement | Left-click places cursor 1 (red), right-click places cursor 2 (blue); auto-scaled time (ns/µs/ms/s) and voltage annotation |
| Parametric sweep | Vary any R/C/L across a range (2-10 steps); re-runs ngspice per step; overlays all results with distinct colours and line styles |
| Runtime stats panel | Peak, Max, Min, Average, Peak-to-Peak, RMS, Frequency - all read directly from ngspice's binary `.raw` output at runtime; **no hardcoded defaults** |
| Legend toggle | Show/hide trace legend without re-running simulation |
| PNG export | Saves current figure at 150 DPI |

---

## Python Plot Window

Clicking **Open Python Plot** launches the `ngspiceSimulation` package - a full PyQt5 waveform viewer compatible with eSim's text output format:

- **Three-panel layout:** waveform list (left) + matplotlib figure (centre) + collapsible controls (right)
- **Digital timing diagram:** two-level digital waveforms stacked vertically with adjustable logic threshold
- **Cursor measurements:** Δt, implied frequency
- **Multimeter:** RMS computed with Python's `Decimal` type (5 significant figures)
- **Function plotting:** ratio mode (`A vs B`) and arbitrary NumPy expression mode
- **Persistent per-trace style:** colour, thickness, line style saved to `~/.pythonPlotting/config.json`

---

## KiCad-to-Ngspice Dialog (6 Tabs)

Mirrors eSim's own KicadToNgspice converter window:

| Tab | Purpose |
|---|---|
| Analysis | Select analysis type and parameters (7 types with dedicated parameter panels) |
| Source Details | Configure V/I source waveforms (SIN, PULSE, PWL, EXP, AC, DC) - dynamically built from schematic |
| Ngspice Model | Set parameters for U-prefix behavioral models via eSim's modelParamXML |
| Device Modeling | Add external .lib files for Q/D/J/M/S components; MOSFET W/L/M fields |
| Subcircuits | Select subcircuit directories for X-prefix components with port count validation |
| Microcontroller | NGHDL status, .hex file picker, previous values restore via XML |

All values are automatically saved and restored between sessions.

---

## SPICE Model Auto-Linker - 5-Tier Search

For every active component, the Auto-Linker searches in priority order:

| Tier | Source | Coverage |
|---|---|---|
| 1 | eSim `deviceModelLibrary/` | 61 model files: Diode, Transistor, MOS, JFET, IGBT, LEDs, Switch, Misc |
| 2 | eSim `SubcircuitLibrary/` | 586+ subcircuit folders (1317 total files): op-amps, 555 timers, regulators, 74-series, CMOS |
| 3 | User `~/.esim-bridge/models/` | Drop any `.lib`/`.sub` file here - auto-discovered |
| 4 | Known equivalents → re-search eSim | BC547 → BC547B/2N2222; 7400 → SN74LS00; etc. |
| 5 | Textbook parameters | Last-resort `.model` card from Sedra/Smith, Razavi, Boylestad |

**Model status codes:**

| Status | Colour | Meaning |
|---|---|---|
| FOUND | Green | Exact match in eSim's open-source library |
| EQUIV | Blue | Pin-compatible substitute used |
| TEXTBK | Amber | Generated from textbook parameters |
| MISSING | Red | No model found anywhere |
| OK | Grey | Passive (R/C/L) or source (V/I) - no model needed |

---

## Supported Components

| Prefix | Component | SPICE Handling |
|---|---|---|
| `R` | Resistor | Direct value (with space/string sanitisation; fallback to `1k`) |
| `C` | Capacitor | Direct value |
| `L` | Inductor | Direct value |
| `V` | Voltage source | Full `Sim.Type` + `Sim.Params` support: SIN, PULSE, PWL, EXP, AC, DC |
| `I` | Current source | DC value |
| `D` / LED | Diode / LED | Auto-model from eSim library |
| `Q` | BJT Transistor | Auto-model NPN/PNP from eSim library |
| `M` | MOSFET | Auto-model NMOS/PMOS from eSim library |
| `J` | JFET | Auto-model NJF/PJF |
| `U` / `X` | IC / Op-amp / Subcircuit | eSim SubcircuitLibrary search → textbook fallback |
| `BT` | Battery | Converted to DC voltage source |
| `MK` | Microphone | Approximated as 10 mV AC source at 1 kHz |
| `SW` | Switch | Modelled as 1 Ω resistor (closed state) |
| `F` | Fuse | Modelled as 0.01 Ω resistor |

---

## Built-in Model Library (47+ Components)

| Category | Models |
|---|---|
| Diodes | 1N4148, 1N4007, 1N4001-4004, 1N5817/5819, Zener variants (BZT52C, 1N4733-4744), LED (red/green/blue/generic) |
| NPN BJTs | 2N2222, 2N3904, BC547/B, BC548, 2N2219, TIP31 |
| PNP BJTs | 2N3906, 2N2907, BC557, BC558, TIP32 |
| N-MOSFETs | IRF540/N, IRF3205, IRF830, 2N7000, 2N7002, BS170 |
| P-MOSFETs | IRF9540, BS250 |
| Op-Amps | LM741, UA741, LM358, LM324 (simplified subcircuits) |
| Timers | NE555 |
| Regulators | 7805, 7812, 78L33 |

---

## Preflight Netlist Checker

Before every simulation, the plugin automatically checks:

| Check | Action on Failure |
|---|---|
| Ground node (GND/0) exists | Error dialog - simulation blocked |
| No floating nodes (pins connected to only one component) | Error dialog - simulation blocked |
| No voltage source short circuits (two sources sharing both terminals) | Error dialog - simulation blocked |
| No orphan components (zero net connections) | Warning - non-blocking |
| No DC path violations (nets connected only through capacitors) | Warning - non-blocking |
| `.spiceinit` contains `set ngbehavior=ps` | Created/appended automatically - silent |

---

## Validated Test Circuits

### Circuit 1: Three-Phase Full-Wave Diode Bridge Rectifier with LC Filter

| Component | Value | Description |
|---|---|---|
| D1-D6 | 1N4148 | Six-pulse diode bridge |
| L1 | 10 mH | Filter inductor |
| C1 | 470 µF | Filter capacitor |
| R1 | 100 Ω | Load resistor |
| V1 | SIN(0 325 50 0 0 0) | Phase A, 0° |
| V2 | SIN(0 325 50 0 0 120) | Phase B, 120° |
| V3 | SIN(0 325 50 0 0 240) | Phase C, 240° |

**Transient analysis settings:** Start=0, Step=0.1ms, Stop=100ms

**Verified results:**
- Average DC output: 49.86 V
- Ripple frequency: 149.93 Hz (confirms 6-pulse rectification: 3×50 Hz)
- RMS: 52.25 V
- D1-D6: all resolved **FOUND** from eSim's `deviceModelLibrary`

### Circuit 2: Two-Stage Stagger-Tuned Amplifier

| Component | Value | Description |
|---|---|---|
| Q1, Q2 | 2N2222 | NPN BJT transistors |
| L1, L2 | 1 mH | Tuned inductors |
| C2 | 1.2 nF | Stage 1 tuning capacitor |
| C5 | 910 pF | Stage 2 tuning capacitor |
| V1 | AC 1 SIN(0 10m 52K) | Input signal at 52 kHz |

**AC analysis settings:** Scale=Dec, Start=80kHz, Stop=250kHz, Points=400

**Verified results:**
- Stage 1 gain peak: ~139.4 kHz (theoretical: 145.4 kHz)
- Stage 2 gain peak: ~166.8 kHz (theoretical: 166.9 kHz)
- Q1, Q2: resolved **FOUND** from eSim's `deviceModelLibrary` (score 100 - exact key match)

---

## System Requirements

| Software | Version | Notes |
|---|---|---|
| Ubuntu Linux | 24.04 LTS | Tested on 24.04 in VirtualBox |
| KiCad | 8.0 | Must include `kicad-cli` |
| eSim | 2.5 | Must be at `~/Downloads/eSim-2.5/` |
| ngspice | 42 | Bundled with eSim 2.5 |
| Python | 3.10+ | Included with Ubuntu 24.04 |

| Environment | Status |
|---|---|
| Ubuntu 24.04 in VirtualBox (Windows/macOS host) | ✅ Fully tested - recommended |
| Native Ubuntu 24.04 | ✅ Works |
| WSL 2 with WSLg (Windows 11) | ⚠️ May work - not officially tested |
| macOS | ❌ eSim 2.5 is Linux-only |

---

## Installation

### Step 1 - Install KiCad 8.0

```bash
sudo apt update && sudo apt install -y kicad
kicad-cli --version   # Expected: Application: kicad-cli 8.0.x
```

### Step 2 - Install eSim 2.5

```bash
cd ~/Downloads
wget https://static.fossee.in/esim/installation-files/eSim-2.5.zip
unzip eSim-2.5.zip && cd eSim-2.5
chmod +x install-eSim.sh && ./install-eSim.sh --install

# Verify
ls ~/Downloads/eSim-2.5/src/frontEnd/Application.py
ls ~/.esim/env/bin/python3
```

### Step 3 - Clone the Repository

```bash
cd ~
git clone https://github.com/FOSSEE/eSim-KiCad-Plugin.git
```

### Step 4 - Install the Plugin

```bash
mkdir -p ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge
cp -r ~/eSim-KiCad-Plugin/ImranFarhat_eSim_Simulation_Bridge/eSim_Simulation_Bridge/* \
    ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/
```

### Step 5 - Create Workspace

```bash
mkdir -p ~/eSim-Workspace
echo '{"/home/'$(whoami)'/eSim-Workspace/esim_bridge_project": []}' \
    > ~/eSim-Workspace/.projectExplorer.txt
```

### Step 6 - Restart KiCad and Verify

Open KiCad → PCB Editor → look for the **eSim Bridge** icon in the toolbar.  
If not visible: **Tools → External Plugins → Refresh Plugins**

> **Important after every code change:** Clear the Python bytecode cache before restarting KiCad:
> ```bash
> rm -rf ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/__pycache__
> ```

---

## Demo Circuit (Recommended for First Test)

Use the Three-Phase Bridge Rectifier circuit for the full demo:

**Components:** 6× 1N4148 diodes (D1-D6), L1=10mH, C1=470µF, R1=100Ω, three SIN sources (V1/V2/V3) at 325V peak, 50Hz, 120° apart.

**Analysis:** Transient, Start=0, Step=0.1ms, Stop=100ms

**Expected:** v(out) shows smoothed DC output at ~49.86V average, ripple frequency 149.93Hz (6-pulse rectification).

---

## File Structure

```
ImranFarhat_eSim_Simulation_Bridge/
├── eSim_Simulation_Bridge/
│   ├── __init__.py                          # Package entry point
│   ├── esim_bridge.py                       # eSim Simulation Bridge v1.0.0
│   ├── esim_spice_linker.py                 # SPICE Model Auto-Linker v1.0.0
│   ├── icon.png                             # KiCad toolbar icon
│   ├── configuration/
│   │   ├── __init__.py
│   │   └── Appconfig.py                     # eSim compatibility layer
│   └── ngspiceSimulation/
│       ├── __init__.py
│       ├── plot_window.py                   # PyQt5 plot window
│       ├── data_extraction.py               # ngspice text output parser
│       └── plotting_widgets.py              # UI widgets
├── README.md
├── INSTALLATION_GUIDE.md
├── QUICK_REFERENCE.md
├── KNOWN_LIMITATIONS.md
├── DESIGN_DOCUMENT.pdf
└── metadata.json
```

---

## Known Limitations

| Limitation | Details |
|---|---|
| **MCUs (ATtiny, Arduino, etc.)** | No SPICE models exist industry-wide. MISSING status is correct and expected. eSim's NGHDL pathway handles MCU co-simulation separately. |
| **74xx TTL digital ICs** | ngspice is an analog solver; digital logic cannot be meaningfully simulated. |
| **eSim co-simulation components** | `eSim_Ngveri`, `eSim_Hybrid`, `adc_bridge`, `dac_bridge` require eSim's internal ngspice+Verilator engine. Not supported. |
| **Condenser microphones** | No standard SPICE model exists. Approximated as 10 mV AC source at 1 kHz. |
| **Pole-zero analysis** | ngspice 42 (Ubuntu package) has a confirmed bug in `pzan.c` - KLU solver returns `E_UNSUPP`. Feature removed entirely. |
| **UTF-8 popup (cosmetic)** | A known eSim 2.5 issue when reading binary `.raw` files. Dismiss and continue - does not affect simulation results. |
| **Parametric sweep leftover** | Running AC analysis immediately after a parametric sweep may leave intermediate component values in the SPICE file. Reset between analysis types. |
| **Linux only** | eSim 2.5 is Linux-only. |

---

## Useful Commands

```bash
# View generated SPICE file
cat ~/eSim-Workspace/esim_bridge_project/esim_bridge_project.cir.out

# Follow plugin log in real time
tail -f ~/.local/share/kicad/esim_bridge.log

# Run simulation manually (without the plugin)
ngspice -b ~/eSim-Workspace/esim_bridge_project/esim_bridge_project.cir.out

# Launch eSim manually
cd ~/Downloads/eSim-2.5/src/frontEnd
PYTHONPATH=/home/$(whoami)/Downloads/eSim-2.5/src \
    ~/.esim/env/bin/python3 Application.py

# Delete stale .raw file (if UTF-8 popup persists)
rm -f ~/eSim-Workspace/esim_bridge_project/esim_bridge_project.raw

# Clear plugin cache after code changes (MANDATORY)
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
| Flat graph at 0V | Check that V1 has `Sim.Type=SIN` and `Sim.Params` set in KiCad schematic properties |
| Sensitivity all zeros | Set `dc=1` on voltage source in Source Details tab (DC operating point required) |
| eSim blank icons in VirtualBox | Set display to VMSVGA + 256 MB Video Memory |
| UTF-8 popup | Dismiss and re-simulate - cosmetic only, results are unaffected |
| Code changes not taking effect | Run `rm -rf ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/__pycache__` and restart KiCad |

---

## License

GPL-3.0 - Free to use, modify, and distribute with attribution. Full compatibility with the eSim ecosystem.

---

*Developed as part of FOSSEE Semester Long Internship Spring 2026, IIT Bombay.*  
*eSim: KiCad Plugin Development*
