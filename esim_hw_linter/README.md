<div align="center">
  <img src="https://img.icons8.com/color/128/000000/security-checked--v1.png" alt="Security Linter Icon" width="128">

  <h1>eSim Hardware Security Linter V2.0</h1>
  <p><strong>Enterprise-Grade Physical Hardware Security & Automated CI/CD for KiCad</strong></p>

  <p>
    <a href="#"><img src="https://img.shields.io/badge/KiCad-8.0%20%7C%209.0-blue?style=for-the-badge&logo=kicad" alt="KiCad Version"></a>
    <a href="#"><img src="https://img.shields.io/badge/Python-3.x-yellow?style=for-the-badge&logo=python" alt="Python Version"></a>
    <a href="#"><img src="https://img.shields.io/badge/FOSSEE-eSim-orange?style=for-the-badge" alt="eSim"></a>
    <a href="#"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License"></a>
  </p>
</div>

<br>

## 🚨 The Hardware Threat Model
In modern electronics design, developers frequently place debugging interfaces (like **UART**, **JTAG**, **SWD**, and **SPI Flash**) directly near the physical edges of a PCB for easy testing. If these ports make it into final production devices, they create a massive "God Mode" vulnerability. 

An attacker can simply drill a tiny hole or pry open the plastic enclosure, connect a 4-pin cable to the exposed boundary port, and completely bypass software encryption, steal plaintext system logs, or extract firmware binaries.

**The eSim Hardware Security Linter** actively hunts down these vulnerabilities during the layout phase, shifting physical security testing all the way left into the DevSecOps pipeline.

---

## 🔥 Enterprise Features (New in V2.0)

### 🚀 1-Click CI/CD Deployment Engine
Integrated directly into the native GUI is an automated deployment engine. By checking a single box, the plugin automatically force-saves your local board, dynamically generates a brand new GitHub Actions `.yml` file targeted to your exact project, and pushes the code to your GitHub repository in the background.

### 🛡️ Pre-Push Hardware Firewall
The plugin runs the security audit *before* talking to the internet. If it detects a critical hardware vulnerability, it physically aborts the deployment process, preventing junior engineers from accidentally merging compromised PCB layouts into production repositories.

### 🌐 Cloud-to-Local UX Bridge
After a successful, secure deployment to GitHub, the plugin uses a non-blocking background timer to seamlessly pop open your local web browser exactly to the live GitHub Actions page, letting you watch the cloud server audit your board.

### 🔌 Trace-Level EMFI Glitch Detection
The audit engine goes far beyond generic components. It scans the literal copper `Tracks` on the board. If a vulnerable net (e.g., `SWDIO`) is routed dangerously close to the `Edge.Cuts` boundary, it flags it as an Electromagnetic Fault Injection (EMFI) vulnerability.

### 📜 JSON Organizational Security Profiles
Organizations can place an `esim_security.json` file in their project root. The plugin automatically detects this and overrides the local GUI variables, enforcing team-wide security tolerances (e.g., locking the minimum distance threshold to 5.0mm).

### 🤖 Headless Cloud Mode
The plugin operates in a dual-mode architecture. In the cloud, it completely detaches from the `wxPython` GUI, binds to an `xvfb` virtual framebuffer, and evaluates the PCB using `sys.exit(1)` protocols to natively block GitHub Pull Requests if the board fails the security check.

---

## 🚀 Installation & Usage

### 1. Install the Plugin
Simply clone this repository and move the entire `esim_hw_linter` folder into your KiCad Scripting Plugins directory.

* **macOS:** `~/Documents/KiCad/9.0/scripting/plugins/`
* **Windows:** `%USERPROFILE%\Documents\KiCad\9.0\scripting\plugins\`
* **Linux:** `~/.local/share/kicad/9.0/scripting/plugins/`

### 2. Run the Security Audit
1. Open up your PCB Layout in KiCad (`pcbnew`).
2. Look for the colorful Security Shield icon in the top toolbar.
3. Click it to launch the internal scanner!

---

## ⚙️ How it Works in eSim

In the **FOSSEE eSim** EDA software ecosystem, users traditionally create their schematics and immediately bridge to KiCad for their physical PCB layout phase. By installing this Action Plugin, eSim gains an entirely automated, native hardware security auditing toolchain, bringing enterprise-grade DevSecOps defenses directly to students, researchers, and professional PCB engineers.

<br>

<div align="center">
  <i>Built to make hardware security accessible and fully automated.</i>
</div>
