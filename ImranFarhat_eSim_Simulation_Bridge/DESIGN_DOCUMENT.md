# Design Document — eSim Simulation Bridge
## KiCad Plugin Suite for eSim/ngspice Simulation

| Field | Value |
|---|---|
| Plugin Names | eSim-BRIDGE v2.1.0 + eSim-SPICE v1.0.0 |
| Author | Imran Farhat |
| Institution | IIT Bombay (FOSSEE) |
| Submitted For | FOSSEE Semester Long Internship Spring 2026 — Task 6 |
| KiCad Compatibility | 8.0 / 9.x |
| Platform | Ubuntu Linux 24.04 LTS |
| License | GPL-3.0 |
| GitHub | https://github.com/ImranFarhat01/KiCad-Plugin-ImranFarhat |
| Date | May 2026 |

---

## 1. Problem Statement

KiCad and eSim are both free, open-source EDA tools used extensively in electronics education in India. KiCad is used for schematic capture and PCB design; eSim (developed by FOSSEE, IIT Bombay) is used for SPICE-based circuit simulation with ngspice.

The workflow to simulate a KiCad schematic in eSim is entirely manual and consists of 26 steps:

1. Export netlist from KiCad (File → Export → Netlist)
2. Open eSim
3. Create new project, set project name
4. Import the netlist file
5. For every active component (diode, transistor, op-amp, etc.):
   - Open the Model Editor
   - Search for a matching SPICE model
   - Download or locate the model file
   - Link the model to the component
   - Save and close
6. Configure simulation analysis type (AC/DC/Transient/OP)
7. Set simulation parameters (time step, stop time, frequency range, etc.)
8. Run ngspice
9. Open eSim's plotter
10. Select which signals to plot

This process takes 10–15 minutes per schematic and must be repeated from scratch every time a component value is changed. For students learning circuit simulation, this friction is a significant barrier.

**The goal:** Reduce this 26-step, 10–15 minute process to 5 steps in approximately 30 seconds, and add advanced waveform analysis capabilities not present in the original eSim.

---

## 2. Solution Overview

The solution consists of two companion KiCad plugins installed as a single package:

| Plugin | File | Role |
|---|---|---|
| **eSim-BRIDGE** | `esim_bridge.py` | Netlist export, SPICE conversion, analysis configuration, ngspice execution, waveform viewer, eSim launch |
| **eSim-SPICE** | `esim_spice_linker.py` | Automatic SPICE model resolution from eSim's built-in library |

Together they reduce the workflow from 26 manual steps to 5 steps in approximately 30 seconds. Additionally, the plugin adds a full-featured interactive waveform viewer with capabilities beyond what eSim's built-in plotter provides.

---

## 3. Architecture Overview

*[Screenshot: Plugin architecture block diagram — showing the pipeline from KiCad through eSim-BRIDGE, eSim-SPICE, ngspice, to the waveform viewer]*

The plugin uses a sequential pipeline architecture:

```
KiCad PCB Editor (toolbar button click)
        │
        ▼
Step 1: get_schematic_path()
        Find .kicad_sch from open PCB project
        │
        ▼
Step 2: export_netlist()
        kicad-cli sch export netlist --format kicadsexpr
        Output: /tmp/esim_bridge_netlist.net
        │
        ▼
Step 3: KicadToNgspiceDialog (6 tabs)
        User configures analysis + source types
        │
        ▼
Step 3b: PreflightChecker.check_netlist()
        Floating nodes, GND, shorts, orphans, DC path violations
        │
        ▼
Step 4: SPICEConverter.convert()
        Parse netlist → generate .cir file
        Auto-inject device models from built-in library
        │
        ▼
Step 5: SPICEAutoLinker (eSim-SPICE)
        5-tier model search → ModelStatusReport dialog
        Inject eSim library models into .cir
        │
        ▼
Step 6: Build eSim project files
        .cir.out with .control block
        .proj, analysis, plot_data files
        │
        ▼
Step 7: SimulationReadyDialog
        SPICE preview → "Run with ngspice →"
        │
        ▼
Step 8: ngspice -b (batch mode)
        Runs simulation, writes .raw file
        │
        ▼
Step 9: NgspiceWaveformViewer
        Interactive plot with FFT, Bode, cursor,
        measurements, parametric sweep
        │
        ▼
Step 10: ESimLauncher (optional)
         Launch eSim 2.5 with project ready
```

---

## 4. Module Breakdown

### 4.1 eSim-BRIDGE (`esim_bridge.py`)

#### 4.1.1 `ESimBridgePlugin` — Main Plugin Class

Inherits from `pcbnew.ActionPlugin`. This is the KiCad plugin entry point that registers with KiCad and appears as a toolbar button.

