# KiCad Design Diary

A native KiCad PCB editor plugin that records, compares, and replays the history of a hardware design in plain English. Design Diary captures every save as a structured snapshot, integrates with eSim and ngspice for SPICE simulation, and produces a portable HTML report of the entire design lifecycle.

This document is intended as both a user guide and a developer handoff. It explains what the plugin does, how it is architected, how each user action flows through the codebase, and where to extend it without breaking existing functionality.

---

## Table of Contents

1. [Overview](#overview)
2. [User-facing Features](#user-facing-features)
3. [Installation](#installation)
4. [Quick Start](#quick-start)
5. [Repository Layout](#repository-layout)
6. [Architecture](#architecture)
7. [Data Model](#data-model)
8. [Module Reference](#module-reference)
9. [Sequence Walks](#sequence-walks)
10. [Extending the Plugin](#extending-the-plugin)
11. [Known Limitations](#known-limitations)
12. [Development Environment](#development-environment)
13. [Debugging Guide](#debugging-guide)
14. [License and Author](#license-and-author)

---

## Overview

Hardware engineers working in KiCad have no native way to track the semantic history of a design. KiCad's undo stack is volatile and is discarded when the project closes. Git captures binary file changes but cannot describe what changed at the level of design intent. A user who modifies the value of `R1` from `22k` to `47k`, repositions three footprints, and adds a decoupling capacitor has no automated mechanism to replay those changes as a human-readable history.

Design Diary fills that gap. It treats a KiCad project as a versioned design artifact, captures every save as a semantic snapshot, diffs successive snapshots into plain-English change records, and exposes the full timeline through an interactive panel inside the PCB editor. It also bridges the gap between layout and simulation: a designer can run SPICE simulations through eSim and ngspice without leaving the plugin, view interactive waveform plots, and receive friendly explanations when a circuit is not amenable to SPICE simulation.

The plugin is a pure-Python KiCad ActionPlugin with no dependencies outside the KiCad scripting environment.

---

## User-facing Features

**Automatic snapshotting.** Every save of a `.kicad_pcb` or `.kicad_sch` file produces a structured JSON snapshot containing component references, values, footprints, positions, net connectivity, and a parsed schematic representation. Snapshots are stored in a hidden `.design_diary_<project>` folder colocated with the project.

**Semantic diff engine.** Successive snapshots are compared at the level of design intent rather than raw text. The engine detects added components, deleted components, value changes, footprint changes, and schematic edits via S-expression parsing of the `.kicad_sch` file. Each change is rendered as a sentence such as *"Changed value of C2 from 10nF to 100nF"* or *"Added component R7 with value 1k"*.

**Snapshot tagging and rollback.** Any snapshot can be tagged with a human-readable name. Users can roll back the live design to any snapshot directly from the timeline. A rollback writes the historical state back to the working `.kicad_pcb` while preserving the rolled-over state in history.

**Snapshot comparison.** Any two snapshots can be selected and compared side by side, enumerating added, removed, and modified components between the two points in time.

**Component history.** A per-component view shows the full lifetime of any reference designator: when it was added, every value change it underwent, every footprint swap, and the final state. This is the equivalent of `git log -- <file>` but for an individual component on a board.

**SPICE simulation pipeline.** When a `.cir` netlist exists for the project, the plugin runs a full transient simulation in batch ngspice mode, captures the `.raw` output, and renders an interactive multi-signal waveform plot as a standalone HTML file. The plot supports per-signal toggling and automatic time-axis scaling.

**Non-simulatable circuit detection.** Boards built around microcontrollers, programmers, EEPROMs, and digital logic chips fall outside what SPICE can model without custom libraries. Design Diary inspects the board for such components and presents a clear non-technical message explaining why simulation is not applicable, rather than producing cryptic ngspice errors. The first such message for a given circuit is delivered as a popup; subsequent attempts on the same circuit show a condensed inline notice.

**ngspice error translation.** When ngspice fails despite a circuit appearing simulatable, Design Diary parses the error output and translates common failure modes (unknown subcircuit, no convergence, singular matrix, parse error) into actionable plain-English explanations.

**Stale netlist detection.** When the schematic has changed since the last `.cir` was generated, Design Diary detects the divergence and prompts the user to regenerate the netlist before running simulation, preventing silent simulation of an outdated design.

**HTML design report.** A single-button export produces a self-contained HTML report covering the entire project history: full timeline, every snapshot, every change, every tagged checkpoint, every simulation run, and embedded waveform plots. The report uses a custom typography pairing of DM Serif Display and IBM Plex Sans on a warm low-contrast palette.

**eSim integration.** A *Launch eSim* control opens the eSim suite directly from the plugin window so users can move between layout and simulation without manual file navigation.

---

## Installation

1. Clone or download this repository.
2. Copy the `kicad_design_diary` folder into your KiCad scripting plugins directory:
   - **Windows**: `%USERPROFILE%\Documents\KiCad\9.0\scripting\plugins\`
   - **Linux**: `~/.local/share/kicad/9.0/scripting/plugins/`
   - **macOS**: `~/Library/Application Support/kicad/9.0/scripting/plugins/`
3. Restart KiCad, or refresh plugins from *Tools → External Plugins → Refresh Plugins*.
4. The plugin will appear in the PCB editor under *Tools → External Plugins → KiCad Design Diary*.

Simulation features require eSim. The plugin auto-detects eSim and ngspice at the standard FOSSEE installation paths (`C:\FOSSEE\eSim\`, `C:\FOSSEE\nghdl-simulator\`); no configuration is required if these paths exist.

---

## Quick Start

Open any KiCad PCB project and launch the plugin from *Tools → External Plugins → KiCad Design Diary*. The timeline panel opens alongside the PCB editor and immediately captures the current state as the first snapshot. Every subsequent save produces a new snapshot automatically.

To compare two points in history, select two snapshots and click *Compare Snapshots*. To see the lifetime of a single component, click *Component History*. To roll the design back to a historical state, select the snapshot and click *Rollback*. To run a SPICE simulation, click *Run Simulation*. To open the schematic in eSim, click *Launch eSim*. To produce a portable design history document, click *Export HTML Report*.

---

## Repository Layout

```
kicad-design-diary/
  kicad_design_diary/
    __init__.py              Plugin entry point; registers with KiCad
    plugin.py                Core plugin class, snapshot capture, save listener
    ui_panel.py              wxPython timeline UI, all dialogs, comparison views
    simulation_engine.py     ngspice integration, .cir handling, plot generation
    board_listener.py        Save-event listener that triggers snapshots
    metadata.json            Plugin metadata for KiCad's plugin manager
  README.md                  This document
  LICENSE                    MIT
```

---

## Architecture

### Module Dependency Graph

```
                       +--------------------+
                       |   __init__.py      |
                       |  (registration)    |
                       +---------+----------+
                                 |
                                 v
                       +--------------------+
                       |     plugin.py      |
                       | +----------------+ |
                       | | snapshot_engine| |
                       | |  (semantic     | |
                       | |   diff logic)  | |
                       | +----------------+ |
                       +----+---------+-----+
                            |         |
              +-------------+         +------------+
              |                                    |
              v                                    v
   +--------------------+               +--------------------+
   | board_listener.py  |               |   ui_panel.py      |
   | (save-event hook)  |               | (wxPython UI)      |
   +--------------------+               +---------+----------+
                                                  |
                                                  v
                                       +--------------------+
                                       | simulation_engine  |
                                       | (ngspice + eSim)   |
                                       +---------+----------+
                                                 |
                                                 v
                                       +--------------------+
                                       |  external: ngspice |
                                       |  external: eSim    |
                                       +--------------------+
```

`plugin.py` is the hub. It is imported by `__init__.py` for registration, owns the snapshot logic that `board_listener.py` triggers, and is referenced by `ui_panel.py` for snapshot helpers. `ui_panel.py` is the only module that touches `simulation_engine.py`. `simulation_engine.py` is self-contained: it never imports any other plugin module, which makes it easy to test in isolation.

### Data Flow When the User Saves a Project

```
   User saves the project (Ctrl+S)
                |
                v
   KiCad fires a board-save event
                |
                v
   board_listener.py catches it
                |
                v
   plugin.py captures current state:
     - Iterates board.GetFootprints()
     - Records ref, value, footprint, position
     - Parses .kicad_sch via S-expressions
                |
                v
   snapshot_engine diffs against previous
                |
                v
   Plain-English changes generated:
     "Added component R7 with value 1k"
     "Changed value of C2 from 10nF to 100nF"
                |
                v
   JSON snapshot written to:
     .design_diary_<project>/YYYYMMDD_HHMMSS.json
                |
                v
   ui_panel timeline refreshes
```

### Data Flow When the User Clicks "Run Simulation"

```
   User clicks "Run Simulation"
                |
                v
   ui_panel.on_run_simulation()
                |
                v
   Captures components from board
                |
                v
   engine.find_cir_file()  -----> returns path or None
                |
                v
   engine.get_simulatability_status(cir_path, components)
                |
        +-------+-------+
        |               |
   simulatable?     not simulatable?
        |               |
        v               v
   has cir_path?    First time on this circuit?
        |           +---+---+
   +----+----+     yes      no
   yes       no    |         |
   |         |     v         v
   v         v   long       short
  run    prompt  popup     popup
ngspice  eSim     |         |
   |              +----+----+
   v                   v
 parse .raw       mark_warning_shown()
   |                   |
   v                   v
 build HTML plot     return
   |
   v
 return
```

The `get_simulatability_status` call is the single decision point. Everything downstream (popup vs inline, run-or-skip) branches from its return value.

---

## Data Model

### Snapshot File Naming

Files in `.design_diary_<project>/` follow these prefixes:

| Pattern                       | Meaning                                              | Example                              |
|-------------------------------|------------------------------------------------------|--------------------------------------|
| `YYYYMMDD_HHMMSS.json`        | Canonical project snapshot (board + schematic)       | `20260421_223811.json`               |
| `SCH_YYYYMMDD_HHMMSS.json`    | Schematic-only snapshot (parsed from `.kicad_sch`)   | `SCH_20260421_223811.json`           |
| `RUN_YYYYMMDD_HHMMSS.json`    | Simulation run record                                | `RUN_20260421_223827.json`           |
| `sim_run_*.raw`               | Raw ngspice output                                   | `sim_run_20260421_223826.raw`        |
| `sim_run_*.log`               | ngspice console log                                  | `sim_run_20260421_223827.log`        |
| `sim_plot_*.html`             | Generated interactive waveform plot                  | `sim_plot_20260421_223828.html`      |
| `design_diary_report.html`    | Exported HTML report                                 | (single file, overwritten on export) |
| `_*.json`                     | Internal plugin state (warnings shown, etc.)         | `_sim_warning_shown.json`            |

The prefix scheme is meaningful. Filtering snapshots by prefix is how the UI separates intent. For example, the component-history view reads only canonical snapshots and ignores `SCH_`, `RUN_`, and `_` files.

### Canonical Snapshot Structure

```json
{
  "timestamp": "2026-04-21 22:38:11",
  "type": "snapshot",
  "components": {
    "R1": {
      "value": "22k",
      "footprint": "Resistor_SMD:R_0805",
      "position": [10.0, 5.0]
    },
    "C1": {
      "value": "10uF",
      "footprint": "Capacitor_SMD:C_0805",
      "position": [12.0, 5.0]
    }
  },
  "schematic": {
    "components": [],
    "wires": []
  },
  "changes": [
    "Schematic: Added component R1 with value 22k",
    "Schematic: Added component C1 with value 10uF"
  ],
  "tag": null
}
```

### Simulation Record Structure

```json
{
  "timestamp": "2026-04-21 22:38:27",
  "type": "simulation_result",
  "cir_file": "/tmp/dd_sim_20260421_223827.cir",
  "raw_file": "/path/to/.design_diary_555/sim_run_20260421_223827.raw",
  "log_file": "/path/to/.design_diary_555/sim_run_20260421_223827.log",
  "success": true,
  "returncode": 0,
  "errors_found": [],
  "changes": ["SIMULATION: Passed -- ran ngspice on 555_timer.cir"]
}
```

The format is intentionally human-readable and forward-compatible. Snapshots from older versions of the plugin remain readable by newer versions.

---

## Module Reference

### `__init__.py`

Two-line entry point. Imports `DesignDiaryPlugin` from `plugin.py` and registers it with KiCad. Do not add logic here. Registration must remain trivial so KiCad startup is never blocked by plugin initialization.

### `plugin.py`

Owns the plugin lifecycle, snapshot capture, and the semantic diff engine. Key entry points:

| Function or Method                                | Purpose                                                                  |
|---------------------------------------------------|--------------------------------------------------------------------------|
| `DesignDiaryPlugin.defaults`                      | Sets plugin name, category, and toolbar visibility for KiCad             |
| `DesignDiaryPlugin.Run`                           | Invoked when the user clicks the plugin; opens the timeline panel        |
| `DesignDiaryPlugin.snapshot_components(board)`    | Static helper that captures the current board state as a components dict |
| `take_snapshot(project, board)`                   | Writes a canonical snapshot to `.design_diary_<project>/`                |
| `diff_snapshots(prev, current)`                   | Produces the list of plain-English change strings                        |
| `parse_schematic(sch_path)`                       | Parses a `.kicad_sch` file via S-expressions                             |

The snapshot engine inside `plugin.py` is structured so that diffing is purely functional: it takes two snapshot dicts and returns a list of strings, with no I/O. This makes it easy to test and reason about.

### `ui_panel.py`

All wxPython UI lives here. The panel is a single class (`DiaryPanel`) with one method per button:

| Button or Action            | Handler Method                | Notes                                                       |
|-----------------------------|-------------------------------|-------------------------------------------------------------|
| Run Simulation              | `on_run_simulation`           | Decision tree for simulatable / non-simulatable / no .cir   |
| Launch eSim                 | `on_launch_esim`              | Delegates to `simulation_engine.launch_esim()`              |
| Mark Checkpoint             | `on_mark_checkpoint`          | Tags current snapshot for sim-vs-schematic alignment        |
| Rollback                    | `on_rollback`                 | Writes selected snapshot back to live `.kicad_pcb`          |
| Component History           | `on_component_history`        | Opens `ComponentHistoryFrame` dialog                        |
| Tag Snapshot                | `on_tag_snapshot`             | Persists a human-readable label to the snapshot             |
| Compare Snapshots           | `on_compare_snapshots`        | Opens side-by-side diff view                                |
| Export HTML Report          | `on_export_report`            | Generates `design_diary_report.html`                        |

Two helper subclasses live at the bottom of the file: `ComponentHistoryFrame` (the per-component-history popup) and the comparison dialog. Both read snapshots independently from disk; neither holds long-lived references to the panel.

### `simulation_engine.py`

The simulation pipeline. Self-contained; imports nothing from other plugin modules. The class `SimulationEngine` exposes:

| Method                                              | Purpose                                                              |
|-----------------------------------------------------|----------------------------------------------------------------------|
| `find_cir_file()`                                   | Locates the `.cir` netlist for the project                           |
| `find_ngspice()`, `find_esim()`                     | Resolve external tool paths cross-platform                           |
| `detect_non_simulatable_components(components)`     | Pattern-matches board components against known non-simulatable parts |
| `detect_non_simulatable_in_cir(cir_path)`           | Same, but reading from a `.cir` file directly                        |
| `get_simulatability_status(cir_path, components)`   | Single source of truth for "can this be simulated?"                  |
| `should_show_popup_warning(cir_path, components)`   | Per-circuit "first time?" check (uses fingerprint marker file)       |
| `mark_warning_shown(cir_path, components)`          | Records that the popup has been shown for this circuit               |
| `preflight_check(cir_path)`                         | Validates `.cir` content before running ngspice                      |
| `sync_cir_values(cir_path, components)`             | Pushes KiCad component values into the `.cir` before simulation      |
| `prepare_cir_for_ngspice(cir_path)`                 | Wraps the `.cir` with a `.control` block and an output write         |
| `run_simulation(cir_path, components)`              | Top-level entry: orchestrates everything above                       |
| `parse_raw_file(raw_path)`                          | Parses ngspice ASCII `.raw` output                                   |
| `generate_plot_html(raw_path)`                      | Produces the interactive waveform plot                               |
| `_translate_ngspice_errors(stdout, stderr, ...)`    | Maps cryptic ngspice errors to plain-English explanations            |

The non-simulatable patterns are class-level constants (`NON_SIMULATABLE_PATTERNS`, `NON_SIMULATABLE_KEYWORDS_IN_VALUE`). Adding new patterns requires no other code changes.

### `board_listener.py`

A thin wxPython event listener that hooks the board-save event. Its only job is to fire a callback into `plugin.py` when the user saves. It is held alive by a module-level reference in `plugin.py` (variable `_listener`) so the Python garbage collector does not destroy it while KiCad is running.

---

## Sequence Walks

These are step-by-step traces of what happens when the user performs each major action. Use them as a map when reading the source.

### Walk 1: Saving the Project

1. User presses Ctrl+S in the PCB editor.
2. KiCad fires a board-save event.
3. `board_listener.py` catches the event and calls back into `plugin.py`.
4. `plugin.py` calls `take_snapshot(project, board)`:
   - Iterates `board.GetFootprints()` and builds a components dict.
   - Reads the `.kicad_sch` file and parses it via S-expressions.
   - Loads the most recent prior snapshot from `.design_diary_<project>/`.
   - Calls `diff_snapshots(prev, current)` to produce change strings.
   - Writes the new snapshot as `YYYYMMDD_HHMMSS.json`.
5. `ui_panel.py` refreshes its timeline list to show the new entry.

### Walk 2: Running a Simulation on a Simulatable Circuit (e.g. 555 timer)

1. User clicks *Run Simulation*.
2. `ui_panel.on_run_simulation` runs.
3. `engine.find_ngspice()` resolves the ngspice binary path.
4. `engine.find_cir_file()` locates the `.cir` (returns a path).
5. `Core.snapshot_components(self.board)` builds the components dict.
6. `engine.get_simulatability_status(cir_path, components)` returns `simulatable: True`.
7. `engine.run_simulation(cir_path, components)` runs:
   - `sync_cir_values` writes current KiCad values into the `.cir`.
   - `prepare_cir_for_ngspice` wraps the netlist with a `.control` block.
   - `subprocess.run` invokes ngspice in batch mode.
   - The `.raw` output is copied into `.design_diary_<project>/`.
   - A `RUN_*.json` record is written.
8. `engine.parse_raw_file` reads the `.raw` into a Python dict.
9. `engine.generate_plot_html` produces an interactive waveform plot.
10. `ui_panel` offers to open the plot in the browser.

### Walk 3: Running a Simulation on a Non-Simulatable Circuit (e.g. PIC programmer)

1. User clicks *Run Simulation*.
2. `ui_panel.on_run_simulation` runs.
3. `engine.find_ngspice()` resolves ngspice.
4. `Core.snapshot_components` builds the components dict.
5. `engine.find_cir_file()` returns `None` (eSim never generated a `.cir` for this board).
6. `engine.get_simulatability_status(None, components)` runs `detect_non_simulatable_components`, finds entries like `U6/PIC_8_PINS`, `U2/74HC125`, `U1/24Cxx`, returns `simulatable: False` with a populated `findings` list and `message`.
7. `ui_panel` checks `engine.should_show_popup_warning(None, components)`:
   - First time on this circuit: shows the long popup explaining PIC, EEPROM, digital logic limitations.
   - Subsequent times: shows the short condensed popup.
8. `engine.mark_warning_shown(None, components)` records the warning state.
9. The function returns. ngspice is never invoked, no `.cir` is required, no error is raised.

### Walk 4: Viewing Component History for R1

1. User clicks *Component History*, picks `R1`.
2. `ui_panel` opens `ComponentHistoryFrame`.
3. `ComponentHistoryFrame.load_history` lists `.design_diary_<project>/` and filters out `SCH_*`, `SIM_*`, `RUN_*`, and `_*` files, keeping only canonical snapshots.
4. For each canonical snapshot, the frame reads `data["changes"]` and emits a row whenever `R1` appears as a whole word.
5. The dialog renders a table of `(timestamp, change description)` pairs.

### Walk 5: Rollback

1. User selects a snapshot in the timeline and clicks *Rollback*.
2. `ui_panel.on_rollback` reads the selected snapshot.
3. The current live state is captured as a fresh snapshot first (so rollback is itself reversible).
4. The historical board state is reconstructed and written back into the live `.kicad_pcb` file.
5. KiCad reloads the board from disk.
6. Timeline refreshes; user sees both the rollback target and a new auto-snapshot of the rolled-back state.

---

## Extending the Plugin

### Adding a new non-simulatable component pattern

Open `simulation_engine.py`. At the top of the `SimulationEngine` class, add an entry to `NON_SIMULATABLE_PATTERNS`:

```python
(r'\bMSP432[A-Z0-9_\-]*\b', 'MSP432 microcontroller'),
```

The first element is a regex matched against the uppercase concatenation of `ref + value + footprint`. The second element is the human-readable label used in the popup. No other code changes are required.

For value-keyword matches that should be case-insensitive (such as substrings appearing inside footprint names), use `NON_SIMULATABLE_KEYWORDS_IN_VALUE` instead.

### Adding a new ngspice error translation

Open `simulation_engine.py` and find `_translate_ngspice_errors`. Add a new branch:

```python
if 'gmin stepping failed' in combined:
    return (
        "ngspice could not converge even with gmin stepping. "
        "This usually means the circuit has a very high-impedance node ..."
    )
```

The function returns a string which the UI displays directly. Return `None` if the error pattern does not match, so the caller falls through to the generic failure message.

### Adding a new toolbar button

In `ui_panel.py`, find the `DiaryPanel.__init__` method and the section where buttons are created. Add the new button:

```python
self.btn_my_action = wx.Button(self, label='My Action')
self.btn_my_action.Bind(wx.EVT_BUTTON, self.on_my_action)
button_sizer.Add(self.btn_my_action, 0, wx.ALL, 4)
```

Then implement the handler:

```python
def on_my_action(self, event):
    ...
```

### Adding a new field to the snapshot

Open `plugin.py`, find `take_snapshot` (or the equivalent capture function). Add the new field to the dict before `json.dump`. The diff engine in `diff_snapshots` will need a corresponding rule to detect changes in the new field; see how `value` and `footprint` are already handled as templates.

Older snapshots without the new field must remain readable. Always read with `data.get('field', default)` rather than `data['field']`.

### Changing the report template

The HTML report generation lives in `plugin.py` (export logic) and `simulation_engine.py` (waveform plot). Both use inline CSS to keep the output as a single self-contained file. The shared color palette is:

```
--bg:     #f5f2ed   (warm off-white background)
--card:   #faf8f5   (slightly lighter card surface)
--border: #e0dbd3   (low-contrast borders)
--text:   #2d3436   (charcoal body text)
--muted:  #9ba3a9   (muted metadata)
--accent: #c4713b   (terracotta accent)
```

Fonts are DM Serif Display (display), IBM Plex Sans (body), and JetBrains Mono (data).

---

## Known Limitations

- **No `.cir` regeneration.** The plugin reads existing `.cir` files but does not generate them. Generation must be done in eSim's KiCad-to-Ngspice converter.
- **Component-history rebuilds from full snapshot scan.** For projects with thousands of snapshots, this becomes O(n) per query. Acceptable in practice but worth caching if it ever becomes a bottleneck.
- **Schematic diff is structural, not semantic.** A wire reroute that does not change net membership will not be flagged. Connectivity changes are detected via net comparison; pure visual edits are not.
- **Snapshot capture is synchronous.** A save on a very large board (>1000 components) introduces a perceptible pause. Moving snapshot writes to a background thread is a known follow-up.
- **`.cir` value sync is one-way.** KiCad to ngspice. Editing the `.cir` directly and expecting KiCad values to follow does not work and is not intended to.
- **Tag persistence assumes the diary folder is not deleted.** Tags are stored in the snapshot files themselves; if the diary folder is wiped, tag history is lost.
- **No multi-user or concurrent-edit safety.** The plugin assumes one KiCad instance per project at a time.

---

## Development Environment

- **OS**: Windows 11 with WSL2 for Linux-side tooling.
- **KiCad**: 9.0 (Python scripting API).
- **Python**: 3.9+ as supplied by KiCad's bundled interpreter.
- **eSim**: 2.4 (installed at `C:\FOSSEE\eSim\`).
- **ngspice**: 36 (installed at `C:\FOSSEE\nghdl-simulator\bin\ngspice.exe`).
- **Editor**: VS Code with the Python extension. The repository is opened directly from the KiCad plugins folder so that edits take effect after a plugin reload.

### Plugin Reload Without Restarting KiCad

Run in the KiCad PCB editor's scripting console:

```python
import sys
for m in [k for k in list(sys.modules) if 'kicad_design_diary' in k]:
    del sys.modules[m]
from kicad_design_diary.plugin import DesignDiaryPlugin
DesignDiaryPlugin().Run()
```

This forces a full re-import of all plugin modules, picking up edits immediately.

### Static Analysis

```
python3 -m pyflakes /path/to/kicad_design_diary/
```

Run before every commit. The codebase should remain free of pyflakes warnings or have each remaining warning explained inline.

---

## Debugging Guide

**The plugin window does not open.** Check the KiCad scripting console (View → Scripting Console) for a traceback. The most common cause is a `SyntaxError` or `IndentationError` in a recently-edited file. Run `python3 -m pyflakes` against the plugin folder to find it.

**Snapshots are not being created on save.** Verify `board_listener.py` is loaded by checking that `_listener` in `plugin.py` is not `None` after the plugin has run once. If the listener is `None`, the save event is not being hooked. Restart KiCad.

**Component History shows duplicate entries.** The `load_history` filter in `ui_panel.py` must exclude `SCH_*`, `SIM_*`, `RUN_*`, and `_*` files. If duplicates appear, that filter is the place to look.

**Run Simulation shows no popup on a non-simulatable board.** The flow is:

1. Verify components are being captured: `len(components)` should be greater than 0.
2. Verify detection fires: `engine.detect_non_simulatable_components(components)` should return a non-empty list.
3. Verify the UI is calling `get_simulatability_status` *before* the "no .cir found" check. Refer to the simulation decision tree above.

**ngspice runs but produces no `.raw`.** Check the log file in the diary folder for the actual ngspice stdout/stderr. The most common causes are missing `.lib` or `.include` directives, malformed netlists, or convergence failures. The `_translate_ngspice_errors` function should catch these and present a friendly message; if it does not, add a new branch.

**Path with spaces or non-ASCII characters causes file errors.** All file I/O in the plugin uses `os.path.join` and `open(..., encoding='utf-8', errors='replace')`. If you find a place that does not, fix it. Cloud-synced folders (OneDrive, Dropbox) are supported but may introduce file-locking races; if a snapshot fails to write, retry once before erroring.



