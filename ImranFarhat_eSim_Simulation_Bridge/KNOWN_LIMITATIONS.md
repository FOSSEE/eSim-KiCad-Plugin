# Known Limitations — eSim-BRIDGE + eSim-SPICE

**Version:** eSim-BRIDGE v2.1.0 / eSim-SPICE v1.0.0
**Platform:** KiCad 8.0/9.x + eSim 2.5 + ngspice 35
**Document Date:** May 2026

This document comprehensively lists all known limitations of the plugin suite, with the technical reasoning behind each and any available workarounds.

---

## 1. Component Simulation Limitations

### 1.1 Microcontrollers (MCUs) — MISSING Status is Expected and Correct

**Affected components:** ATtiny85, ATmega328P (Arduino), PIC16F, STM32, ESP32, and all MCUs.

**Why it cannot be simulated:** Microcontrollers execute firmware instructions — they are digital state machines driven by clock cycles. ngspice is an analog circuit simulator operating on continuous-time differential equations (Modified Nodal Analysis). The fundamental computational models are incompatible. No SPICE model for any MCU exists anywhere in the industry — not in eSim, not in any manufacturer datasheet library, not in any commercial SPICE product.

**Plugin behavior:** eSim-SPICE correctly reports these as MISSING. eSim-BRIDGE comments them out in the generated SPICE file with a warning. When an MCU is the central hub of a schematic (all other components connect through it), the entire schematic cannot be simulated.

**Workaround:** Use Logisim Evolution or a dedicated IDE simulator (MPLAB Sim, SimulIDE) for MCU-level simulation. For analog sub-circuits connected to an MCU, extract and simulate the analog portion separately with voltage sources replacing the MCU's output pins.

---

### 1.2 Digital ICs (74xx / CMOS 40xx Series) — Partial Support Only

**Affected components:** 7400, 7402, 7404, 7408, 7432, 74HC86, CD4011, CD4093, and all TTL/CMOS digital logic ICs.

**Why analog simulation is problematic:** 74xx ICs are designed for binary operation. ngspice is an analog simulator — it can technically simulate transistor-level SPICE models of these gates, but:
- eSim's SN74LS00 subcircuit depends on multiple companion `.lib` files (NPN.lib, PNP.lib, etc.) in the same folder. These paths are hardcoded relative to eSim's internal `SubcircuitLibrary/` directory and fail when injected into a standalone `.cir` file.
- Simulating digital circuits in analog mode is extremely slow and prone to convergence failures.
- Industry-standard practice is to use dedicated digital simulators for logic-level work.

**Plugin behavior:** eSim-SPICE attempts to find a matching subcircuit. If found (e.g., SN74LS00 for a 7400), it injects it but the simulation may fail due to missing dependency files. ICs with no eSim equivalent are correctly reported as MISSING.

**Workaround:** Use Logisim Evolution or Icarus Verilog for digital logic verification.

---

### 1.3 Condenser Microphones — No SPICE Model Exists

**Affected components:** Any component with `MK` prefix (Microphone_Condenser, etc.).

**Why no model exists:** A condenser microphone is an acoustic transducer — it converts sound pressure waves into electrical signals. SPICE models circuit elements, not acoustic phenomena. There is no standard SPICE model for any microphone type.

**Plugin behavior:** eSim-BRIDGE approximates a microphone as an AC voltage source: `VMK1 node 0 AC 0.01 SIN(0 0.01 1k)` — a 10mV peak signal at 1kHz, representing typical speech-frequency input. The positive terminal is the non-GND node, negative is GND.

---

### 1.4 Light-Dependent Resistors (LDRs) — Fixed Value Only

**Affected components:** Any R-prefix component whose value field contains spaces or non-SPICE strings (e.g., "5mm LDR").

**Why it is limited:** ngspice requires a fixed numeric resistance value. Dynamic resistance behavior requires a behavioral (B-element) model not yet implemented.