| Method | Purpose |
|---|---|
| `defaults()` | Register plugin name, icon, category with KiCad |
| `Run()` | Main orchestration — called when toolbar button clicked |
| `get_schematic_path()` | Resolve `.kicad_sch` path from open PCB project |
| `export_netlist()` | Shell out to `kicad-cli sch export netlist` |

`Run()` orchestrates the full pipeline in sequence with error handling and user feedback at each step.

---

#### 4.1.2 `KicadToNgspiceDialog` — 6-Tab Configuration Dialog

Mirrors eSim's own KicadToNgspice window exactly. Must be created after the netlist is parsed so all tabs can be dynamically populated from the schematic content.

**Tab 1 — Analysis**

Seven analysis types as checkboxes (radio behavior — only one active at a time):

| Analysis | Panel | Key Widgets |
|---|---|---|
| AC | `_ac_panel` | Scale (Lin/Dec/Oct), Start/Stop Freq, Points |
| DC | `_dc_panel` | Source 1/2, Start, Increment, Stop |
| Transient | `_tran_panel` | Start Time, Step Time, Stop Time |
| Noise | `_noise_panel` | Output Node, Input Source, Freq Range |
| Transfer Function | `_tf_panel` | Output Node, Input Source |
| Sensitivity | `_sens_panel` | Output Variable |
| Operating Point | (no panel) | Selected via DC tab checkbox |

Each panel is a `wx.Panel` wrapped around a `wx.StaticBoxSizer` so `Show(False)` properly collapses the space. This fixes a wxPython limitation where `StaticBoxSizer.Show(False)` does not collapse layout.

**Tab 2 — Source Details**

Dynamically built from V/I prefix components found in the schematic. Each source shows a type dropdown (dc/ac/sine/pulse/pwl/exp) and matching parameter fields. Source type is detected from `Sim.Type` and `Sim.Params` properties in the KiCad netlist.

**Tab 3 — Ngspice Model**

For U-prefix components. Reads eSim's `modelParamXML/` directory (Analog, Digital, Hybrid, Nghdl, Ngveri subdirs) and renders parameter fields from the XML definition. Mirrors eSim's `Model.py` tab exactly.

**Tab 4 — Device Modeling**

