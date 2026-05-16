# Installation Guide - eSim Simulation Bridge

Complete step-by-step installation instructions for all supported environments.

**Plugin:** eSim Simulation Bridge v1.0.0  
**Environment:** KiCad 8.0 + eSim 2.5 + ngspice 42  
**Platform:** Ubuntu Linux 24.04 LTS

---

## Environment Options

| Environment | Recommendation |
|---|---|
| Ubuntu 24.04 in VirtualBox (Windows host) | ✅ **Fully tested - recommended for Windows users** |
| Native Ubuntu 24.04 Linux | ✅ Works perfectly |
| WSL 2 with WSLg (Windows 11) | ⚠️ May work - follow Option C below |
| WSL 1 or without WSLg | ❌ No display support - cannot work |
| macOS | ❌ eSim 2.5 is Linux-only - not supported |

---

## Option A - VirtualBox Ubuntu (Recommended for Windows Users)

### Prerequisites
- Windows 10/11 host machine
- 8 GB RAM minimum (16 GB recommended)
- 60 GB free disk space

### A1 - Set Up VirtualBox

1. Download VirtualBox from https://virtualbox.org and install it
2. Download Ubuntu 24.04 LTS ISO from https://ubuntu.com/download/desktop
3. In VirtualBox, click **New** and create a VM with these settings:

| Setting | Value |
|---|---|
| Name | Ubuntu 24.04 eSim |
| Type | Linux - Ubuntu (64-bit) |
| RAM | 4096 MB minimum (8192 recommended) |
| CPU | 2 cores or more |
| Storage | 40 GB VDI, dynamically allocated |
| **Graphics Controller** | **VMSVGA** ← critical, not VBoxVGA |
| Video Memory | 256 MB |
| 3D Acceleration | Enabled |

4. Start the VM, point to the Ubuntu ISO, install Ubuntu normally
5. After installation, install VirtualBox Guest Additions:

```bash
sudo apt update && sudo apt install -y build-essential dkms linux-headers-$(uname -r)
# In VirtualBox menu: Devices → Insert Guest Additions CD Image
sudo /media/$USER/VBox_GAs_*/VBoxLinuxAdditions.run
sudo reboot
```

### A2 - Install KiCad 8.0

```bash
sudo apt update
sudo apt install -y kicad
kicad-cli --version
# Expected output: Application: kicad-cli 8.0.x
```

If you encounter a `libngspice-kicad` conflict:

```bash
sudo dpkg --remove --force-depends ngspice
sudo dpkg -i --force-overwrite /var/cache/apt/archives/libngspice-kicad_*.deb
sudo apt-get install -f -y
sudo apt install ngspice -y
sudo dpkg -i --force-overwrite /var/cache/apt/archives/ngspice_*.deb
sudo apt-get install -f -y
```

### A3 - Install eSim 2.5

```bash
cd ~/Downloads
wget https://static.fossee.in/esim/installation-files/eSim-2.5.zip
unzip eSim-2.5.zip
cd eSim-2.5
chmod +x install-eSim.sh
./install-eSim.sh --install
# Wait 5-10 minutes for installation to complete
```

Verify the installation:

```bash
ls ~/Downloads/eSim-2.5/src/frontEnd/Application.py
ls ~/.esim/env/bin/python3
# Both must print the file path - if not, reinstall eSim
```

Test eSim launches correctly (optional):

```bash
cd ~/Downloads/eSim-2.5/src/frontEnd
PYTHONPATH=/home/$(whoami)/Downloads/eSim-2.5/src \
    ~/.esim/env/bin/python3 Application.py
# eSim should open. Close it after confirming.
```

### A4 - Clone and Install the Plugin

```bash
cd ~
git clone https://github.com/FOSSEE/eSim-KiCad-Plugin.git

mkdir -p ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge
cp -r ~/eSim-KiCad-Plugin/ImranFarhat_eSim_Simulation_Bridge/eSim_Simulation_Bridge/* \
    ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/

# Verify all files are present
ls -la ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/
```

Expected files:
```
__init__.py
esim_bridge.py
esim_spice_linker.py
icon.png
configuration/
    __init__.py
    Appconfig.py
ngspiceSimulation/
    __init__.py
    plot_window.py
    data_extraction.py
    plotting_widgets.py
```

### A5 - Create eSim Workspace

```bash
mkdir -p ~/eSim-Workspace
echo '{"/home/'$(whoami)'/eSim-Workspace/esim_bridge_project": []}' \
    > ~/eSim-Workspace/.projectExplorer.txt
```

### A6 - Launch KiCad and Verify Plugin

1. Open KiCad from the Applications menu
2. Open or create a project (File → New → Project)
3. Open **PCB Editor** (click the PCB icon)
4. Look for the **eSim Bridge icon** in the PCB Editor toolbar
5. If not visible: **Tools → External Plugins → Refresh Plugins**

✅ Plugin loaded successfully if the eSim Simulation Bridge icon appears in the toolbar.

> **After every code change**, clear the Python bytecode cache before restarting KiCad:
> ```bash
> rm -rf ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/__pycache__
> ```

---

## Option B - Native Ubuntu 24.04

Follow all steps in Option A starting from **A2**. The VirtualBox setup (A1) is not needed.