**Plugin behavior:** eSim-BRIDGE sanitizes R-prefix values with regex — everything after the first space is stripped. If the remaining value is not a valid SPICE resistance expression, it falls back to `1k` (bright-light assumption).

**Workaround:** Set the LDR value to a fixed numeric resistance (e.g., `10k`) before simulating.

---

### 1.5 Transformers — Manual Subcircuit Required

**Affected components:** T-prefix components.

**Why it is limited:** Transformers require a two-coupled-inductor model (`K` element) with both winding inductances and coupling coefficient — values not available from a standard KiCad value field.

**Plugin behavior:** eSim-BRIDGE generates a commented placeholder and reports as unsupported.

**Workaround:** Manually add a transformer subcircuit to `~/.esim-bridge/models/`:
```spice
.subckt XFMR in1 in2 out1 out2
L1 in1 in2 1m
L2 out1 out2 1m
K1 L1 L2 0.99
.ends XFMR
```

---

### 1.6 Operating Point Analysis — No Waveform Graph

**Why it is limited:** eSim 2.5's plotter cannot display `.op` results graphically. The `.op` analysis produces a single set of DC node voltages, not a time-varying dataset.

**Plugin behavior:** eSim-BRIDGE runs `.op` internally using ngspice and displays the DC node voltages in a MessageBox popup. eSim is not launched for `.op` analysis.

---

### 1.7 Transfer Function Analysis — No Waveform Graph

**Why it is limited:** `.tf` produces a scalar result (gain + impedances), not a waveform dataset.

**Plugin behavior:** Results are displayed in a labeled popup showing gain, input impedance, and output impedance. eSim is not launched.

---

### 1.8 Sensitivity Analysis — Requires DC Operating Point

**Why it is limited:** `.sens` computes DC sensitivity — it requires a non-zero DC operating point to linearize around. If the source has `dc=0` (typical for sine sources), all sensitivities will be zero.

**Plugin behavior:** A note is displayed in the results popup: "Sensitivity requires a DC operating point. If all values are zero, add a DC value to your source (e.g. change V1 dc=0 to dc=1)."

**Workaround:** In the Source Details tab, set the `dc` offset of the voltage source to a non-zero value (e.g., `dc=1`) before running Sensitivity Analysis.

---

## 2. eSim / ngspice Compatibility Issues

### 2.1 UTF-8 Popup After Simulation (Cosmetic Bug in eSim 2.5)

**Description:** After clicking "Simulate" in eSim, a UTF-8 error dialog may appear.

**Root cause:** eSim 2.5's internal plotter attempts to read the `.raw` binary output file from a previous ngspice run. If that file exists from a different simulation format, the plotter raises a UTF-8 decode error.

**Plugin behavior:** eSim-BRIDGE attempts to delete stale `.raw` files before launching eSim. However, the file may be re-created during the eSim session before the plotter reads it.

**Resolution:** Dismiss the popup and click **Simulate** again. The simulation completes successfully — this is purely cosmetic.

**Cannot be fixed from within the plugin:** The error occurs inside eSim's plotter code, which runs in a separate process after eSim-BRIDGE has already exited.

---

### 2.2 Manual Project Selection in eSim

**Description:** After eSim launches, the user must manually double-click `esim_bridge_project` in the left panel before clicking Simulate.

**Root cause:** eSim 2.5 does not support command-line arguments to pre-select a project. The `Application.py` entry point does not accept a project path argument.

---

### 2.3 Single Project Folder

**Description:** All schematics share one eSim project folder (`esim_bridge_project`). Simulating a different schematic overwrites the previous simulation results.

**Workaround:** Copy the `.cir.out` and `plot_data_v.txt` files to a separate folder before simulating a new schematic if you need to retain previous results.

---

## 3. Analysis-Specific Limitations

### 3.1 Sensitivity Analysis — Resistor Values Near Zero

**Description:** ngspice's `.sens` returns sensitivity with respect to conductance (1/R), not resistance. For purely resistive circuits, R1/R2/R3 values may show near-zero sensitivity while `v1` (the source sensitivity) shows the correct voltage divider gain.

