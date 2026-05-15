# Known Limitations - eSim Simulation Bridge

**Version:** eSim Simulation Bridge v1.0.0 (esim_bridge.py + esim_spice_linker.py + ngspiceSimulation package)  
**Platform:** KiCad 8.0 + eSim 2.5 + ngspice 42 (Ubuntu package `42+ds-3build1`)  
**Document Date:** May 2026

This document comprehensively lists all known limitations, with the technical reasoning behind each and any available workarounds.

---

## 1. Component Simulation Limitations

### 1.1 Microcontrollers (MCUs) - MISSING Status is Expected and Correct

**Affected components:** ATtiny85, ATmega328P (Arduino), PIC16F, STM32, ESP32, and all MCUs.

**Why it cannot be simulated:** Microcontrollers execute firmware instructions - they are digital state machines driven by clock cycles. ngspice is an analog circuit simulator operating on continuous-time differential equations (Modified Nodal Analysis). The fundamental computational models are incompatible. No SPICE model for any MCU exists anywhere in the industry - not in eSim, not in any manufacturer datasheet library, not in any commercial SPICE product.

**Plugin behaviour:** The SPICE Model Auto-Linker correctly reports these as MISSING. The SPICE converter comments them out in the generated `.cir` file with a warning. When an MCU is the central hub of a schematic, the entire schematic cannot be simulated.

**Workaround:** Use Logisim Evolution or a dedicated IDE simulator (MPLAB Sim, SimulIDE) for MCU-level simulation. For analog sub-circuits connected to an MCU, extract and simulate the analog portion separately with voltage sources replacing the MCU output pins.

---

### 1.2 Digital ICs (74xx / CMOS 40xx Series) - Partial Support Only

**Affected components:** 7400, 7402, 7404, 7408, 7432, 74HC86, CD4011, CD4093, and all TTL/CMOS digital logic ICs.

**Why analog simulation is problematic:** 74xx ICs are designed for binary operation. ngspice is an analog simulator - it can technically use transistor-level SPICE subcircuits of these gates, but: (a) eSim's `SN74LS00` subcircuit depends on multiple companion `.lib` files with paths hardcoded relative to eSim's internal `SubcircuitLibrary/` directory, which fail when injected into a standalone `.cir` file; (b) simulating digital circuits in analog mode is extremely slow and prone to convergence failures.

**Plugin behaviour:** The Auto-Linker attempts to find a matching subcircuit using the 74xx special handler (tries `sn74ls00`, `sn74hc00`, `sn74`, `cd40` prefix variants). If found, it injects it but the simulation may fail due to missing dependency files. ICs with no eSim equivalent are correctly reported as MISSING.

**Workaround:** Use Logisim Evolution or Icarus Verilog for digital logic verification.

---

### 1.3 Condenser Microphones - No SPICE Model Exists

**Affected components:** Any component with `MK` prefix.

**Why no model exists:** A condenser microphone is an acoustic transducer. SPICE models circuit elements, not acoustic phenomena. There is no standard SPICE model for any microphone type.

**Plugin behaviour:** The plugin approximates a microphone as an AC voltage source: `VMK1 <non-gnd-node> 0 AC 0.01 SIN(0 0.01 1k)` - a 10 mV peak signal at 1 kHz, representing typical speech-frequency input. The positive terminal is always the non-GND node.

---

### 1.4 Light-Dependent Resistors (LDRs) - Fixed Value Only

**Affected components:** Any R-prefix component whose value field contains spaces or non-SPICE strings (e.g., "5mm LDR").

**Why it is limited:** ngspice requires a fixed numeric resistance value. Dynamic resistance behaviour requires a behavioural (B-element) model not yet implemented.

**Plugin behaviour:** The SPICE converter sanitises R-prefix values with regex - everything after the first space is stripped. If the remaining value is not a valid SPICE resistance expression, it falls back to `1k` (bright-light assumption).

**Workaround:** Set the LDR value to a fixed numeric resistance (e.g., `10k`) before simulating.

---

### 1.5 Transformers - Manual Subcircuit Required

**Affected components:** T-prefix components.

**Why it is limited:** Transformers require a two-coupled-inductor model (`K` element) with both winding inductances and coupling coefficient - values not available from a standard KiCad value field.

**Plugin behaviour:** A commented placeholder is generated and the component is reported as unsupported.

**Workaround:** Manually add a transformer subcircuit to `~/.esim-bridge/models/`:

```spice
.subckt XFMR in1 in2 out1 out2
L1 in1 in2 1m
L2 out1 out2 1m
K1 L1 L2 0.99
.ends XFMR
```

---

### 1.6 eSim Co-Simulation Components - Not Supported