Apply the conflict fix from A2 if `libngspice-kicad` errors appear during KiCad installation.

---

## Option C - WSL 2 with WSLg (Windows 11)

> ⚠️ All three applications (KiCad, eSim, ngspice) are graphical. WSL without WSLg display support will not work.

### C1 - Verify GUI Support

```bash
kicad
# A KiCad window must appear - if you see display errors, use VirtualBox instead
```

If KiCad opens successfully, proceed. Otherwise, use Option A.

### C2 - Install KiCad with Conflict Fix

```bash
sudo apt update && sudo apt install kicad -y

# If libngspice-kicad conflict error:
sudo dpkg --remove --force-depends ngspice
sudo dpkg -i --force-overwrite /var/cache/apt/archives/libngspice-kicad_*.deb
sudo apt-get install -f -y
sudo apt install ngspice -y
sudo dpkg -i --force-overwrite /var/cache/apt/archives/ngspice_*.deb
sudo apt-get install -f -y
```

### C3-C6 - Follow Option A Steps A3-A6

All remaining steps are identical to the VirtualBox installation.

---

## One-Shot Install Script (Clean Ubuntu System)

Copy and run all at once:

```bash
# Step 1: Install KiCad
sudo apt update && sudo apt install -y kicad git

# Step 2: Install eSim 2.5
cd ~/Downloads
wget https://static.fossee.in/esim/installation-files/eSim-2.5.zip
unzip eSim-2.5.zip && cd eSim-2.5
chmod +x install-eSim.sh && ./install-eSim.sh --install

# Step 3: Clone and install plugin
cd ~
git clone https://github.com/FOSSEE/eSim-KiCad-Plugin.git
mkdir -p ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge
cp -r ~/eSim-KiCad-Plugin/ImranFarhat_eSim_Simulation_Bridge/eSim_Simulation_Bridge/* \
    ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/

# Step 4: Create workspace
mkdir -p ~/eSim-Workspace
echo '{"/home/'$(whoami)'/eSim-Workspace/esim_bridge_project": []}' \
    > ~/eSim-Workspace/.projectExplorer.txt

echo ""
echo "Installation complete! Launch KiCad with: kicad"
```

---

## Verification Checklist

Run these commands to verify everything is installed correctly:

```bash
echo "=== KiCad ===" && kicad-cli --version
echo "=== ngspice ===" && ngspice --version
echo "=== eSim Python ===" && ls ~/.esim/env/bin/python3
echo "=== eSim Application ===" && ls ~/Downloads/eSim-2.5/src/frontEnd/Application.py
echo "=== Plugin files ===" && \
    ls -la ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/
echo "=== ngspiceSimulation package ===" && \
    ls ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/ngspiceSimulation/
echo "=== configuration package ===" && \
    ls ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/configuration/
echo "=== __init__.py ===" && \
    cat ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/__init__.py
echo "=== eSim Workspace ===" && ls ~/eSim-Workspace/
```

---

## Post-Installation: Updating the Plugin

When a new version is released:

```bash
cd ~/eSim-KiCad-Plugin
git pull

cp -r ~/eSim-KiCad-Plugin/ImranFarhat_eSim_Simulation_Bridge/eSim_Simulation_Bridge/* \
    ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/

# Clear Python cache
rm -rf ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/__pycache__

echo "Update complete - restart KiCad"
```

---

## Troubleshooting Installation Issues

| Problem | Cause | Fix |
|---|---|---|
| `kicad-cli: command not found` | KiCad not installed | `sudo apt install kicad -y` |
| `ngspice: command not found` | Removed during KiCad install | See conflict fix commands in A2 |
| `libngspice-kicad` conflict | Both packages own the same file | See conflict fix commands in A2 |
| Plugin folder missing | Clone or copy failed | Re-clone and re-copy |
| `esim_bridge.py` is 0 bytes | Git clone got empty file | `rm -rf ~/eSim-KiCad-Plugin && git clone https://github.com/FOSSEE/eSim-KiCad-Plugin.git` |
| `ngspiceSimulation/` folder missing | Incomplete copy | Re-run the `cp -r` command in Step 3 |
| `configuration/` folder missing | Incomplete copy | Re-run the `cp -r` command in Step 3 |
| `__init__.py` empty or wrong | File corrupted | `echo "from .esim_bridge import ESimBridgePlugin" > ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/__init__.py` |
| eSim install fails | Incomplete download or permissions | Re-run `./install-eSim.sh --install` |
| KiCad shows blank icons (VirtualBox) | Wrong display controller | VM Settings → Display → **VMSVGA** + 256 MB + 3D Acceleration |
| KiCad display errors in WSL | WSLg not working | Use VirtualBox instead |
| Plugin not appearing in toolbar | KiCad not refreshed | Tools → External Plugins → Refresh Plugins |
| Code changes not taking effect | Stale `.pyc` bytecode cache | `rm -rf ~/.local/share/kicad/8.0/scripting/plugins/esim_bridge/__pycache__` |

---

*Installation guide for eSim Simulation Bridge v1.0.0*  
*Developed by Imran Farhat - FOSSEE Semester Long Internship Spring 2026, IIT Bombay*
