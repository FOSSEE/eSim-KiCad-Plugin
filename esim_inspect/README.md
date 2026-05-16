# eSim-Inspect 
#### Report Generator

--- 
> A KiCad Action Plugin that automates schematic design review and generates eSim simulation readiness report.

Developed by Dipanshu Katole under **FOSSEE, IIT Bombay** - part of the open-source eSim EDA toolchain.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
  - [Windows](#windows)
  - [Linux](#linux)
- [Usage](#usage)
- [Project Structure](#project-structure)
- [Module Documentation](#module-documentation)
  - [esim_inspect_action.py](#esim_inspect_actionpy)
  - [schematic_parser.py](#schematic_parserpy)
  - [topology_builder.py](#topology_builderpy)
  - [design_analyzer.py](#design_analyzerpy)
  - [report_generator.py](#report_generatorpy)
- [Report Output](#report-output)
- [Known Limitations](#known-limitations)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgements](#acknowledgements)

---

## Overview

**eSim-Inspect** is a KiCad 9.0 plugin that reads your `.kicad_sch` schematic file, parses component and wire data, builds a circuit topology graph and generates an HTML design review report - all from within the KiCad PCB Editor with one click.

The report flags:

- missing component values or references
- dangling/floating nets
- SPICE simulation readiness of each component
- ERC (Electrical Rules Check) errors and warnings

Additionally, the report includes an interactive and adjustable circuit diagram view, allowing users to zoom and inspect the schematic visually for better analysis.

This plugin is designed for students and engineers who want a quick and reliable sanity check before running simulations, all in one integrated workflow.

---

## Features

| Feature | Description |
|---|---|
| Schematic parsing | Reads `.kicad_sch` S-expression format directly |
| Topology graph | Builds a net-based graph using NetworkX |
| SPICE coverage check | Classifies every component as executable / incomplete / non-executable |
| ERC checks | Detects unconnected pins, duplicate refs, missing power symbols |
| Dangling net detection | Finds nets connected to fewer than 2 pins |
| HTML report | Opens automatically in the browser after generation |
| Cross-platform | Tested on latest Windows 10/11 (KiCad 9.0) and Linux Ubuntu 25.10 |

---

[View PDF Report](eSim-KiCad-Plugin\esim_inspect\DesignInspectionReport_LED.pdf)

---

## Requirements

| Dependency | Version |
|---|---|
| KiCad | 9.0 |
| Python | 3.x (bundled with KiCad) |
| sexpdata | Included with KiCad Python env or install via pip |
| networkx | Included with KiCad Python env or install via pip |

> **Note:** KiCad 9.0 ships its own Python environment. You do not need a separate Python installation.

---

## Installation

### Windows

1. Download or clone this repository:

   ```bash
   git clone https://github.com/DipanshuK04/eSimInspect_Kicad_ReportGenerator_Plugin.git
   ```

2. Copy the entire `esim_inspect/` folder (the one containing `esim_inspect_action.py`) into your KiCad scripting plugins directory:

   ```
   C:\Users\<your_username>\Documents\KiCad\9.0\scripting\plugins\
   ```

   If the `plugins\` folder does not exist, create it manually.

3. Open **KiCad** → open the **PCB Editor** (`.kicad_pcb`).

4. In the PCB Editor, go to **Tools → External Plugins → Refresh Plugins**.

5. The **eSim-Inspect** button will now appear in the toolbar.

### Linux

1. Clone the repository:

   ```bash
   git clone https://github.com/DipanshuK04/eSimInspect_Kicad_ReportGenerator_Plugin.git
   ```

2. Copy the plugin folder to the KiCad scripting plugins directory:

   ```bash
   cp -r esim_inspect/ ~/.local/share/kicad/9.0/scripting/plugins/
   ```

   > On some systems the path may be `/usr/lib/kicad/lib/python3/dist-packages/` or `/usr/share/kicad/scripting/plugins/`. Check via KiCad → **Scripting Console** → `import pcbnew; print(pcbnew.PLUGIN_DIRECTORIES_SEARCH)`.

3. Open KiCad → PCB Editor → **Tools → External Plugins → Refresh Plugins**.

4. The eSim-Inspect icon will appear in the toolbar.

---

## Usage

> Make sure your KiCad project has both a `.kicad_pcb` and a `.kicad_sch` file with the **same project name** in the same folder.

1. **Design your circuit** in the KiCad Schematic Editor and save it.

2. **Open the PCB Editor** from KiCad's main project window.

3. Click the **eSim-Inspect** toolbar button (or go to **Tools → External Plugins → eSim-Inspect**).

4. The plugin will:
   - Parse your `.kicad_sch` file
   - Build the circuit topology graph
   - Run design analysis and ERC checks
   - Save a `Parsed_sch.txt` debug file in your project folder
   - Generate an HTML report in your project folder
   - **Automatically open the report in your default browser**

5. Review the report. Fix any flagged issues in your schematic and re-run the plugin.
6. Plugin provides a button to download the generated report. 

---

## Project Structure

```
esim_inspect/
│
├── esim_inspect_action.py    # Entry point — KiCad ActionPlugin, orchestrates the pipeline
├── schematic_parser.py       # Parses .kicad_sch S-expression file
├── topology_builder.py       # Builds NetworkX graph from components and wires
├── design_analyzer.py        # Runs all design checks and ERC rules
├── report_generator.py       # Generates the HTML report
├── Rg.png                    # Toolbar icon
└── README.md                 # This file
```

---

## Module Documentation

### `esim_inspect_action.py`

The KiCad plugin entry point. Inherits from `pcbnew.ActionPlugin`.

**Class: `ESimInspectPlugin`**

Registered as a KiCad Action Plugin. When triggered, it:

1. Gets the current board file path from `pcbnew.GetBoard()`
2. Resolves the matching `.kicad_sch` file from the same project directory
3. Passes the schematic data through the full pipeline:
   `Extract_Information` → `TopologyBuilder` → `DesignAnalyzer` → `ReportGenerator`
4. Opens the generated HTML report in the browser via `webbrowser.open()`

**Import strategy:** Uses a `try/except` import block to handle the difference between how KiCad loads plugins on Windows (relative imports work) versus Linux (absolute imports required).

---

### `schematic_parser.py`

**Class: `Extract_Information`**

Parses a raw `.kicad_sch` file string using the `sexpdata` library (KiCad uses S-expression format).

| Method | Returns | Description |
|---|---|---|
| `find_components()` | `list[dict]` | Extracts all `symbol` entries: `type`, `ref`, `value`, `Sim.*` properties, `pos`, `angle` |
| `get_wires()` | `list[tuple]` | Extracts all wire segments as pairs of `[x, y]` coordinate points |
| `extract_symbol_pins()` | `dict` | Extracts pin definitions from `lib_symbols` section; maps `lib_name → list of pins` with position and rotation |
| `get_absolute_pins(components, symbol_pins)` | `list[dict]` | Transforms pin positions from component-local coordinates to schematic absolute coordinates using rotation matrix |

**Coordinate transform in `get_absolute_pins`:**

Each component has a position `(base_x, base_y)` and a rotation angle. Pin positions stored in the library are relative to the component origin. The method rotates each pin position by the component's angle and then translates it:

```
x_rot = px * cos(θ) - py * sin(θ)
y_rot = px * sin(θ) + py * cos(θ)
x_final = base_x + x_rot
y_final = base_y + y_rot
```

---

### `topology_builder.py`

**Class: `TopologyBuilder`**

Builds a [NetworkX](https://networkx.org/) graph representing circuit connectivity.

| Method | Returns | Description |
|---|---|---|
| `is_point_on_wire(point, wire, tol=0.2)` | `bool` | Checks if a point lies on a horizontal or vertical wire segment, within tolerance `tol` |
| `build_graph(pin_positions)` | `nx.Graph` | Main graph builder — see below |
| `build_component_graph(graph)` | `nx.Graph` | Builds a component-level graph (components as nodes, shared nets as edges) |

**`build_graph` algorithm:**

1. Add each pin as a node (format: `"REF_pinnumber"`, e.g. `"R1_1"`)
2. Build a wire connectivity graph using wire endpoints as nodes
3. Find connected groups of wires using `nx.connected_components` — each group becomes one net
4. For each pin, find which net group it belongs to by matching its absolute position to wire endpoints (exact match within 0.2 mm tolerance) or to a mid-point on a wire segment
5. Add a `NET_<idx>` node for each net group, with edges to all pins on that net

**Tolerance:** A floating-point tolerance of `0.2` mm is used for all position matching to account for rounding in KiCad's coordinate representation.

---

### `design_analyzer.py`

**Class: `DesignAnalyzer`**

Runs all design rule checks on the parsed data.

**Constructor parameters:**

| Parameter | Type | Description |
|---|---|---|
| `components` | `list[dict]` | Output of `find_components()` |
| `graph` | `nx.Graph` | Output of `build_graph()` |
| `wires` | `list` | Output of `get_wires()` |
| `pin_positions` | `dict` | Optional; output of `get_absolute_pins()` |

**Component classification sets:**

| Set | Members | Rule |
|---|---|---|
| `STANDARD_MODELS` | D, LED, Zener, BJT, MOSFET | Need `Sim.Device` + `Sim.Pins` |
| `COMPLEX` | Opamp, Opamp_Dual | Need `Sim.Device` (subcircuit) |
| `NON_ELECTRICAL` | MountingHole, TestPoint, PWR_FLAG | Never simulate |

**Methods:**

| Method | Returns | Description |
|---|---|---|
| `check_missing_values()` | `list[dict]` | Components with empty `value` field |
| `check_missing_refs()` | `list[dict]` | Components whose reference starts with `?` |
| `check_spice_models()` | `dict` | Classifies all components into `executable`, `incomplete`, `non_executable`, `non_sim` |
| `find_dangling_nets(graph)` | `list[dict]` | Nets with 0 or 1 connected pins |
| `erc_unconnected_pins()` | `list[dict]` | Pin nodes in the graph with degree 0 |
| `erc_duplicate_refs()` | `list[dict]` | Reference designators appearing more than once |
| `erc_no_power_symbol()` | `list[dict]` | Warning if no voltage source or power symbol found |
| `da_report()` | `dict` | Aggregates all checks into a single report dict |

**`check_spice_models` classification logic:**

```
Passives (R, C, L)         → executable if value present, else incomplete
Sources (Battery, V, I)    → executable if value + Sim.Type present
Standard models (D, BJT…)  → executable if Sim.Device + Sim.Pins present
Complex (Opamp)            → executable if Sim.Device present
Non-electrical             → non_sim (skip)
Unknown                    → non_executable if no Sim.* keys at all
```

---

### `report_generator.py`

Generates the HTML report file.

> *(Document this module once the code is shared)*

The report is saved to the project directory and opened automatically via `webbrowser.open()`.

---

## Report Output

The generated HTML report includes the following sections:

- **Project info** - schematic file name, generation timestamp
- **Component summary** - total count, breakdown by type
- **SPICE coverage** - table of executable / incomplete / non-executable / non-sim components
- **Missing values / refs** - list of components needing attention
- **Dangling nets** - nets that are floating or connected to only one pin
- **ERC results** - errors and warnings with severity labels

The report file is saved as `<project_name>_report.html` (or similar) inside your KiCad project folder.

---

## Known Limitations

- Only horizontal and vertical wire segments are supported for mid-point pin matching. Diagonal wires are not handled.
- Bus wires are not currently parsed.
- The plugin reads the `.kicad_sch` file from disk — unsaved schematic changes will not appear in the report.
- The `.kicad_sch` and `.kicad_pcb` files must share the same project name and be in the same folder.
- Tested on latest KiCad 9.0. Compatibility with KiCad 7.x or 8.x is not guaranteed due to S-expression format differences.

---

## Contributing

Contributions are welcome! This is an open-source project under FOSSEE, IIT Bombay.

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Make your changes with clear commit messages
4. Ensure the plugin loads correctly in KiCad (refresh plugins and test)
5. Open a pull request describing what you changed and why

**Reporting bugs:** Open a GitHub Issue and include:
- Your KiCad version and OS
- The error message (from KiCad's Scripting Console)
- A minimal `.kicad_sch` file that reproduces the issue (if possible)

For FOSSEE-related discussion, you can also reach out via the [eSim forums](https://esim.fossee.in/).

---


## Acknowledgements

- **FOSSEE, IIT Bombay** — for supporting open-source EDA tools and the eSim project
- **KiCad** — for the extensible plugin architecture and `pcbnew` Python API
- **NetworkX** — for the graph library used in topology analysis
- **sexpdata** — for S-expression parsing of KiCad schematic files

---

*eSim-Inspect is part of the eSim open-source EDA ecosystem. For more about eSim, visit [esim.fossee.in](https://esim.fossee.in/).*