**Affected components:** `eSim_Ngveri`, `eSim_Hybrid` library blocks such as `adc_bridge`, `dac_bridge`, and behavioral Verilog models generated through eSim's NgVeri flow.

**Why it cannot be simulated:** These components require eSim's internal co-simulation engine (ngspice + Verilator) and have no standalone SPICE subcircuit representation. Attempting to simulate such circuits will result in a *missing subcircuit model* error from ngspice.

**This is a fundamental architectural constraint of ngspice itself**, not a limitation of the plugin design. eSim handles mixed-signal circuits through a separate co-simulation engine (NGHDL/Verilator) that operates outside the ngspice batch mode used by eSim Simulation Bridge.

---

## 2. ngspice Analysis Limitations

### 2.1 Pole-Zero Analysis - Removed Due to ngspice 42 Bug

**Description:** Pole-zero analysis (`.pz` command) is not available in eSim Simulation Bridge.

**Root cause:** ngspice 42 (Ubuntu package `42+ds-3build1`) has a confirmed bug in `src/spicelib/analysis/pzan.c`. The KLU solver guard (`#ifdef KLU`) returns `E_UNSUPP` for all pole-zero analysis. Even forcing the SPARSE 1.3 solver yields `PZnPoles=0` for simple RC circuits. This is a regression in ngspice 42 - not present in earlier versions.

**Plugin decision:** Pole-zero analysis was removed entirely from the plugin rather than shipping a half-working implementation that returns zero vectors. This is documented as a known ngspice 42 Ubuntu package limitation.

**Workaround:** None available without upgrading or patching ngspice.

---

### 2.2 Operating Point Analysis - No Waveform Graph

**Why it is limited:** eSim 2.5's plotter cannot display `.op` results graphically. The `.op` analysis produces a single set of DC node voltages, not a time-varying dataset.

**Plugin behaviour:** The plugin runs `.op` internally using ngspice and displays the DC node voltages in a MessageBox popup. eSim is not launched for `.op` analysis.

---

### 2.3 Transfer Function Analysis - No Waveform Graph

**Why it is limited:** `.tf` produces a scalar result (gain + impedances), not a waveform dataset.

**Plugin behaviour:** Results are displayed in a labelled popup showing gain, input impedance, and output impedance with plain-language interpretation. eSim is not launched.

---

### 2.4 Sensitivity Analysis - Requires DC Operating Point

**Why it is limited:** `.sens` computes DC sensitivity - it requires a non-zero DC operating point to linearise around. If the source has `dc=0` (typical for sine sources), all sensitivities will be zero.

**Plugin behaviour:** A note is displayed in the results popup. Additionally, DC voltage sources whose KiCad Value field retains the library symbol name (e.g., `VSIN`) instead of the sim type are handled specially - the DC handler reads the `dc=` field from `Sim.Params` directly.

**Workaround:** In the Source Details tab, set the `dc` offset of the voltage source to a non-zero value (e.g., `dc=1`) before running Sensitivity Analysis.

---

### 2.5 FFT - Limited Frequency Resolution

**Description:** The FFT frequency resolution depends on the number of time-domain data points. With default Transient settings (Step=0.1ms, Stop=10ms), you get approximately 100 data points, which limits FFT resolution.

**Workaround:** Increase Stop time or decrease Step time to get more data points, improving FFT resolution. For the Three-Phase Rectifier, Step=0.1ms, Stop=100ms gives 1000 data points and clear FFT peaks.

---

### 2.6 Bode Plot - Phase Shows Zero for Purely Resistive Circuits

**Description:** Resistive voltage dividers show 0° phase at all frequencies in the Bode plot.

**This is correct physics.** Pure resistors introduce no phase shift. The Bode plot becomes meaningful when capacitors or inductors are present (e.g., RC filter, LC amplifier).

---

### 2.7 Parametric Sweep - Leftover Component Values After AC Analysis

**Description:** Running AC analysis immediately after a parametric sweep may leave intermediate component values (e.g., `R1=23.19k`) in the SPICE file from the sweep steps.

**Workaround:** Reset the component values manually in the schematic and re-run the plugin before switching to AC analysis.

---

### 2.8 Parametric Sweep - R/C/L Components Only

**Description:** The parametric sweep can only vary R, C, or L components found in the `.cir.out` file. Voltage sources, current sources, and other components cannot be swept.

---

## 3. eSim / Interface Limitations

### 3.1 UTF-8 Popup After Simulation (Cosmetic Bug in eSim 2.5)

**Description:** After clicking Simulate in eSim, a UTF-8 error dialog may appear.

**Root cause:** eSim 2.5's internal plotter reads a stale binary `.raw` file from a previous ngspice run. If that file exists from a different simulation format, the plotter raises a UTF-8 decode error.