For Q/D/J/M/S prefix components. File picker for external `.lib` files. MOSFET components additionally show Width, Length, and Multiplication Factor fields (matching eSim's `DeviceModel.py`).

**Tab 5 — Subcircuits**

For X-prefix components. Directory picker for `.sub` files, with validation that the selected directory contains at least one `.sub` file.

**Tab 6 — Microcontroller**

Mirrors eSim's `Microcontroller.py` tab:
- Reads `~/.nghdl/config.ini` to detect NGHDL installation and show `NGHDL_HOME`
- Detects MCU components in schematic by keyword matching (attiny, arduino, atmega, pic, stm32, esp, avr, mcu)
- Shows instance ID (auto-generated 0–99) and hex file picker per MCU
- Saves/restores hex file paths via `~/.esim-bridge/mcu_previous_values.xml`

---

#### 4.1.3 `SPICEConverter`

Converts a KiCad KiExpr netlist file (`.net`) to a SPICE deck (`.cir`).

**Component handling priority (multi-char prefixes checked first):**

```
MK* → Microphone → 10mV AC source
BT* → Battery → DC voltage source
SW* → Switch → 1Ω resistor
R   → Resistor (with value sanitization)
C   → Capacitor
L   → Inductor
V   → Voltage source (Sim.Type + Sim.Params handling)
I   → Current source
D   → Diode/LED (auto-model)
Q   → BJT (auto-model NPN/PNP)
M   → MOSFET (auto-model NMOS/PMOS)
J   → JFET (auto-model)
U/X → IC/Subcircuit (library search cascade)
S   → Switch → 1Ω resistor
F   → Fuse → 0.01Ω resistor
T   → Transformer → unsupported comment
```

**Voltage source conversion** (`_convert_voltage_source`) handles:
- `Sim.Type == 'SIN'` → `AC {ac} SIN({dc} {ampl} {freq} {delay} {damping})`
- `Sim.Type == 'PULSE'` → `PULSE({v1} {v2} {td} {tr} {tf} {pw} {per})`
- `Sim.Type == 'DC'` → `DC {dc}` (reads `dc=` from Sim.Params)
- `Sim.Type == 'AC'` → `AC {ampl} {phase}`
- `Sim.Type == 'EXP'` → `EXP({v1} {v2} {rise_delay} {rise_tau} {fall_delay} {fall_tau})`
- `Sim.Type == 'PWL'` → `PWL({t1} {v1} {t2} {v2} ...)` (time-value pairs from Sim.Params)
- Value == 'VSIN'/'VPULSE'/'VAC'/'VDC' → `DC 5` (fallback when KiCad stores symbol name as value)
- Value contains 'DC'/'AC'/'PULSE'/'SIN' → pass through as-is

**Net name cleaning rules:**
- GND/GROUND/VSS/0 → SPICE node `0`
- Strip leading `/`
- Replace non-alphanumeric with `_`, collapse multiple `_`
- Truncate to 20 characters
- Prepend `N` if starts with digit

**Model injection** via `_rewrite_with_models()`:
- Reads existing `.model` and `.subckt` names from file to avoid duplicates
- Appends only new models/subcircuits before `.end`

---

#### 4.1.4 `ExternalModelLoader`

Scans `~/.esim-bridge/models/` for user-provided SPICE model files.

- Supported extensions: `.lib`, `.mod`, `.sub`, `.spice`, `.txt`, `.cir`, `.model`
- Parses `.model <name> <TYPE>(...)` patterns
- Parses `.subckt <name> ... .ends` blocks
- Creates `README.txt` on first run explaining how to add models
- Clean key index: lowercase alphanumeric only for fuzzy matching

---

#### 4.1.5 `SPICEModelLibrary`

Hardcoded SPICE model library for 47+ common components. All parameters from published textbooks and manufacturer datasheets.

| Category | Coverage |
|---|---|
| Diodes | 1N4148, 1N4007, 1N4001–4004, 1N5817/5819, Zener variants (BZT52C, 1N4733–4744), LED (generic, red, green, blue) |
| NPN BJTs | 2N2222, 2N3904, BC547/B, BC548, 2N2219, TIP31 |
| PNP BJTs | 2N3906, 2N2907, BC557, BC558, TIP32 |
| N-MOSFET | IRF540/N, IRF3205, IRF830, 2N7000, 2N7002, BS170 |
| P-MOSFET | IRF9540, BS250 |
| Op-Amps | LM741, UA741, LM358, LM324 (simplified subcircuits) |
| Timers | NE555 |
| Regulators | 7805, 7812, 78L33 |

---

#### 4.1.6 `PreflightChecker`

Validates both environment and netlist before simulation.

**`run_all_checks(schematic_path)`** checks:
1. Schematic file exists
2. `kicad-cli` available (`kicad-cli --version`)
3. eSim installed at expected path
4. `/tmp` writable
5. `.spiceinit` created/updated with `set ngbehavior=ps`

**`check_netlist(components, nets)`** checks:
1. Ground node (GND/0) exists
2. Floating nodes (nets with only 1 pin connection)
3. Voltage source short circuits (two sources sharing both terminals)
4. Orphan components (no net connections)
5. DC path violations (nets connected only through capacitors)

Results shown as errors (blocking, user must confirm to continue) or warnings (non-blocking, shown as info). All results also logged to `~/.local/share/kicad/esim_bridge.log`.

---

#### 4.1.7 `NgspiceWaveformViewer`

*[Screenshot: Waveform viewer showing voltage divider transient simulation with dark oscilloscope theme]*

wxPython dialog embedding a matplotlib figure. Dark oscilloscope theme with 8-colour trace palette.

**UI structure:**
- Top info bar: info label + action buttons
- Splitter: matplotlib canvas (left) + trace toggle checkboxes (right)
- Bottom: stats text panel (green-on-dark-blue monospace) — shows peak/min/max/average per node from parsed `.raw` data, noise analysis inoise/onoise values, simulation timing info, and any unsupported component warnings
- Close button

**Buttons and methods:**

| Button | Method | Analysis |
|---|---|---|
| 📊 Show FFT | `_on_show_fft()` | Transient only |
| 📈 Bode Plot | `_on_show_bode()` | AC only |
| 📏 Measure | `_on_measure()` | Transient only |
| 🖱 Cursor | `_on_toggle_cursor()` | All |
| 🔁 Sweep | `_on_param_sweep()` | Transient only |
| 💾 Save PNG | `_on_save_png()` | All |
| ⟳ Refresh | `_load_and_plot()` | All |

**FFT (`_on_show_fft`):** Uses `numpy.fft.rfft` on time-domain data. Sample rate computed from time vector spacing. Magnitude = `|rfft| * 2 / N`. Toggle button switches between FFT view and waveform view.

**Bode Plot (`_on_show_bode`):** Clears figure and creates two subplots. Top: `20 * log10(|y|)` vs frequency (log scale). Bottom: `angle(y, deg=True)` vs frequency (log scale). For real-valued raw data, phase shows 0° (correct for resistive circuits). Restores single-axis view on toggle.

**Cursor (`_on_toggle_cursor`, `_on_cursor_move`):** Connects `motion_notify_event` to matplotlib canvas. Shows a gold annotation box with auto-scaled time (ns/µs/ms/s) and voltage, plus crosshair lines. Disconnects event on toggle off.

**Measurements (`_on_measure`):** Dialog with node dropdown + measurement type dropdown. Computes from parsed `.raw` data:
- RMS: `sqrt(sum(v²) / N)`
- Average: `sum(v) / N`
- Peak: `max(|v|)`
- Min/Max: direct
- Frequency: zero-crossing detection (rising edges), period from first to last crossing

**Parametric Sweep (`_on_param_sweep`):** Dialog asking for component, start value, stop value, steps. Uses log spacing if ratio > 10, linear otherwise. For each step: modifies the `.cir.out` file with regex substitution on the component line, runs ngspice, parses the `.raw` output, overlays all results. Skips first non-time variable (input node) and plots the second (output node).

---

#### 4.1.8 `NgspiceRawParser`

Parses ngspice `.raw` files in both ASCII and binary format.

**ASCII parser:** Reads header fields (Title, Plotname, No. Variables, No. Points), then parses Variables section and Values section line by line.

**Binary parser:** Locates `Binary:\n` marker in file bytes, reads 8-byte doubles in row-major order. For AC analysis, doubles complex values (interleaved real + imaginary).

Returns a normalized dict: `{title, type, vars: [{name, unit}], data: {name: [float...]}}`.

---

#### 4.1.9 `ESimLauncher`

Handles eSim process launch using `subprocess.Popen` (non-blocking, so KiCad stays responsive).

```bash
cd ~/Downloads/eSim-2.5/src/frontEnd
PYTHONPATH=~/Downloads/eSim-2.5/src \
    ~/.esim/env/bin/python3 Application.py
```

---

#### 4.1.10 `SimulationReadyDialog`

Shown after successful SPICE conversion, before ngspice execution. Displays:
- Component count and analysis type
- Unsupported component warnings (amber text)
- Full generated SPICE file preview (read-only)
- Buttons: "Launch eSim →", "Run with ngspice →", "Open .cir File", "Close"

The "Run with ngspice →" button triggers `_on_run_ngspice()`, which:
1. Injects `set filetype=binary` and `write <raw_path>` into the `.control` block
2. Runs ngspice in batch mode (`-b`)
3. Opens `NgspiceWaveformViewer` with the resulting `.raw` file

---

### 4.2 eSim-SPICE (`esim_spice_linker.py`)

#### 4.2.1 `ESimLibraryScanner`

Scans eSim 2.5's built-in open-source model libraries at initialization.

**Library paths:**

| Directory | Contents |
|---|---|
| `library/deviceModelLibrary/` | Diode, Transistor, MOS, JFET, IGBT, LEDs, Switch, Misc — 61 categories |
| `library/SubcircuitLibrary/` | Op-amps, 555 timers, regulators, 74-series, CMOS — 586+ subcircuit folders |

**Scanning:** Uses `os.walk()` recursively (not a hardcoded subdirectory whitelist) so any new library folders added to eSim are automatically indexed.

**Index structures:**
- `self.device_models` — `{clean_key: {name, type, definition, file_path, category, folder_name}}`
- `self.subcircuits` — `{clean_key: {name, definition, file_path, folder_name}}`

**Matching algorithm (`_match_score`):**

| Score | Condition |
|---|---|
| 100 | Exact clean key match |
| 90 | Exact folder name match |
| 88 | Folder name match with common IC prefix stripped (SN, CD, MC, DM) |
| 80 | Match after stripping common prefixes (LM, TL, SN, CD, etc.) |
| 60 | One key starts with the other (both ≥ 4 chars) |
| 0 | No match or generic key (blacklisted: npn, pnp, nmos, d, r, c, switch, etc.) |

**74xx special handling (Strategy 4):** Tries prefixed lookups — `sn74ls00`, `sn74`, `cd40`, etc. — for 74-series IC numbers where the schematic value is just `7400` but eSim's folder is `SN74LS00`.

---

#### 4.2.2 `ModelMatcher`

Orchestrates the 5-tier model search cascade for each active component.

**Search order:**

| Tier | Source | Method |
|---|---|---|
| 1 | eSim deviceModelLibrary | `ESimLibraryScanner.find_device_model()` |
| 2 | eSim SubcircuitLibrary | `ESimLibraryScanner.find_subcircuit()` |
| 3 | User `~/.esim-bridge/models/` | `ExternalModelLoader.find_model()` / `find_subcircuit()` |
| 4 | Known equivalents → re-search eSim | `TextbookModelGenerator.get_equivalents()` |
| 5 | Textbook parameters | `TextbookModelGenerator.generate_model()` |
| 6 | Not found | Report MISSING |

**Bypass logic:** R, C, L, V, I, BT, and SW-prefix components are immediately classified as `passive` or `source` without searching libraries, saving scan time.

**Status codes:**

| Code | Meaning |
|---|---|
| `esim_device` | Found in eSim deviceModelLibrary |
| `esim_subcircuit` | Found in eSim SubcircuitLibrary |
| `external` | Found in user's `~/.esim-bridge/models/` |
| `builtin` | Found in eSim-BRIDGE built-in SPICEModelLibrary |
| `generated` | Generated from textbook parameters |
| `equivalent` | Using a known pin-compatible substitute |
| `not_found` | No model found anywhere |
| `passive` | R/C/L — no model needed |
| `source` | V/I/BT — uses SPICE source syntax |

---

#### 4.2.3 `TextbookModelGenerator`

Generates approximate `.model` cards from published textbook parameters as a last resort (Sedra/Smith, Razavi, Boylestad).

**Parameter databases:** Diodes (1N4148, 1N4007, generic, LED, Zener), NPN BJTs (2N2222, 2N3904, BC547, BC548, generic), PNP BJTs (2N3906, 2N2907, BC557, BC558, generic), NMOS (2N7000, 2N7002, IRF540, BS170, generic), PMOS (IRF9540, BS250, generic).

**Equivalence table:** Maps component names to known pin-compatible substitutes available in eSim's library. Examples: `BC547` → `[BC547B, 2N2222, 2N3904]`, `7400` → `[SN74LS00]`.

---

#### 4.2.4 `ModelStatusReport`

*[Screenshot: Model Status Report dialog showing FOUND/TEXTBK/MISSING rows with color coding]*

wxPython dialog displaying the model coverage report.

**Table columns:** Ref | Value | Status | Source / Action

**Row sorting:** MISSING first → EQUIV → TEXTBK → FOUND → OK

**Color coding:**
- Green: FOUND
- Amber: TEXTBK
- Blue: EQUIV
- Red: MISSING (row background tinted red)
- Grey: OK

**Buttons:** Export Report (saves `.txt`), Continue (proceed), Cancel

---

#### 4.2.5 `SPICEAutoLinker`

Main entry point for eSim-SPICE. Called from eSim-BRIDGE's `Run()`.

```python
linker = SPICEAutoLinker()
results = linker.check_models(components)
linker.show_report(parent, components, results)
models, subcircuits = linker.get_injection_data(results)
```

**Import placement:** The import of `SPICEAutoLinker` is inside `Run()`, not at module level. This is required because eSim-SPICE scans 1,300+ library files on initialization (~2 seconds) — placing the import at module level would cause KiCad to timeout during startup.

**`sys.path.insert`:** Must be called before the import to ensure KiCad finds `esim_spice_linker.py` in the plugin directory.

---

## 5. Data Flow

```
KiCad schematic (.kicad_sch)
         │ kicad-cli sch export netlist --format kicadsexpr
         ▼
/tmp/esim_bridge_netlist.net (KiCad s-expression format)
         │ SPICEConverter.parse_full_netlist()
         ▼
components: {ref: {value, description, lib_name, sim_type, sim_params, pins}}
nets:       {net_name: {spice_name, nodes: [(ref, pin)]}}
         │ PreflightChecker.check_netlist()
         ▼
Issues list (errors/warnings shown to user)
         │ SPICEConverter.component_to_spice() × N
         │ + SPICEModelLibrary lookups
         │ + ExternalModelLoader lookups
         ▼
/tmp/esim_bridge_simulation.cir (pure SPICE netlist)
         │ SPICEAutoLinker.check_models()
         ▼
match_results: {ref: {status, model_name, model_definition, dependencies}}
         │ ModelStatusReport shown to user
         │ SPICEAutoLinker.get_injection_data()
         ▼
esim_models, esim_subcircuits (deduplicated vs already-injected)
         │ SPICEConverter._rewrite_with_models()
         ▼
/tmp/esim_bridge_simulation.cir (with all models injected)
         │ Build .cir.out with .control block
         ▼
~/eSim-Workspace/esim_bridge_project/
├── esim_bridge_project.cir         ← pure netlist
├── esim_bridge_project.cir.out     ← with .control block
├── esim_bridge_project.proj
├── analysis
├── plot_data_v.txt
└── plot_data_i.txt
         │ ngspice -b esim_bridge_project.cir.out
         ▼
esim_bridge_project.raw (binary waveform data)
         │ NgspiceRawParser.parse()
         ▼
{vars: [{name, unit}], data: {name: [float...]}}
         │ NgspiceWaveformViewer._draw_plot()
         ▼
Interactive matplotlib waveform display
```

---

## 6. KiCad Plugin Integration

```python
import pcbnew

class ESimBridgePlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "eSim Simulation Bridge"
        self.category = "eSim Tools"
        self.description = "One-click simulation bridge"
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), 'icon.png')

    def Run(self):
        # Full pipeline here
        pass

ESimBridgePlugin().register()
```

**`__init__.py`** must contain exactly:
```python
from .esim_bridge import ESimBridgePlugin
```

**`__pycache__`** must be cleared after every code change — KiCad loads cached `.pyc` files and will not see updates otherwise.

---

## 7. Integration of Computer Science and Electronics Concepts

This plugin deliberately integrates both domains, meeting the task requirement.

**Computer Science concepts applied:**

| Concept | Application |
|---|---|
| Plugin/extension framework | KiCad `pcbnew.ActionPlugin` API |
| Parsing and regex | KiCad KiExpr netlist format, SPICE syntax validation |
| Multi-tier search with scoring | eSim-SPICE model matching algorithm (0–100 score) |
| Subprocess management | `kicad-cli`, `ngspice`, `eSim Application.py` |
| wxPython GUI | 6-tab dialog, waveform viewer, progress dialogs, file pickers |
| `os.walk()` file traversal | Scanning 1,300+ eSim library files |
| Object-oriented design | 10+ cooperating classes |
| Caching | `ModelMatcher._cache` dict for repeated lookups |
| Binary file parsing | ngspice `.raw` file format (ASCII and binary) |
| Signal processing | FFT via `numpy.fft.rfft`, Bode plot from complex data |
| matplotlib embedding | FigureCanvasWxAgg backend inside wx.Dialog |
| matplotlib events | `motion_notify_event` for cursor readout |

**Electronics concepts applied:**

| Concept | Application |
|---|---|
| SPICE netlist syntax | `.model`, `.subckt`, `.tran`, `.ac`, `.dc`, `.op`, `.tf`, `.sens`, `.noise` |
| BJT pin ordering | collector/base/emitter mapping from KiCad pin numbers |
| MOSFET pin ordering | drain/gate/source/bulk in SPICE |
| Diode polarity | KiCad pin 1=Cathode, pin 2=Anode → SPICE anode/cathode order |
| ngspice analysis types | Transient, AC, DC, OP, Noise, TF, Sensitivity |
| Transfer function | Gain = V(out)/V(in), input/output impedance |
| Sensitivity analysis | dV(out)/d(component) — DC linearization |
| Noise analysis | inoise (input-referred), onoise (output) in V/√Hz |
| Bode plots | Gain (dB) + Phase (°) vs frequency |
| FFT | Frequency spectrum of time-domain signals |
| Voltage divider | Demo circuit for all analysis types |
| Why MCUs cannot be SPICE-simulated | Firmware execution vs. analog differential equations |
| eSim project file format | `.cir`, `.cir.out`, `.proj`, `analysis`, `plot_data_v.txt` |

---

## 8. Testing

### 8.1 Demo Circuit — Voltage Divider

*[Screenshot: KiCad schematic of voltage divider with R1=10k, R2=10k, V1=VSIN]*

| Component | Value | Notes |
|---|---|---|
| R1 | 10kΩ | Series resistor |
| R2 | 10kΩ | Shunt resistor |
| V1 | VSIN: dc=0, ampl=1, f=1k, ac=1 | Input source |

Expected simulation results:

| Analysis | Expected Output |
|---|---|
| Transient | vmid shows 0.5V peak sine at 1kHz |
| AC Sweep | Flat gain at −6dB (0.5 ratio) across all frequencies |
| DC Sweep | Linear vmid = V1/2 |
| Operating Point | vmid = 0V (dc=0 source has no DC component) |
| Noise | inoise and onoise values computed at specified frequency |
| Transfer Function | gain=0.5, input=20kΩ, output=5kΩ |
| FFT (transient) | Single spike at 1kHz, magnitude ~0.5V |
| Bode Plot (AC) | Flat −6dB gain, 0° phase across all frequencies |
| Sensitivity (dc=1) | v1=0.5, r1 negative, r2 positive |

### 8.2 Test Scenarios Verified

| Test Circuit | Expected Result | Status |
|---|---|---|
| Voltage divider — transient | vmid = 0.5V peak | PASS |
| Voltage divider — AC | Flat 0.5 gain (−6dB) | PASS |
| Voltage divider — DC sweep | Linear vmid = V1/2 | PASS |
| Voltage divider — Operating Point | vmid = 0V (dc=0 source) | PASS |
| Voltage divider — TF | gain=0.5, Zin=20k, Zout=5k | PASS |
| Voltage divider — FFT | Spike at 1kHz | PASS |
| Voltage divider — Bode | Flat dB, 0° phase | PASS |
| Voltage divider — Sensitivity | v1=0.5 (with dc=1) | PASS |
| Voltage divider — Noise | inoise/onoise values shown | PASS |
| BJT amplifier (BC547) | FOUND in eSim Transistor lib | PASS |
| Diode rectifier (1N4148) | FOUND in eSim Diode lib | PASS |
| LED circuit | FOUND (eSim LED lib) | PASS |
| ATtiny85 schematic | MISSING status (correct) | PASS |
| NAND gate (7400) | EQUIV via SN74LS00 | PASS |
| LDR circuit (R2="5mm LDR") | Sanitized to 1k | PASS |
| Microphone circuit (MK1) | 10mV AC source substitution | PASS |
| Floating node detection | Error shown before simulation | PASS |
| Missing GND detection | Error shown before simulation | PASS |
| Voltage source short detection | Error shown before simulation | PASS |
| Orphan component detection | Warning shown before simulation | PASS |
| DC path violation detection | Warning shown before simulation | PASS |
| .spiceinit auto-creation | set ngbehavior=ps written silently | PASS |
| Parametric sweep (R1: 1k→100k) | 5 overlaid sine waves | PASS |
| Measurement (RMS, freq) | Correct values from zero-crossing | PASS |

---

## 9. Technical Decisions and Bugs Resolved

This section documents significant technical challenges encountered during development and the solutions implemented. These are important for understanding non-obvious design choices.

| Issue | Root Cause | Resolution |
|---|---|---|
| `MK` prefix caught by `M` (MOSFET) handler | Python `str.startswith('M')` matched both `M` and `MK` components | Multi-char prefixes (`MK`, `BT`, `SW`) now checked first in strict priority order before single-char prefixes |
| Duplicate `.model` entries in SPICE output | eSim-SPICE injected models that were already present from SPICEModelLibrary | `_rewrite_with_models()` reads all existing `.model` and `.subckt` names via regex before appending — deduplicates |
| `TypeError: check_models() got unexpected keyword argument 'skip_model_names'` | Removed kwarg from function signature but call site still passed it | Removed `skip_model_names=` argument from all call sites |
| `VMK1` node polarity reversed | KiCad MK symbol has GND on pin 1; SPICE source needs positive terminal first | `VMK1` is written as `VMK1 <non-gnd-node> 0 AC 0.01 SIN(...)` — positive terminal is always the non-GND node |
| Library scanner undercounted models | Hardcoded subdirectory whitelist missed eSim's full folder structure | Replaced whitelist with `os.walk()` recursive scan — indexes all 61 device model categories and 586+ subcircuit folders |
| 74xx IC never matched | `7400` does not match `SN74LS00` under any simple string comparison | Added dedicated `_match_74xx()` function that tries manufacturer-prefixed variants (`sn74ls00`, `sn74hc00`, `sn74`, `cd40`) |
| `SW*` prefix triggering model search | Switch prefix `SW` was being sent to the IC lookup cascade | `SW*` is now explicitly classified as `STATUS_PASSIVE` and converted to a 1Ω resistor — no `.model` card written |
| KiCad startup timeout | `esim_spice_linker.py` was imported at module level, causing a ~2s library scan on every KiCad startup | Moved `import` of `SPICEAutoLinker` to inside `Run()` body — only runs when user clicks the toolbar button |
| `sys.path` not including plugin directory | KiCad does not automatically add the plugin folder to Python's `sys.path` | `sys.path.insert(0, plugin_dir)` called immediately before the `SPICEAutoLinker` import |
| Stale `.pyc` bytecode | KiCad loads cached `.pyc` files — code changes not seen until cache cleared | Documented: `rm -rf __pycache__` required after every code change |
| R2 value `"5mm LDR"` causing ngspice parse error | KiCad value field contained a space and descriptive text, not a numeric resistance | `SPICEConverter` applies regex to strip everything after the first space, then validates remaining string is a valid SPICE value; falls back to `1k` if invalid |
| Sensitivity analysis all zeros | `.sens` command requires a non-zero DC operating point to linearize around | Documented as user action: set `dc=1` on voltage source; warning shown in results popup |
| UTF-8 decode error popup in eSim 2.5 | eSim's internal plotter tries to read a stale `.raw` binary file from a previous session | Plugin attempts to delete stale `.raw` files before launching eSim; documented as known eSim 2.5 cosmetic bug |
| `StaticBoxSizer.Show(False)` not collapsing layout on Linux | wxPython `StaticBoxSizer` does not release vertical space when hidden on GTK | Each analysis panel uses a `wx.Panel` wrapper — `panel.Show(False)` correctly collapses layout |
| eSim does not accept CLI project path argument | `Application.py` has no argparse; project selection is GUI-only | ESimLauncher launches eSim without arguments; user double-clicks project in eSim GUI — documented in known limitations |

---



The plugin suite is designed to be extended without modifying core code.

**Adding new component models:**
- Drop a `.lib`, `.mod`, or `.sub` file in `~/.esim-bridge/models/` — auto-discovered at next run
- Add entries to `SPICEModelLibrary` class dictionaries for hardcoded common models
- Add entries to `TextbookModelGenerator.TEXTBOOK_*` dicts for last-resort fallbacks

**Adding new component types:**
- Add a new prefix handler block in `SPICEConverter.component_to_spice()`

**Adding new analysis types:**
- Add a `wx.CheckBox` in `_build_analysis_tab()` with a matching panel
- Add a `_make_<type>_group()` method
- Add collection in `_collect_analysis()`
- Add case in `SPICEConverter.get_analysis_command()`
- Add case in the `.control` block builder in `ESimBridgePlugin.Run()`
- Add result handler in `Run()` (for non-waveform results)

**Adding new eSim library sources:**
- `ESimLibraryScanner` uses `os.walk()` — any new library folder added to eSim will be auto-scanned

---

## 10. Extensibility

The plugin suite is designed to be extended without modifying core code.

**Adding new component models:**
- Drop a `.lib`, `.mod`, or `.sub` file in `~/.esim-bridge/models/` — auto-discovered at next run, no code changes needed
- Add entries to `SPICEModelLibrary` class dictionaries for hardcoded common models
- Add entries to `TextbookModelGenerator.TEXTBOOK_*` dicts for last-resort textbook fallbacks

**Adding new component types:**
- Add a new prefix handler block in `SPICEConverter.component_to_spice()` — prefix length determines priority order

**Adding new analysis types:**
- Add a `wx.CheckBox` in `_build_analysis_tab()` with a matching `wx.Panel`
- Add a `_make_<type>_group()` method with the analysis parameter widgets
- Add collection in `_collect_analysis()`
- Add a case in `SPICEConverter.get_analysis_command()`
- Add a case in the `.control` block builder in `ESimBridgePlugin.Run()`
- Add result handler in `Run()` (popup for scalar results, waveform viewer for time/freq data)

**Adding new eSim library sources:**
- `ESimLibraryScanner` uses `os.walk()` recursively — any new library folder eSim adds is automatically indexed without code changes

---

## 11. Future Work

The following features were identified during development but are outside the scope of this submission. They are documented here as planned future work:

| Feature | Description | Difficulty |
|---|---|---|
| **Pole-Zero analysis (.pz)** | Filter and amplifier stability analysis | Medium |
| **Monte Carlo simulation** | Statistical tolerance analysis using AGAUSS()/AUNIF() | Medium |
| **Periodic Steady State (pss)** | RF and switching circuit analysis | High |
| **XSPICE behavioral tab** | A-prefix components (a_gain, a_integrator, d_state_machine) | High |
| **Transmission line support** | Native T (lossless) and O (lossy) elements | Medium |
| **Username portability** | Replace hardcoded paths with `os.path.expanduser('~')` | Low |
| **Multiple project folders** | Support simultaneous projects | Medium |
| **KiCad 9 native project detection** | Better schematic path resolution | Low |
| **Behavioral models for LDRs** | B-element models for light-dependent resistors | Medium |
| **Full NGHDL integration** | Complete microcontroller simulation via NGHDL | Very High |
| **ngspice-45.2 (KiCad 10)** | Leverage natively bundled ngspice in KiCad 10 | Medium |

---

## 12. File Inventory

| File | Description |
|---|---|
| `KiCad_Plugin/esim_bridge.py` | eSim-BRIDGE v2.1.0 — main plugin |
| `KiCad_Plugin/esim_spice_linker.py` | eSim-SPICE v1.0.0 — model auto-linker |
| `KiCad_Plugin/icon.png` | KiCad toolbar icon |
| `KiCad_Plugin/__init__.py` | Package entry point |
| `README.md` | User installation and usage guide |
| `DESIGN_DOCUMENT.md` | This document — architecture and design |
| `INSTALLATION_GUIDE.md` | Step-by-step installation for all environments |
| `KNOWN_LIMITATIONS.md` | Comprehensive limitations reference |
| `QUICK_REFERENCE.md` | One-page cheat sheet for common tasks |
| `metadata.json` | KiCad Plugin Manager metadata |

---

*Imran Farhat — FOSSEE Semester Long Internship Spring 2026, IIT Bombay*
*Submitted for Task 6: KiCad Plugin Development*