**This is correct ngspice behavior**, not a plugin bug. The `v1` sensitivity value equals the circuit's transfer function gain.

---

### 3.2 FFT — Limited Frequency Resolution

**Description:** The FFT frequency resolution depends on the number of time-domain data points. With default Transient settings (Step=0.1ms, Stop=10ms), you get approximately 100 data points, which limits FFT resolution.

**Workaround:** Increase Stop time or decrease Step time to get more data points, improving FFT resolution.

---

### 3.3 Bode Plot — Phase Shows Zero for Resistive Circuits

**Description:** Resistive voltage dividers show 0° phase at all frequencies in the Bode plot. This is correct physics — pure resistors introduce no phase shift.

**This is correct behavior.** The Bode plot becomes meaningful when capacitors or inductors are added to the circuit.

---

### 3.4 Parametric Sweep — Only R/C/L Components

**Description:** The parametric sweep can only vary R, C, or L components found in the `.cir.out` file. Voltage sources, current sources, and other components cannot be swept.

---

## 4. Plugin Installation Limitations

### 4.1 Username Hardcoded in Path Strings

**Description:** The plugin uses `~/Downloads/eSim-2.5/` paths that were developed on a system with the username `imran-farhat`.

**Resolution:** The mandatory `sed` command in Step 4 of installation replaces the developer's username with the current user's username. This is a one-time setup step.

**Future fix (planned):** Replace all hardcoded paths with `os.path.expanduser('~')` for true portability.

---

### 4.2 Linux Only

**Description:** The plugin uses Linux-style paths and depends on eSim 2.5, which is Linux-only.

**Windows users:** Use VirtualBox with Ubuntu 24.04 LTS (fully tested, recommended).

---

### 4.3 eSim Must Be at `~/Downloads/eSim-2.5/`

**Description:** The plugin expects eSim 2.5 at `~/Downloads/eSim-2.5/`.

**Workaround if eSim is elsewhere:** Edit `esim_bridge.py` and update the `ESIM_SCRIPT`, `ESIM_PYTHON`, `ESIM_SRC`, and `ESIM_DIR` constants in the `ESimLauncher` class.

---

### 4.4 `__pycache__` Must Be Cleared After Code Changes

```bash
rm -rf ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/__pycache__
```

---

## 5. Summary Table

| Limitation | Severity | Fix Available | Workaround |
|---|---|---|---|
| MCUs (ATtiny85, etc.) | Fundamental — industry-wide | No | Dedicated MCU simulators |
| 74xx digital ICs | Industry-wide constraint | No | Logisim Evolution / Icarus Verilog |
| Condenser microphone | No SPICE model exists | No | 10mV AC source approximation |
| LDR value with spaces | Parse issue | Resolved | Sanitized to 1k fallback |
| Transformers | Needs manual subcircuit | Partial | Add to `~/.esim-bridge/models/` |
| .op analysis — no graph | eSim 2.5 plotter limit | No | Voltages shown in popup |
| .tf analysis — no graph | Scalar result, no waveform | No | Gain/impedance shown in popup |
| Sensitivity zeros | DC operating point needed | User action | Set dc=1 on source |
| UTF-8 popup (cosmetic) | eSim 2.5 internal bug | No | Dismiss and re-simulate |
| Manual project selection | eSim 2.5 GUI limit | No | Double-click project in eSim |
| Single project folder | Design decision | Partial | Manually back up results |
| Username hardcoded | Installation requirement | Partial | `sed` command in Step 4 |
| Linux only | eSim 2.5 platform constraint | No | Use VirtualBox Ubuntu |
| eSim path hardcoded | Installation requirement | Partial | Edit `ESimLauncher` constants |
| FFT limited resolution | Data point count | User action | Increase simulation duration |
| Parametric sweep — R/C/L only | Implementation scope | Partial | Voltage source sweep not supported |

---

*Document maintained by: Imran Farhat (FOSSEE Intern, IIT Bombay)*
*Last updated: May 2026*