**Plugin behaviour:** The plugin attempts to delete stale `.raw` files before launching eSim. However, the file may be re-created during the eSim session before the plotter reads it.

**Resolution:** Dismiss the popup and click **Simulate** again. The simulation completes correctly - this is purely cosmetic and cannot be fixed from within the plugin (the error occurs inside eSim's plotter code running in a separate process).

---

### 3.2 Manual Project Selection in eSim

**Description:** After eSim launches, the user must manually double-click `esim_bridge_project` in the left panel before clicking Simulate.

**Root cause:** eSim 2.5 does not support command-line arguments to pre-select a project. `Application.py` does not accept a project path argument.

---

### 3.3 Single Project Folder

**Description:** All schematics share one eSim project folder (`esim_bridge_project`). Simulating a different schematic overwrites the previous simulation results.

**Workaround:** Copy the `.cir.out` and `plot_data_v.txt` files to a separate folder before simulating a new schematic if you need to retain previous results.

---

### 3.4 Python Plot Window - Text Output Format Only

**Description:** The `ngspiceSimulation` Python plot window reads ngspice's text output format (`plot_data_v.txt`, `plot_data_i.txt`) - not the binary `.raw` file. Both files are generated automatically by eSim Simulation Bridge.

**Plugin behaviour:** The plot window is launched dynamically via `importlib` when the user clicks **Open Python Plot** in the `SimulationReadyDialog`. If the text output files do not exist (e.g., ngspice failed), the plot window will open but show no data.

---

## 4. Installation Limitations

### 4.1 Linux Only

**Description:** The plugin uses Linux-style paths and depends on eSim 2.5, which is Linux-only.

**Windows users:** Use VirtualBox with Ubuntu 24.04 LTS (fully tested, recommended).

---

### 4.2 eSim Must Be at `~/Downloads/eSim-2.5/`

**Description:** The plugin expects eSim 2.5 at `~/Downloads/eSim-2.5/`.

**Workaround if eSim is elsewhere:** Edit `esim_bridge.py` and update the `ESIM_SCRIPT`, `ESIM_PYTHON`, `ESIM_SRC`, and `ESIM_DIR` constants in the `ESimLauncher` class.

---

### 4.3 `__pycache__` Must Be Cleared After Code Changes

KiCad loads cached `.pyc` bytecode. After any code change:

```bash
rm -rf ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/__pycache__
```

Then restart KiCad.

---

## 5. Summary Table

| Limitation | Severity | Fix Available | Workaround |
|---|---|---|---|
| MCUs (ATtiny85, Arduino, etc.) | Fundamental - industry-wide | No | Use dedicated MCU simulators |
| 74xx digital ICs | Industry-wide constraint | No | Logisim Evolution / Icarus Verilog |
| eSim co-simulation components (NgVeri, Hybrid) | Architectural - ngspice limitation | No | Not simulatable via ngspice batch mode |
| Condenser microphone | No SPICE model exists | No | 10 mV AC source approximation (built-in) |
| LDR value with spaces | Parse issue | Resolved | Sanitised to `1k` fallback |
| Transformers | Needs manual subcircuit | Partial | Add `.subckt` to `~/.esim-bridge/models/` |
| Pole-zero analysis | ngspice 42 confirmed bug in `pzan.c` (KLU solver) | No | None - removed from plugin |
| `.op` analysis - no graph | eSim 2.5 plotter limitation | No | DC node voltages shown in popup |
| `.tf` analysis - no graph | Scalar result, no waveform | No | Gain/impedances shown in popup |
| Sensitivity all zeros | DC operating point required | User action | Set `dc=1` on voltage source |
| UTF-8 popup (cosmetic) | eSim 2.5 internal bug | No | Dismiss and re-simulate |
| Manual project selection in eSim | eSim 2.5 has no CLI project args | No | Double-click project in eSim GUI |
| Single project folder | Design decision | Partial | Manually back up results |
| Parametric sweep leftover values | Sweep modifies `.cir.out` in-place | User action | Reset component values before AC run |
| Parametric sweep - R/C/L only | Implementation scope | Partial | Voltage/current source sweep not supported |
| FFT limited resolution | Depends on data point count | User action | Increase simulation duration / decrease step |
| Python plot window - text format only | `ngspiceSimulation` reads text output | No | Binary `.raw` is read by embedded viewer |
| Linux only | eSim 2.5 platform constraint | No | Use VirtualBox Ubuntu |
| eSim path hardcoded | Installation assumption | Partial | Edit `ESimLauncher` constants in `esim_bridge.py` |

---

*Maintained by: Imran Farhat - FOSSEE Semester Long Internship Spring 2026, IIT Bombay*  
*Last updated: May 2026*
