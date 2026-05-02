# esim_bridge.py
# eSim-BRIDGE v2.1.0 - eSim One-Click Simulation Bridge
# Enhanced with comprehensive component model library + external model loading

import pcbnew
import wx
import os
import subprocess
import re
import shutil
import logging
import random
import traceback
import tempfile
from datetime import datetime
import xml.etree.ElementTree as _ET
import struct

# ══════════════════════════════════════════════════════════════════════
# EXTERNAL MODEL LOADER - Scan user folder for .lib/.model/.subckt files
# ══════════════════════════════════════════════════════════════════════

class ExternalModelLoader:
    """
    Scans a user-specified folder for SPICE model files (.lib, .mod, .sub, .spice, .txt).
    Users simply drop manufacturer-provided model files into the folder,
    and eSim-BRIDGE automatically finds and includes them during simulation.
    
    This gives the plugin infinite scalability - no code changes needed
    to support new components.
    
    Folder structure example:
        ~/.esim-bridge/models/
        ├── 2N2222.lib          (BJT model)
        ├── TL072.lib           (op-amp subcircuit)
        ├── IRF540.spice        (MOSFET model)
        └── my_custom_ic.sub    (user's custom subcircuit)
    """
    
    # Default folder where users put their model files
    DEFAULT_MODEL_DIR = os.path.expanduser('~/.esim-bridge/models')
    
    def __init__(self, model_dir=None):
        self.model_dir = model_dir or self.DEFAULT_MODEL_DIR
        
        # Parsed models and subcircuits from external files
        # Format: {clean_name: {name, definition, source_file, type}}
        self.external_models = {}
        self.external_subcircuits = {}
        
        # Supported file extensions
        self.SUPPORTED_EXTENSIONS = ('.lib', '.mod', '.sub', '.spice', '.txt', '.cir', '.model')
        
        # Ensure the model directory exists (create it for first-time users)
        self._ensure_model_dir()
        
        # Scan and load all model files
        self._scan_model_directory()
    
    def _ensure_model_dir(self):
        """Create the model directory if it doesn't exist, with a README."""
        if not os.path.exists(self.model_dir):
            try:
                os.makedirs(self.model_dir, exist_ok=True)
                
                # Create a helpful README for first-time users
                readme_path = os.path.join(self.model_dir, 'README.txt')
                with open(readme_path, 'w') as f:
                    f.write(
                        "eSim-BRIDGE External SPICE Model Library\n"
                        "======================================\n\n"
                        "Drop your SPICE model files here!\n\n"
                        "Supported file types: .lib, .mod, .sub, .spice, .txt, .cir, .model\n\n"
                        "How to use:\n"
                        "1. Download a SPICE model from a manufacturer website\n"
                        "   (TI, Analog Devices, NXP, ON Semi, etc.)\n"
                        "2. Save the file in this folder\n"
                        "3. Run eSim-BRIDGE - it will automatically find and use the model\n\n"
                        "The file can contain .model or .subckt definitions.\n"
                        "eSim-BRIDGE will parse them automatically.\n\n"
                        "Example .model file content:\n"
                        "  .model 2N2222 NPN(Is=14.34f Bf=255.9 Vaf=74.03)\n\n"
                        "Example .subckt file content:\n"
                        "  .subckt TL072 inp inn out vcc vee\n"
                        "  ... (circuit definition) ...\n"
                        "  .ends TL072\n"
                    )
            except Exception as e:
                print(f"Could not create model directory: {e}")
    
    def _scan_model_directory(self):
        """Scan the model folder and parse all model files."""
        if not os.path.exists(self.model_dir):
            return
        
        for root, dirs, files in os.walk(self.model_dir):
            for filename in files:
                # Skip non-model files
                if not filename.lower().endswith(self.SUPPORTED_EXTENSIONS):
                    continue
                
                filepath = os.path.join(root, filename)
                try:
                    self._parse_model_file(filepath)
                except Exception as e:
                    print(f"Warning: Could not parse model file {filepath}: {e}")
    
    def _parse_model_file(self, filepath):
        """
        Parse a single SPICE model file and extract all .model and .subckt definitions.
        
        A single file can contain multiple models/subcircuits.
        """
        with open(filepath, 'r', errors='ignore') as f:
            content = f.read()
        
        filename = os.path.basename(filepath)
        
        # ── Parse .model definitions ──
        # Pattern: .model <name> <type>(<params>)
        # Can span multiple lines with + continuation
        model_pattern = re.compile(
            r'^\s*\.model\s+(\S+)\s+(NPN|PNP|NMOS|PMOS|D|NJF|PJF|NMOS|PMOS)\s*\(([^)]*)\)',
            re.MULTILINE | re.IGNORECASE
        )
        
        for match in model_pattern.finditer(content):
            model_name = match.group(1)
            model_type = match.group(2).upper()
            model_params = match.group(3)
            
            # Reconstruct the full .model line
            full_definition = f".model {model_name} {model_type}({model_params})"
            
            # Store with clean lookup key
            clean_key = re.sub(r'[^a-z0-9]', '', model_name.lower())
            
            self.external_models[clean_key] = {
                'name': model_name,
                'definition': full_definition,
                'type': model_type,
                'source_file': filename
            }
        
        # ── Parse .subckt definitions ──
        # Pattern: .subckt <name> <nodes...> \n ... \n .ends [name]
        subckt_pattern = re.compile(
            r'(^\s*\.subckt\s+(\S+)\s+.*?^\s*\.ends\b[^\n]*)',
            re.MULTILINE | re.IGNORECASE | re.DOTALL
        )
        
        for match in subckt_pattern.finditer(content):
            full_subckt = match.group(1).strip()
            subckt_name = match.group(2)
            
            clean_key = re.sub(r'[^a-z0-9]', '', subckt_name.lower())
            
            self.external_subcircuits[clean_key] = {
                'name': subckt_name,
                'definition': full_subckt,
                'source_file': filename
            }
    
    def find_model(self, component_value, description=''):
        """
        Search external models for a match.
        
        Args:
            component_value: The component's value field from KiCad (e.g., "2N2222", "TL072")
            description: Additional description text to help matching
        
        Returns:
            (model_name, model_definition, model_type) or (None, None, None)
        """
        search = (component_value + ' ' + description).lower()
        search_clean = re.sub(r'[^a-z0-9]', '', search)
        
        # Try matching against external .model definitions
        for clean_key, model_data in self.external_models.items():
            if clean_key in search_clean or search_clean in clean_key:
                return (
                    model_data['name'],
                    model_data['definition'],
                    model_data['type']
                )
        
        return None, None, None
    
    def find_subcircuit(self, component_value, description=''):
        """
        Search external subcircuits for a match.
        
        Args:
            component_value: The component's value field from KiCad
            description: Additional description text
        
        Returns:
            (subckt_name, subckt_definition) or (None, None)
        """
        search = (component_value + ' ' + description).lower()
        search_clean = re.sub(r'[^a-z0-9]', '', search)
        
        for clean_key, subckt_data in self.external_subcircuits.items():
            if clean_key in search_clean or search_clean in clean_key:
                return subckt_data['name'], subckt_data['definition']
        
        return None, None
    
    def get_stats(self):
        """Return a summary of loaded external models."""
        return {
            'model_dir': self.model_dir,
            'dir_exists': os.path.exists(self.model_dir),
            'num_models': len(self.external_models),
            'num_subcircuits': len(self.external_subcircuits),
            'models': list(self.external_models.keys()),
            'subcircuits': list(self.external_subcircuits.keys()),
        }
    
    def get_summary_text(self):
        """Return a human-readable summary for the UI."""
        stats = self.get_stats()
        if not stats['dir_exists']:
            return f"External model folder not found: {self.model_dir}"
        
        total = stats['num_models'] + stats['num_subcircuits']
        if total == 0:
            return (
                f"External model folder: {self.model_dir}\n"
                f"No external models found. Drop .lib files here to add more components."
            )
        
        return (
            f"External model folder: {self.model_dir}\n"
            f"Loaded: {stats['num_models']} device models, "
            f"{stats['num_subcircuits']} subcircuits"
        )


# ══════════════════════════════════════════════════════════════════════
# MODEL LIBRARY - Auto-injected SPICE models for common components
# ══════════════════════════════════════════════════════════════════════

class SPICEModelLibrary:
    """
    Built-in SPICE model library for common components.
    When eSim-BRIDGE encounters a component, it looks up the model here
    and auto-injects the .model or .subckt definition into the SPICE file.
    
    This eliminates the need for users to manually add model files.
    """
    
    # ── DIODE MODELS ────────────────────────────────────────────────
    DIODE_MODELS = {
        # Generic / fallback
        'default':    '.model DDEFAULT D(Is=1e-14 N=1.0 Rs=0 Cjo=10p Bv=100 Ibv=100u)',
        'dled':       '.model DLED D(Is=2.52e-9 N=1.752 Rs=0.568 Cjo=825p Bv=30 Ibv=10u)',
        'dgeneric':   '.model DGENERIC D(Is=1e-14 N=1.0 Rs=0 Cjo=10p Bv=100 Ibv=100u)',
        
        # Common signal diodes
        '1n4148':     '.model D1N4148 D(Is=2.52e-9 Rs=0.568 N=1.752 Bv=100 Ibv=100u Cjo=4p M=0.4 tt=5.76n)',
        '1n4007':     '.model D1N4007 D(Is=7.02e-9 Rs=0.0341 N=1.8 Bv=1000 Ibv=5u Cjo=26.5p M=0.35 tt=4.32u)',
        '1n4001':     '.model D1N4001 D(Is=29.5e-9 Rs=0.073 N=1.96 Bv=50 Ibv=5u Cjo=26.5p M=0.35)',
        '1n4002':     '.model D1N4002 D(Is=29.5e-9 Rs=0.073 N=1.96 Bv=100 Ibv=5u Cjo=26.5p M=0.35)',
        '1n4003':     '.model D1N4003 D(Is=29.5e-9 Rs=0.073 N=1.96 Bv=200 Ibv=5u Cjo=26.5p M=0.35)',
        '1n4004':     '.model D1N4004 D(Is=29.5e-9 Rs=0.073 N=1.96 Bv=400 Ibv=5u Cjo=26.5p M=0.35)',
        '1n5819':     '.model D1N5819 D(Is=40.7e-9 Rs=0.042 N=1.2 Bv=40 Ibv=1m Cjo=110p)',
        '1n5817':     '.model D1N5817 D(Is=31.7e-9 Rs=0.051 N=1.1 Bv=20 Ibv=1m Cjo=110p)',
        
        # Zener diodes
        'bzt52c3v3':  '.model DBZT52C3V3 D(Is=1e-14 N=1.0 Rs=10 Bv=3.3 Ibv=5m Cjo=50p)',
        'bzt52c5v1':  '.model DBZT52C5V1 D(Is=1e-14 N=1.0 Rs=10 Bv=5.1 Ibv=5m Cjo=50p)',
        '1n4733':     '.model D1N4733 D(Is=1e-14 N=1.0 Rs=10 Bv=5.1 Ibv=20m Cjo=100p)',
        '1n4740':     '.model D1N4740 D(Is=1e-14 N=1.0 Rs=10 Bv=10 Ibv=20m Cjo=100p)',
        '1n4742':     '.model D1N4742 D(Is=1e-14 N=1.0 Rs=10 Bv=12 Ibv=20m Cjo=100p)',
        '1n4744':     '.model D1N4744 D(Is=1e-14 N=1.0 Rs=10 Bv=15 Ibv=20m Cjo=100p)',
        
        # LEDs
        'led':        '.model DLED D(Is=2.52e-9 N=1.752 Rs=0.568 Cjo=825p Bv=30 Ibv=10u)',
        'led_red':    '.model DLED_RED D(Is=9.3e-10 N=3.0 Rs=1.5 Cjo=15p Bv=5 Ibv=10u)',
        'led_green':  '.model DLED_GREEN D(Is=2.3e-10 N=3.2 Rs=2.0 Cjo=15p Bv=5 Ibv=10u)',
        'led_blue':   '.model DLED_BLUE D(Is=5.4e-11 N=3.5 Rs=3.0 Cjo=15p Bv=5 Ibv=10u)',
    }
    
    # ── BJT TRANSISTOR MODELS ───────────────────────────────────────
    BJT_MODELS = {
        # Generic fallback
        'npn_default': '.model QNPN_DEFAULT NPN(Is=1e-15 Bf=100 Vaf=100 Cjc=10p Cje=15p Rb=100 Tf=0.3n)',
        'pnp_default': '.model QPNP_DEFAULT PNP(Is=1e-15 Bf=100 Vaf=100 Cjc=10p Cje=15p Rb=100 Tf=0.3n)',
        
        # Common NPN transistors
        '2n2222':     '.model Q2N2222 NPN(Is=14.34e-15 Bf=255.9 Vaf=74.03 Ikf=0.2847 Ise=14.34e-15 Ne=1.307 Br=6.092 Var=28 Ikr=0 Isc=0 Nc=2 Rb=10 Rc=1 Cjc=7.306p Mjc=0.3416 Vjc=0.75 Cje=22.01p Mje=0.377 Vje=0.75 Tf=0.345n Tr=46.91n)',
        '2n3904':     '.model Q2N3904 NPN(Is=6.734e-15 Bf=416.4 Vaf=74.03 Ikf=66.78e-3 Ise=6.734e-15 Ne=1.259 Br=0.7389 Var=28 Ikr=0 Isc=0 Nc=2 Rb=10 Rc=1 Cjc=3.638p Mjc=0.3085 Vjc=0.75 Cje=4.493p Mje=0.2593 Vje=0.75 Tf=0.301n Tr=239.5n)',
        '2n3906':     '.model Q2N3906 PNP(Is=1.41e-15 Bf=180.7 Vaf=18.7 Ikf=80e-3 Ise=0 Ne=1.5 Br=4.977 Var=100 Ikr=0 Isc=0 Nc=2 Rb=10 Rc=2.5 Cjc=9.728p Mjc=0.5776 Vjc=0.75 Cje=8.063p Mje=0.3677 Vje=0.75 Tf=0.3n Tr=50n)',
        'bc547':      '.model QBC547 NPN(Is=1.8e-14 Bf=400 Vaf=80 Ikf=0.1 Ise=5e-14 Ne=1.46 Br=35.5 Var=12.5 Ikr=0.01 Rb=10 Rc=1 Cjc=5.25p Cje=11.5p Tf=0.64n Tr=50n)',
        'bc547b':     '.model QBC547B NPN(Is=1.8e-14 Bf=400 Vaf=80 Ikf=0.1 Ise=5e-14 Ne=1.46 Br=35.5 Var=12.5 Ikr=0.01 Rb=10 Rc=1 Cjc=5.25p Cje=11.5p Tf=0.64n Tr=50n)',
        'bc548':      '.model QBC548 NPN(Is=1.95e-14 Bf=400 Vaf=80 Ikf=0.08 Ise=5e-14 Ne=1.46 Br=35.5 Var=12.5 Rb=10 Rc=1 Cjc=5.25p Cje=11.5p Tf=0.64n Tr=50n)',
        'bc557':      '.model QBC557 PNP(Is=2e-14 Bf=290 Vaf=60 Ikf=0.1 Ise=5e-14 Ne=1.46 Br=20 Var=12.5 Rb=10 Rc=1 Cjc=7.5p Cje=12.5p Tf=0.6n Tr=50n)',
        'bc558':      '.model QBC558 PNP(Is=2e-14 Bf=290 Vaf=60 Ikf=0.1 Rb=10 Rc=1 Cjc=7.5p Cje=12.5p Tf=0.6n Tr=50n)',
        '2n2907':     '.model Q2N2907 PNP(Is=650.6e-18 Bf=231.7 Vaf=116.1 Ikf=0.1856 Ise=54.81e-15 Ne=1.829 Br=3.563 Var=100 Ikr=0 Isc=0 Nc=2 Rb=10 Rc=1 Cjc=14.76p Cje=19.82p Tf=0.5n Tr=50n)',
        '2n2219':     '.model Q2N2219 NPN(Is=14.34e-15 Bf=200 Vaf=74 Ikf=0.28 Rb=10 Rc=1 Cjc=7.3p Cje=22p Tf=0.35n Tr=47n)',
        'tip31':      '.model QTIP31 NPN(Is=2e-12 Bf=60 Vaf=100 Ikf=3 Rb=5 Rc=0.1 Cjc=50p Cje=100p Tf=10n Tr=500n)',
        'tip32':      '.model QTIP32 PNP(Is=2e-12 Bf=60 Vaf=100 Ikf=3 Rb=5 Rc=0.1 Cjc=50p Cje=100p Tf=10n Tr=500n)',
    }
    
    # ── MOSFET MODELS ───────────────────────────────────────────────
    MOSFET_MODELS = {
        # Generic fallback
        'nmos_default': '.model MNMOS_DEFAULT NMOS(Level=1 Vto=0.7 Kp=110u W=10u L=1u)',
        'pmos_default': '.model MPMOS_DEFAULT PMOS(Level=1 Vto=-0.7 Kp=50u W=10u L=1u)',
        
        # Common MOSFETs
        'irf540':     '.model MIRF540 NMOS(Level=3 Vto=3.0 Kp=20.43 Rs=0.0768 Rd=0.2 Cbd=1.36n Cgso=1.95n Cgdo=0.13n)',
        'irf540n':    '.model MIRF540N NMOS(Level=3 Vto=3.0 Kp=20.43 Rs=0.0768 Rd=0.2 Cbd=1.36n Cgso=1.95n Cgdo=0.13n)',
        'irf9540':    '.model MIRF9540 PMOS(Level=3 Vto=-3.0 Kp=10.2 Rs=0.12 Rd=0.3 Cbd=1.36n Cgso=1.95n Cgdo=0.13n)',
        'irf3205':    '.model MIRF3205 NMOS(Level=3 Vto=2.0 Kp=40 Rs=0.008 Rd=0.1 Cbd=3.6n Cgso=3.2n Cgdo=0.2n)',
        'irf830':     '.model MIRF830 NMOS(Level=3 Vto=3.0 Kp=5.0 Rs=0.4 Rd=1.0 Cbd=0.5n Cgso=0.8n Cgdo=0.1n)',
        '2n7000':     '.model M2N7000 NMOS(Level=3 Vto=2.0 Kp=0.15 Rs=5.0 Rd=1.5 Cbd=35p Cgso=40p Cgdo=5p)',
        '2n7002':     '.model M2N7002 NMOS(Level=3 Vto=1.8 Kp=0.15 Rs=5.0 Rd=1.5 Cbd=35p Cgso=40p Cgdo=5p)',
        'bs170':      '.model MBS170 NMOS(Level=3 Vto=1.5 Kp=0.12 Rs=5.0 Rd=2.0 Cbd=30p Cgso=35p Cgdo=5p)',
        'bs250':      '.model MBS250 PMOS(Level=3 Vto=-2.0 Kp=0.06 Rs=8.0 Rd=3.0 Cbd=30p Cgso=35p Cgdo=5p)',
    }
    
    # ── OP-AMP SUBCIRCUITS ──────────────────────────────────────────
    OPAMP_SUBCIRCUITS = {
        'lm741': (
            '.subckt LM741 inp inn out vcc vee\n'
            '* Simplified LM741 op-amp subcircuit\n'
            'Rin inp inn 2Meg\n'
            'Egain mid 0 inp inn 200000\n'
            'Rout mid out 75\n'
            'Icc vcc vee 1.7m\n'
            '.ends LM741'
        ),
        'ua741': (
            '.subckt UA741 inp inn out vcc vee\n'
            '* Simplified UA741 op-amp subcircuit\n'
            'Rin inp inn 2Meg\n'
            'Egain mid 0 inp inn 200000\n'
            'Rout mid out 75\n'
            'Icc vcc vee 1.7m\n'
            '.ends UA741'
        ),
        'lm358': (
            '.subckt LM358 inp inn out vcc vee\n'
            '* Simplified LM358 op-amp subcircuit\n'
            'Rin inp inn 1Meg\n'
            'Egain mid 0 inp inn 100000\n'
            'Rout mid out 150\n'
            'Icc vcc vee 0.5m\n'
            '.ends LM358'
        ),
        'lm324': (
            '.subckt LM324 inp inn out vcc vee\n'
            '* Simplified LM324 op-amp subcircuit\n'
            'Rin inp inn 1Meg\n'
            'Egain mid 0 inp inn 100000\n'
            'Rout mid out 150\n'
            'Icc vcc vee 0.5m\n'
            '.ends LM324'
        ),
        'ne555': (
            '.subckt NE555 gnd trigger output reset control threshold discharge vcc\n'
            '* Simplified 555 timer subcircuit (astable behavior)\n'
            'Rctrl vcc control 5k\n'
            'Rctrl2 control gnd 10k\n'
            '.ends NE555'
        ),
        'opamp_generic': (
            '.subckt OPAMP_GENERIC inp inn out vcc vee\n'
            '* Generic ideal op-amp subcircuit\n'
            'Rin inp inn 10Meg\n'
            'Egain mid 0 inp inn 1000000\n'
            'Rout mid out 10\n'
            '.ends OPAMP_GENERIC'
        ),
    }
    
    # ── VOLTAGE REGULATOR SUBCIRCUITS ───────────────────────────────
    REGULATOR_SUBCIRCUITS = {
        '7805': (
            '.subckt REG7805 in out gnd\n'
            '* Simplified 7805 5V regulator\n'
            'Rin in mid 1\n'
            'Vreg mid out DC 0\n'
            'Breg out gnd V=min(max(V(in,gnd)-2, 0), 5)\n'
            'Rload out gnd 100k\n'
            '.ends REG7805'
        ),
        '7812': (
            '.subckt REG7812 in out gnd\n'
            '* Simplified 7812 12V regulator\n'
            'Rin in mid 1\n'
            'Vreg mid out DC 0\n'
            'Breg out gnd V=min(max(V(in,gnd)-2, 0), 12)\n'
            'Rload out gnd 100k\n'
            '.ends REG7812'
        ),
        '7833': (
            '.subckt REG7833 in out gnd\n'
            '* Simplified 78L33 3.3V regulator\n'
            'Rin in mid 1\n'
            'Vreg mid out DC 0\n'
            'Breg out gnd V=min(max(V(in,gnd)-1.5, 0), 3.3)\n'
            'Rload out gnd 100k\n'
            '.ends REG7833'
        ),
    }
    
    @classmethod
    def lookup_diode_model(cls, value, description=''):
        """
        Find the best matching diode model.
        Returns (model_name, model_definition) tuple.
        """
        search = (value + ' ' + description).lower()
        search = re.sub(r'[^a-z0-9]', '', search)
        
        # Try exact match first
        for key, model_def in cls.DIODE_MODELS.items():
            clean_key = re.sub(r'[^a-z0-9]', '', key)
            if clean_key in search or search in clean_key:
                model_name = model_def.split()[1]  # Extract model name from .model line
                return model_name, model_def
        
        # Check if it's an LED
        if any(kw in search for kw in ['led', 'lightemit']):
            return 'DLED', cls.DIODE_MODELS['dled']
        
        # Check if it's a Zener
        if any(kw in search for kw in ['zener', 'bzt', 'bzx']):
            return 'DBZT52C5V1', cls.DIODE_MODELS['bzt52c5v1']
        
        # Fallback to generic diode
        return 'DDEFAULT', cls.DIODE_MODELS['default']
    
    @classmethod
    def lookup_bjt_model(cls, value, description=''):
        """
        Find the best matching BJT model.
        Returns (model_name, model_definition, is_npn) tuple.
        """
        search = (value + ' ' + description).lower()
        search = re.sub(r'[^a-z0-9]', '', search)
        
        # Try exact match
        for key, model_def in cls.BJT_MODELS.items():
            clean_key = re.sub(r'[^a-z0-9]', '', key)
            if clean_key in search or search in clean_key:
                model_name = model_def.split()[1]
                is_npn = 'NPN' in model_def
                return model_name, model_def, is_npn
        
        # Detect PNP from description
        if any(kw in search for kw in ['pnp', '2n3906', '2n2907', 'bc557', 'bc558', 'tip32']):
            return 'QPNP_DEFAULT', cls.BJT_MODELS['pnp_default'], False
        
        # Default to NPN
        return 'QNPN_DEFAULT', cls.BJT_MODELS['npn_default'], True
    
    @classmethod
    def lookup_mosfet_model(cls, value, description=''):
        """
        Find the best matching MOSFET model.
        Returns (model_name, model_definition, is_nmos) tuple.
        """
        search = (value + ' ' + description).lower()
        search = re.sub(r'[^a-z0-9]', '', search)
        
        # Try exact match
        for key, model_def in cls.MOSFET_MODELS.items():
            clean_key = re.sub(r'[^a-z0-9]', '', key)
            if clean_key in search or search in clean_key:
                model_name = model_def.split()[1]
                is_nmos = 'NMOS' in model_def
                return model_name, model_def, is_nmos
        
        # Detect PMOS from description
        if any(kw in search for kw in ['pmos', 'pchannel', 'p-channel', 'irf9', 'bs250']):
            return 'MPMOS_DEFAULT', cls.MOSFET_MODELS['pmos_default'], False
        
        # Default to NMOS
        return 'MNMOS_DEFAULT', cls.MOSFET_MODELS['nmos_default'], True
    
    @classmethod
    def lookup_opamp_subcircuit(cls, value, description=''):
        """
        Find the best matching op-amp subcircuit.
        Returns (subckt_name, subckt_definition) or (None, None).
        """
        search = (value + ' ' + description).lower()
        search = re.sub(r'[^a-z0-9]', '', search)
        
        for key, subckt_def in cls.OPAMP_SUBCIRCUITS.items():
            clean_key = re.sub(r'[^a-z0-9]', '', key)
            if clean_key in search or search in clean_key:
                # Extract subcircuit name from .subckt line
                subckt_name = subckt_def.split('\n')[0].split()[1]
                return subckt_name, subckt_def
        
        # Check for generic op-amp keywords
        if any(kw in search for kw in ['opamp', 'op_amp', 'operational']):
            subckt_name = 'OPAMP_GENERIC'
            return subckt_name, cls.OPAMP_SUBCIRCUITS['opamp_generic']
        
        return None, None
    
    @classmethod
    def lookup_regulator_subcircuit(cls, value, description=''):
        """
        Find voltage regulator subcircuit.
        Returns (subckt_name, subckt_definition) or (None, None).
        """
        search = (value + ' ' + description).lower()
        search = re.sub(r'[^a-z0-9]', '', search)
        
        for key, subckt_def in cls.REGULATOR_SUBCIRCUITS.items():
            clean_key = re.sub(r'[^a-z0-9]', '', key)
            if clean_key in search or search in clean_key:
                subckt_name = subckt_def.split('\n')[0].split()[1]
                return subckt_name, subckt_def
        
        return None, None


# ══════════════════════════════════════════════════════════════════════
# SPICE CONVERTER - Enhanced with model library integration
# ══════════════════════════════════════════════════════════════════════

class SPICEConverter:
    """
    Converts KiCad netlist data into a SPICE deck (.cir file)
    that Ngspice/eSim can simulate.
    
    v2.1: Built-in models + external user-provided model library.
    """
    
    def __init__(self):
        self.supported_types = {
            'R': 'resistor',
            'C': 'capacitor', 
            'L': 'inductor',
            'V': 'voltage_source',
            'I': 'current_source',
            'D': 'diode',
            'Q': 'bjt_transistor',
            'M': 'mosfet',
            'J': 'jfet',
            'U': 'ic_subcircuit',
            'X': 'subcircuit',
            'SW': 'switch',
            'S': 'vswitch',
        }
        
        # Track which models need to be injected
        self.required_models = {}      # {model_name: model_definition}
        self.required_subcircuits = {}  # {subckt_name: subckt_definition}
        self.unsupported_components = []  # Track what couldn't be converted
        
        # Load external user-provided models
        self.external_loader = ExternalModelLoader()
    
    def convert(self, netlist_path, output_path, analysis_type='tran',
                analysis_params=None):
        """
        Main conversion function.
        """
        try:
            # Reset tracking
            self.required_models = {}
            self.required_subcircuits = {}
            self.unsupported_components = []
            
            # Read and parse the netlist
            components, nets = self.parse_full_netlist(netlist_path)
            
            if not components:
                return False
            
            # Build SPICE content
            spice_lines = []
            
            # Header
            spice_lines.append("* eSim Bridge Plugin - Auto-generated SPICE file")
            spice_lines.append(f"* Source: {netlist_path}")
            spice_lines.append(f"* Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            spice_lines.append(f"* eSim Bridge v2.1.0")
            ext_stats = self.external_loader.get_stats()
            spice_lines.append(f"* Built-in models: 47+ | External models: {ext_stats['num_models']} models, {ext_stats['num_subcircuits']} subcircuits")
            spice_lines.append("")
            
            # Component lines
            spice_lines.append("* ── Components ──")
            for ref, comp_data in components.items():
                spice_line = self.component_to_spice(ref, comp_data, nets)
                if spice_line:
                    spice_lines.append(spice_line)
            
            spice_lines.append("")
            
            # Inject all required models
            if self.required_models:
                spice_lines.append("* ── Auto-injected Device Models (by eSim) ──")
                for model_name, model_def in self.required_models.items():
                    spice_lines.append(model_def)
                spice_lines.append("")
            
            # Inject all required subcircuits
            if self.required_subcircuits:
                spice_lines.append("* ── Auto-injected Subcircuits (by eSim) ──")
                for subckt_name, subckt_def in self.required_subcircuits.items():
                    spice_lines.append(subckt_def)
                    spice_lines.append("")
            
            # Warn about unsupported components
            if self.unsupported_components:
                spice_lines.append("* ── Unsupported Components (skipped) ──")
                for warning in self.unsupported_components:
                    spice_lines.append(f"* WARNING: {warning}")
                spice_lines.append("")
            
            # Analysis command
            spice_lines.append("* ── Simulation Analysis ──")
            analysis_cmd = self.get_analysis_command(analysis_type, analysis_params)
            spice_lines.append(analysis_cmd)
            spice_lines.append("")
            
            # Output commands
            spice_lines.append("* ── Output ──")
            output_cmds = self.get_output_commands(nets, analysis_type)
            spice_lines.extend(output_cmds)
            spice_lines.append("")
            
            # End
            spice_lines.append(".end")
            
            # Write to file
            with open(output_path, 'w') as f:
                f.write('\n'.join(spice_lines) + '\n')
            
            return True
            
        except Exception as e:
            print(f"SPICE conversion error: {e}")
            traceback.print_exc()
            return False
    
    def parse_full_netlist(self, netlist_path):
        """
        Parse KiCad netlist file.
        Returns:
            components: {ref: {value, description, pins: {pin_num: net_name}}}
            nets: {net_name: [list of (ref, pin) connections]}
        """
        components = {}
        nets = {}
        
        with open(netlist_path, 'r') as f:
            content = f.read()
        
        # Parse components
        parts = content.split('(comp ')
        
        for part in parts[1:]:
            ref_match = re.search(r'\(ref\s+"([^"]+)"\)', part)
            if not ref_match:
                continue
            ref = ref_match.group(1)
            
            val_match = re.search(r'\(value\s+"([^"]+)"\)', part)
            value = val_match.group(1) if val_match else "?"
            
            desc_match = re.search(r'\(description\s+"([^"]+)"\)', part)
            description = desc_match.group(1) if desc_match else ""
            
            # Extract library name (helps identify component type)
            lib_match = re.search(r'\(lib\s+\(name\s+"([^"]+)"\)', part)
            lib_name = lib_match.group(1) if lib_match else ""
            
            # Extract footprint (can help distinguish packages)
            fp_match = re.search(r'\(footprint\s+"([^"]+)"\)', part)
            footprint = fp_match.group(1) if fp_match else ""
            
            # Sim.Type and Sim.Params for simulation sources
            sim_type_match = re.search(
                r'\(property\s+\(name\s+"Sim\.Type"\)\s+\(value\s+"([^"]+)"\)', part)
            sim_params_match = re.search(
                r'\(property\s+\(name\s+"Sim\.Params"\)\s+\(value\s+"([^"]+)"\)', part)
            
            sim_type = sim_type_match.group(1) if sim_type_match else ""
            sim_params = sim_params_match.group(1) if sim_params_match else ""
            
            # Sim.Name override
            sim_name_match = re.search(
                r'\(property\s+\(name\s+"Sim\.Name"\)\s+\(value\s+"([^"]+)"\)', part)
            sim_name = sim_name_match.group(1) if sim_name_match else ""
            
            components[ref] = {
                'value': value,
                'description': description,
                'lib_name': lib_name,
                'footprint': footprint,
                'sim_type': sim_type,
                'sim_params': sim_params,
                'sim_name': sim_name,
                'pins': {}
            }
        
        # Parse nets
        net_parts = content.split('(net ')
        
        for part in net_parts[1:]:
            name_match = re.search(r'\(name\s+"([^"]+)"\)', part)
            if not name_match:
                continue
            net_name = name_match.group(1)
            
            spice_net = self.clean_net_name(net_name)
            
            nets[net_name] = {
                'spice_name': spice_net,
                'nodes': []
            }
            
            node_matches = re.findall(
                r'\(node\s+\(ref\s+"([^"]+)"\)\s+\(pin\s+"([^"]+)"\)',
                part
            )
            
            for ref, pin in node_matches:
                nets[net_name]['nodes'].append((ref, pin))
                if ref in components:
                    if 'pins' not in components[ref]:
                        components[ref]['pins'] = {}
                    components[ref]['pins'][pin] = spice_net
        
        return components, nets
    
    def clean_net_name(self, net_name):
        """Clean net name for SPICE compatibility"""
        if net_name.upper() in ['GND', 'GROUND', 'VSS', '0']:
            return '0'
        
        cleaned = net_name.lstrip('/')
        cleaned = re.sub(r'[^a-zA-Z0-9]', '_', cleaned)
        cleaned = re.sub(r'_+', '_', cleaned)
        cleaned = cleaned.strip('_')
        cleaned = cleaned[:20]
        
        if not cleaned or cleaned[0].isdigit():
            cleaned = 'N' + cleaned
        
        return cleaned
    
    def component_to_spice(self, ref, comp_data, nets):
        """
        Convert a single component to its SPICE line.
        Now with automatic model lookup and injection.
        """
        if not ref:
            return None
        
        prefix = ref[0].upper()
        value = comp_data.get('value', '?')
        description = comp_data.get('description', '')
        lib_name = comp_data.get('lib_name', '')
        pins = comp_data.get('pins', {})
        
        # Get nodes in pin order
        sorted_pins = sorted(pins.keys(),
                           key=lambda x: int(x) if x.isdigit() else 0)
        nodes = [pins[p] for p in sorted_pins]
        
        # Pad with GND if missing pins
        while len(nodes) < 2:
            nodes.append('0')
        
        # ══ MULTI-CHARACTER PREFIX CHECKS (must come first!) ══
        
        # ── MICROPHONE / SENSOR (MK prefix - must check before M) ──        
        if ref.startswith('MK'):
            self.unsupported_components.append(
                f"{ref} ({value}): Microphone modeled as 10mV AC source at 1kHz")
            return f"V{ref} {nodes[1]} {nodes[0]} AC 0.01 SIN(0 0.01 1k)"
        
        # ── BATTERY (BT prefix - must check before B) ──
        elif ref.startswith('BT'):
            voltage = self._extract_numeric_value(value, default='3.7')
            return f"V{ref} {nodes[0]} {nodes[1]} DC {voltage}"
        
        # ── SWITCH (SW prefix - must check before S) ──
        elif ref.startswith('SW'):
            self.unsupported_components.append(
                f"{ref} ({value}): Switch converted to 1 ohm resistor (closed state)")
            return f"R{ref} {nodes[0]} {nodes[1]} 1"
        
        # ══ SINGLE-CHARACTER PREFIX CHECKS ══
        
        # ── RESISTOR ──        
        elif prefix == 'R':
            sanitized = re.sub(r'\s+.*', '', value)  # strip everything after first space
            if not re.match(r'^[\d.]+([rRkKmMgGuUnNpPfFtT]|meg|Meg|MEG)?$', sanitized):
                sanitized = '1k'  # fallback for "5mm LDR", "5mm", etc.
            return f"{ref} {nodes[0]} {nodes[1]} {sanitized}"
        
        # ── CAPACITOR ──
        elif prefix == 'C':
            return f"{ref} {nodes[0]} {nodes[1]} {value}"
        
        # ── INDUCTOR ──
        elif prefix == 'L':
            return f"{ref} {nodes[0]} {nodes[1]} {value}"
        
        # ── VOLTAGE SOURCE ──
        elif prefix == 'V':
            return self._convert_voltage_source(ref, comp_data, nodes)
        
        # ── CURRENT SOURCE ──
        elif prefix == 'I':
            return f"{ref} {nodes[0]} {nodes[1]} DC {value}"
        
        # ── DIODE / LED ──
        elif prefix == 'D':
            # Try external user models first, then built-in
            ext_name, ext_def, ext_type = self.external_loader.find_model(
                value, description + ' ' + lib_name)
            if ext_name and ext_type == 'D':
                model_name, model_def = ext_name, ext_def
            else:
                model_name, model_def = SPICEModelLibrary.lookup_diode_model(
                    value, description + ' ' + lib_name)
            self.required_models[model_name] = model_def
            
            # KiCad LED/Diode: pin1=Cathode(K), pin2=Anode(A)
            # SPICE diode: D<name> <anode> <cathode> <model>
            anode = nodes[1] if len(nodes) > 1 else nodes[0]
            cathode = nodes[0]
            return f"{ref} {anode} {cathode} {model_name}"
        
        # ── BJT TRANSISTOR ──
        elif prefix == 'Q':
            # Try external user models first, then built-in
            ext_name, ext_def, ext_type = self.external_loader.find_model(
                value, description + ' ' + lib_name)
            if ext_name and ext_type in ('NPN', 'PNP'):
                model_name, model_def = ext_name, ext_def
                is_npn = ext_type == 'NPN'
            else:
                model_name, model_def, is_npn = SPICEModelLibrary.lookup_bjt_model(
                    value, description + ' ' + lib_name)
            self.required_models[model_name] = model_def
            
            # Ensure we have 3 nodes: collector, base, emitter
            while len(nodes) < 3:
                nodes.append('0')
            

            # BC547 KiCad: pin1=Collector, pin2=Base, pin3=Emitter
            # SPICE BJT: Q<name> <collector> <base> <emitter> <model>
            collector = nodes[0]   # pin 1 = Collector
            base      = nodes[1]   # pin 2 = Base
            emitter   = nodes[2] if len(nodes) > 2 else '0'   # pin 3 = Emitter
            return f"{ref} {collector} {base} {emitter} {model_name}"
        
        # ── MOSFET ──
        elif prefix == 'M':
            # Try external user models first, then built-in
            ext_name, ext_def, ext_type = self.external_loader.find_model(
                value, description + ' ' + lib_name)
            if ext_name and ext_type in ('NMOS', 'PMOS'):
                model_name, model_def = ext_name, ext_def
                is_nmos = ext_type == 'NMOS'
            else:
                model_name, model_def, is_nmos = SPICEModelLibrary.lookup_mosfet_model(
                    value, description + ' ' + lib_name)
            self.required_models[model_name] = model_def
            
            # Ensure 4 nodes: drain, gate, source, bulk
            while len(nodes) < 4:
                nodes.append('0')
            
            # KiCad typical: 1=Gate, 2=Drain, 3=Source
            # SPICE: M<name> <drain> <gate> <source> <bulk> <model>
            drain = nodes[1] if len(nodes) > 1 else nodes[0]
            gate = nodes[0]
            source = nodes[2] if len(nodes) > 2 else '0'
            bulk = nodes[3] if len(nodes) > 3 else source
            return f"{ref} {drain} {gate} {source} {bulk} {model_name}"
        
        # ── JFET ──
        elif prefix == 'J':
            # JFET: J<name> <drain> <gate> <source> <model>
            while len(nodes) < 3:
                nodes.append('0')
            # Try external user models first
            ext_name, ext_def, ext_type = self.external_loader.find_model(
                value, description + ' ' + lib_name)
            if ext_name and ext_type in ('NJF', 'PJF'):
                model_name, model_def = ext_name, ext_def
            else:
                model_name = 'JNFET_DEFAULT'
                model_def = '.model JNFET_DEFAULT NJF(Vto=-2.0 Beta=1.304m Lambda=2.25m Rd=0 Rs=0 Cgs=3.1p Cgd=1.6p Is=33.57f)'
            self.required_models[model_name] = model_def
            return f"{ref} {nodes[0]} {nodes[1]} {nodes[2]} {model_name}"
        
        # ── IC / SUBCIRCUIT (U prefix) ──
        elif prefix == 'U' or prefix == 'X':
            return self._convert_ic_subcircuit(ref, comp_data, nodes)
        
        # ── VOLTAGE-CONTROLLED SWITCH (S prefix, not SW) ──
        elif prefix == 'S':
            self.unsupported_components.append(
                f"{ref} ({value}): Switch converted to 1 ohm resistor (closed state)")
            return f"R{ref} {nodes[0]} {nodes[1]} 1"
        
        # ── FUSE ──
        elif prefix == 'F':
            # Fuse - model as small resistance
            return f"R{ref} {nodes[0]} {nodes[1]} 0.01"
        
        # ── TRANSFORMER ──
        elif prefix == 'T':
            self.unsupported_components.append(
                f"{ref} ({value}): Transformer needs manual .subckt definition")
            return f"* TRANSFORMER {ref}: needs .subckt - {value}"
        
        # ── UNKNOWN ──
        else:
            node_str = ' '.join(nodes)
            self.unsupported_components.append(
                f"{ref} ({value}): Unknown component type '{prefix}'")
            return f"* UNKNOWN: {ref} {node_str} {value}"
    
    def _convert_voltage_source(self, ref, comp_data, nodes):
        """Handle voltage source conversion with all source types"""
        value = comp_data.get('value', '5')
        sim_type = comp_data.get('sim_type', '')
        sim_params = comp_data.get('sim_params', '')
        
        if sim_type == 'SIN' and sim_params:
            params = {}
            for p in sim_params.split():
                if '=' in p:
                    k, v = p.split('=')
                    params[k] = v
            dc = params.get('dc', '0')
            ampl = params.get('ampl', '1')
            freq = params.get('f', '1k')
            ac = params.get('ac', '1')
            return f"{ref} {nodes[0]} {nodes[1]} AC {ac} SIN({dc} {ampl} {freq})"
        
        elif sim_type == 'PULSE' and sim_params:
            params = {}
            for p in sim_params.split():
                if '=' in p:
                    k, v = p.split('=')
                    params[k] = v
            v1 = params.get('v1', '0')
            v2 = params.get('v2', '5')
            td = params.get('td', '0')
            tr = params.get('tr', '1n')
            tf = params.get('tf', '1n')
            pw = params.get('pw', '5m')
            per = params.get('per', '10m')
            return f"{ref} {nodes[0]} {nodes[1]} PULSE({v1} {v2} {td} {tr} {tf} {pw} {per})"
        
        elif sim_type == 'DC':
            params = {}
            for p in sim_params.split():
                if '=' in p:
                    k, v = p.split('=', 1)
                    params[k.lower()] = v
            dc_val = params.get('dc', '5')
            return f"{ref} {nodes[0]} {nodes[1]} DC {dc_val}"
        
        elif value.upper() in ('VSIN', 'VPULSE', 'VAC', 'VDC'):
            # KiCad symbol name used as value — default to DC 5
            return f"{ref} {nodes[0]} {nodes[1]} DC 5"
        
        elif any(kw in value.upper() for kw in ['DC', 'AC', 'PULSE', 'SIN']):
            return f"{ref} {nodes[0]} {nodes[1]} {value}"
        
        else:
            return f"{ref} {nodes[0]} {nodes[1]} DC {value}"
    
    def _convert_ic_subcircuit(self, ref, comp_data, nodes):
        """Handle IC/subcircuit conversion with model lookup.
        Search order: 1) Built-in library  2) External user models  3) Unsupported"""
        value = comp_data.get('value', '')
        description = comp_data.get('description', '')
        lib_name = comp_data.get('lib_name', '')
        search_text = value + ' ' + description + ' ' + lib_name
        
        # 1) Try built-in op-amp lookup
        subckt_name, subckt_def = SPICEModelLibrary.lookup_opamp_subcircuit(
            value, description)
        if subckt_name:
            self.required_subcircuits[subckt_name] = subckt_def
            node_str = ' '.join(nodes)
            return f"X{ref} {node_str} {subckt_name}"
        
        # 2) Try built-in regulator lookup
        subckt_name, subckt_def = SPICEModelLibrary.lookup_regulator_subcircuit(
            value, description)
        if subckt_name:
            self.required_subcircuits[subckt_name] = subckt_def
            node_str = ' '.join(nodes)
            return f"X{ref} {node_str} {subckt_name}"
        
        # 3) Try external user-provided subcircuit
        subckt_name, subckt_def = self.external_loader.find_subcircuit(
            value, description)
        if subckt_name:
            self.required_subcircuits[subckt_name] = subckt_def
            node_str = ' '.join(nodes)
            return f"X{ref} {node_str} {subckt_name}"
        
        # 4) Try external user-provided model (some ICs use .model instead of .subckt)
        model_name, model_def, model_type = self.external_loader.find_model(
            value, description)
        if model_name:
            self.required_models[model_name] = model_def
            node_str = ' '.join(nodes)
            return f"X{ref} {node_str} {model_name}"
        

        # 5) Check if eSim SPICE can find it in eSim library
        try:
            import sys
            plugin_dir = os.path.dirname(__file__)
            if plugin_dir not in sys.path:
                sys.path.insert(0, plugin_dir)
            from esim_spice_linker import SPICEAutoLinker
            if not hasattr(self, '_pspice_linker'):
                self._pspice_linker = SPICEAutoLinker()
            result = self._pspice_linker.get_model_for_component(ref, value, '')
            if result['status'] in ('esim_subcircuit', 'equivalent'):
                subckt_name = result['model_name']
                subckt_def = result['model_definition']
                self.required_subcircuits[subckt_name] = subckt_def
                # Also inject dependencies
                for dep in result.get('dependencies', []):
                    if dep.get('name') and dep.get('definition'):
                        self.required_models[dep['name']] = dep['definition']
                node_str = ' '.join(nodes)
                return f"X{ref} {node_str} {subckt_name}"
        except Exception:
            pass

        # 6) Nothing found anywhere - report as unsupported
        node_str = ' '.join(nodes)
        self.unsupported_components.append(
            f"{ref} ({value}): IC needs .subckt model - not in built-in or external library. "
            f"Download the SPICE model and save it to: {self.external_loader.model_dir}")
        return f"* UNSUPPORTED IC: {ref} {node_str} {value}"
    
    def _extract_numeric_value(self, value, default='5'):
        """Extract a numeric value from a component value string"""
        match = re.search(r'[\d.]+', value)
        if match:
            return match.group()
        return default
    
    def get_analysis_command(self, analysis_type, params=None):
        """Generate the Ngspice analysis command."""
        if params is None:
            params = {}
        
        if analysis_type == 'tran':
            start = params.get('start', '0')
            step = params.get('step', '1us')
            stop = params.get('stop', '10ms')
            return f".tran {step} {stop} {start}"
        
        elif analysis_type == 'ac':
            scale = params.get('scale', 'dec')
            points = params.get('points', '100')
            fstart = params.get('fstart', '1Hz')
            fstop = params.get('fstop', '1MEGHz')
            return f".ac {scale} {points} {fstart} {fstop}"
        
        elif analysis_type == 'dc':
            source = params.get('source', 'V1')
            start = params.get('start', '0')
            stop = params.get('stop', '5')
            step = params.get('step', '0.1')
            return f".dc {source} {start} {stop} {step}"
        
        elif analysis_type == 'op':
            return ".op"
        

        elif analysis_type == 'noise':
            output = params.get('output', 'out')
            source = params.get('source', 'V1')
            fstart = params.get('fstart', '1')
            fstop  = params.get('fstop', '1Meg')
            points = params.get('points', '100')
            return f".noise v({output}) {source} dec {points} {fstart} {fstop}"
        
        else:
            return ".tran 1us 10ms"
    
    def get_output_commands(self, nets, analysis_type):
        """Generate .print and .probe commands."""
        commands = []
        
        output_nets = [
            data['spice_name'] 
            for name, data in nets.items()
            if data['spice_name'] != '0'
        ]
        
        if not output_nets:
            return [".probe v(*)"]
        

        
        commands.append(".probe v(*)")
        return commands
    
    def get_unsupported_summary(self):
        """Return a summary of unsupported components for the user"""
        if not self.unsupported_components:
            return None
        return "\n".join(self.unsupported_components)
    
    
    def _rewrite_with_models(self, output_path):
        with open(output_path, 'r') as f:
            content = f.read()
        
        # Find model/subckt names already written to the file
        existing = set(re.findall(r'\.model\s+(\S+)', content, re.IGNORECASE))
        existing |= set(re.findall(r'\.subckt\s+(\S+)', content, re.IGNORECASE))
        
        content = content.replace('\n.end\n', '\n')
        
        new_models = {n: d for n, d in self.required_models.items() if n not in existing}
        if new_models:
            content += "\n* ── eSim Library Models (by eSim-SPICE) ──\n"
            for name, defn in new_models.items():
                content += defn + "\n"
        
        new_subcircuits = {n: d for n, d in self.required_subcircuits.items() if n not in existing}
        if new_subcircuits:
            content += "\n* ── eSim Library Subcircuits (by eSim-SPICE) ──\n"
            for name, defn in new_subcircuits.items():
                content += defn + "\n\n"
        
        content += "\n.end\n"
        
        with open(output_path, 'w') as f:
            f.write(content)



# ══════════════════════════════════════════════════════════════════════
# KICAD TO NGSPICE DIALOG - Replaces AnalysisConfigDialog
# Mirrors eSim's 5-tab KicadToNgspice window exactly:
#   Tab 1: Analysis        (AC / DC / Transient / OP)
#   Tab 2: Source Details  (sine/pulse/pwl/ac/dc/exp per source)
#   Tab 3: Ngspice Model   (U-prefix analog/digital behavioral models via XML)
#   Tab 4: Device Modeling (file picker for Q/D/J/M/S components)
#   Tab 5: Subcircuits     (directory picker for X-prefix components)
#
# HOW TO INTEGRATE:
#   1. Delete the entire AnalysisConfigDialog class from esim_bridge.py
#   2. Paste this entire file's content in its place
#   3. In Run(), replace the AnalysisConfigDialog block with the
#      NEW RUN FLOW shown at the bottom of this file
# ══════════════════════════════════════════════════════════════════════




class KicadToNgspiceDialog(wx.Dialog):
    """
    Single tabbed dialog mirroring eSim's KicadToNgspice window.
    Must be created AFTER the netlist is parsed so Source Details,
    Ngspice Model, Device Modeling and Subcircuits tabs are built
    dynamically from the schematic content.
    """

    MODEL_XML_DIR = os.path.expanduser(
        '~/Downloads/eSim-2.5/library/modelParamXML')

    def __init__(self, parent, components):
        super().__init__(
            parent,
            title="KiCad to Ngspice Converter  -  eSim Bridge v2.1",
            size=(1000, 700),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        )
        self.components = components

        # Analysis tab
        self._analysis_type   = 'tran'
        self._analysis_params = {}

        # Source Details tab
        self._source_overrides = {}
        self._source_widgets   = {}
        self._source_types     = {}

        # Ngspice Model tab
        self._ngmodel_parsed  = {}   # {ref: {model_type, params}}
        self._ngmodel_widgets = {}   # {ref: {key: wx.TextCtrl}}
        self._ngmodel_lines   = []   # filled on OK

        # Device Modeling tab
        self._device_lib_paths = {}
        self._device_entry     = {}

        # Subcircuits tab
        self._subcircuit_paths = {}
        self._subckt_entry     = {}

        self._build_ui()
        self.Centre()

    # ══════════════════════════════════════════════════════════════
    # TOP-LEVEL UI
    # ══════════════════════════════════════════════════════════════

    def _build_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(self, label="eSim One-Click Simulation Bridge")
        title.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT,
                              wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        main_sizer.Add(title, 0, wx.ALL, 10)

        ext_loader = ExternalModelLoader()
        ext_stats  = ext_loader.get_stats()
        ext_count  = ext_stats['num_models'] + ext_stats['num_subcircuits']
        ver_text   = "eSim Bridge v2.1 - 47+ built-in models"
        if ext_count > 0:
            ver_text += f" + {ext_count} external models"
        ver = wx.StaticText(self, label=ver_text)
        ver.SetForegroundColour(wx.Colour(0, 100, 0))
        main_sizer.Add(ver, 0, wx.LEFT | wx.BOTTOM, 10)

        main_sizer.Add(wx.StaticLine(self), 0,
                       wx.EXPAND | wx.LEFT | wx.RIGHT, 10)


        self.nb = wx.Notebook(self, style=wx.NB_TOP)
        main_sizer.Add(self.nb, 1, wx.EXPAND | wx.ALL, 10)

        self._build_analysis_tab()
        self._build_source_tab()
        self._build_ngmodel_tab()
        self._build_device_tab()
        self._build_subcircuit_tab()
        self._build_microcontroller_tab()

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn     = wx.Button(self, wx.ID_OK,     "Convert  ->")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Cancel")
        ok_btn.SetDefault()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        main_sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        ok_btn.Bind(wx.EVT_BUTTON, self._on_ok)
        self.SetSizer(main_sizer)
        self.Fit()



    

    # ══════════════════════════════════════════════════════════════
    # TAB 1 - ANALYSIS
    # ══════════════════════════════════════════════════════════════

    def _build_analysis_tab(self):
        panel = wx.ScrolledWindow(self.nb)
        panel.SetScrollRate(0, 10)
        sizer = wx.BoxSizer(wx.VERTICAL)

        type_box = wx.StaticBox(panel, label="Select Analysis Type")
        type_bsz = wx.StaticBoxSizer(type_box, wx.HORIZONTAL)
        self._cb_ac    = wx.CheckBox(panel, label="AC")
        self._cb_dc    = wx.CheckBox(panel, label="DC")
        self._cb_tran  = wx.CheckBox(panel, label="TRANSIENT")
        self._cb_noise = wx.CheckBox(panel, label="NOISE")
        self._cb_tf    = wx.CheckBox(panel, label="TRANSFER FUNCTION")
        self._cb_sens  = wx.CheckBox(panel, label="SENSITIVITY")
        self._cb_tran.SetValue(True)
        for cb in (self._cb_ac, self._cb_dc, self._cb_tran, self._cb_noise, self._cb_tf, self._cb_sens):
            type_bsz.Add(cb, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 8)
            cb.Bind(wx.EVT_CHECKBOX, self._on_analysis_checkbox)
        sizer.Add(type_bsz, 0, wx.EXPAND | wx.ALL, 8)

        # Wrap each group in its own panel for proper Show/Hide
        self._ac_panel = wx.Panel(panel)
        ac_sizer = wx.BoxSizer(wx.VERTICAL)
        ac_sizer.Add(self._make_ac_group(self._ac_panel), 0, wx.EXPAND)
        self._ac_panel.SetSizer(ac_sizer)
        sizer.Add(self._ac_panel, 0, wx.EXPAND | wx.ALL, 8)

        self._dc_panel = wx.Panel(panel)
        dc_sizer = wx.BoxSizer(wx.VERTICAL)
        dc_sizer.Add(self._make_dc_group(self._dc_panel), 0, wx.EXPAND)
        self._dc_panel.SetSizer(dc_sizer)
        sizer.Add(self._dc_panel, 0, wx.EXPAND | wx.ALL, 8)

        self._tran_panel = wx.Panel(panel)
        tran_sizer = wx.BoxSizer(wx.VERTICAL)
        tran_sizer.Add(self._make_tran_group(self._tran_panel), 0, wx.EXPAND)
        self._tran_panel.SetSizer(tran_sizer)
        sizer.Add(self._tran_panel, 0, wx.EXPAND | wx.ALL, 8)

        self._noise_panel = wx.Panel(panel)
        noise_sizer = wx.BoxSizer(wx.VERTICAL)
        noise_sizer.Add(self._make_noise_group(self._noise_panel), 0, wx.EXPAND)
        self._noise_panel.SetSizer(noise_sizer)
        sizer.Add(self._noise_panel, 0, wx.EXPAND | wx.ALL, 8)

        self._tf_panel = wx.Panel(panel)
        tf_sizer = wx.BoxSizer(wx.VERTICAL)
        tf_sizer.Add(self._make_tf_group(self._tf_panel), 0, wx.EXPAND)
        self._tf_panel.SetSizer(tf_sizer)
        sizer.Add(self._tf_panel, 0, wx.EXPAND | wx.ALL, 8)

        self._sens_panel = wx.Panel(panel)
        sens_sizer = wx.BoxSizer(wx.VERTICAL)
        sens_sizer.Add(self._make_sens_group(self._sens_panel), 0, wx.EXPAND)
        self._sens_panel.SetSizer(sens_sizer)
        sizer.Add(self._sens_panel, 0, wx.EXPAND | wx.ALL, 8)

        # Show only TRANSIENT by default
        self._ac_panel.Show(False)
        self._dc_panel.Show(False)
        self._tran_panel.Show(True)
        self._noise_panel.Show(False)
        self._tf_panel.Show(False)
        self._sens_panel.Show(False)

        panel.SetSizer(sizer)
        self.nb.AddPage(panel, "Analysis")
        self._analysis_panel = panel

    def _make_ac_group(self, parent):
        box  = wx.StaticBox(parent, label="AC Analysis")
        bsz  = wx.StaticBoxSizer(box, wx.VERTICAL)
        grid = wx.FlexGridSizer(rows=0, cols=3, vgap=6, hgap=10)
        grid.AddGrowableCol(1)

        grid.Add(wx.StaticText(parent, label="Scale"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        sp = wx.Panel(parent)
        ss = wx.BoxSizer(wx.HORIZONTAL)
        self._ac_lin = wx.RadioButton(sp, label="Lin", style=wx.RB_GROUP)
        self._ac_dec = wx.RadioButton(sp, label="Dec")
        self._ac_oct = wx.RadioButton(sp, label="Oct")
        self._ac_dec.SetValue(True)
        for rb in (self._ac_lin, self._ac_dec, self._ac_oct):
            ss.Add(rb, 0, wx.RIGHT, 8)
        sp.SetSizer(ss)
        grid.Add(sp, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(wx.StaticText(parent, label=""), 0)

        grid.Add(wx.StaticText(parent, label="Start Frequency"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._ac_fstart = wx.TextCtrl(parent, value="1")
        grid.Add(self._ac_fstart, 1, wx.EXPAND)
        self._ac_fstart_unit = wx.Choice(
            parent, choices=["Hz", "KHz", "Meg", "GHz", "THz"])
        self._ac_fstart_unit.SetSelection(0)
        grid.Add(self._ac_fstart_unit, 0)

        grid.Add(wx.StaticText(parent, label="Stop Frequency"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._ac_fstop = wx.TextCtrl(parent, value="1")
        grid.Add(self._ac_fstop, 1, wx.EXPAND)
        self._ac_fstop_unit = wx.Choice(
            parent, choices=["Hz", "KHz", "Meg", "GHz", "THz"])
        self._ac_fstop_unit.SetSelection(2)
        grid.Add(self._ac_fstop_unit, 0)

        grid.Add(wx.StaticText(parent, label="No. of Points"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._ac_points = wx.TextCtrl(parent, value="100")
        grid.Add(self._ac_points, 1, wx.EXPAND)
        grid.Add(wx.StaticText(parent, label=""), 0)

        bsz.Add(grid, 0, wx.EXPAND | wx.ALL, 6)
        return bsz
    


    def _build_microcontroller_tab(self):
        panel = wx.ScrolledWindow(self.nb)
        panel.SetScrollRate(0, 10)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Check NGHDL installation
        nghdl_config = os.path.expanduser('~/.nghdl/config.ini')
        nghdl_installed = os.path.exists(nghdl_config)

        # Status box
        status_box = wx.StaticBox(panel, label="NGHDL Status")
        status_bsz = wx.StaticBoxSizer(status_box, wx.VERTICAL)

        if nghdl_installed:
            status_text = wx.StaticText(panel,
                label="NGHDL is installed and available.")
            status_text.SetForegroundColour(wx.Colour(0, 128, 0))
        else:
            status_text = wx.StaticText(panel,
                label="NGHDL is NOT installed on this system.\n"
                    "Microcontroller simulation requires NGHDL.\n\n"
                    "Install NGHDL from:\n"
                    "https://github.com/FOSSEE/NGHDL")
            status_text.SetForegroundColour(wx.Colour(200, 0, 0))



        nghdl_home = "Not configured"
        if nghdl_installed:
            from configparser import ConfigParser
            parser = ConfigParser()
            parser.read(nghdl_config)
            try:
                nghdl_home = parser.get('NGHDL', 'NGHDL_HOME')
            except:
                nghdl_home = "Could not read NGHDL_HOME from config"

        # Then add this to the status_bsz display:
        if nghdl_installed:
            home_text = wx.StaticText(panel, label=f"NGHDL Home: {nghdl_home}")
            home_text.SetForegroundColour(wx.Colour(0, 80, 0))
            status_bsz.Add(home_text, 0, wx.LEFT | wx.BOTTOM, 10)

        status_bsz.Add(status_text, 0, wx.ALL, 10)
        sizer.Add(status_bsz, 0, wx.EXPAND | wx.ALL, 8)

        # MCU components detected
        mcu_keywords = ['attiny', 'arduino', 'atmega', 'pic', 'stm32',
                        'esp', 'avr', 'microcontroller', 'mcu']
        mcu_comps = {}
        for ref, cd in self.components.items():
            value = cd.get('value', '').lower()
            if any(kw in value for kw in mcu_keywords):
                mcu_comps[ref] = cd

        mcu_box = wx.StaticBox(panel, label="Microcontroller Components")
        mcu_bsz = wx.StaticBoxSizer(mcu_box, wx.VERTICAL)



        # Load previous hex file paths
        prev_hex = {}
        prev_xml = os.path.expanduser('~/.esim-bridge/mcu_previous_values.xml')
        if os.path.exists(prev_xml):
            try:
                tree = _ET.parse(prev_xml)
                root_elem = tree.getroot()
                for child in root_elem:
                    if child.tag == 'mcu':
                        ref = child.get('ref', '')
                        hexpath = child.get('hexpath', '')
                        if ref and hexpath:
                            prev_hex[ref] = hexpath
            except:
                pass

        if not mcu_comps:
            no_mcu = wx.StaticText(panel,
                label="No microcontroller components detected in schematic.\n"
                    "MCU components should have values like: ATtiny85,\n"
                    "Arduino, ATmega328, PIC16F877, STM32F103 etc.")
            no_mcu.SetForegroundColour(wx.Colour(100, 100, 100))
            mcu_bsz.Add(no_mcu, 0, wx.ALL, 10)
        else:
            self._mcu_hex_paths = {}
            grid = wx.FlexGridSizer(rows=0, cols=4, vgap=6, hgap=10)
            grid.AddGrowableCol(2)

            for ref, cd in sorted(mcu_comps.items()):
                value = cd.get('value', '')
                instance_id = str(random.randint(0, 99))

                grid.Add(wx.StaticText(panel, label=ref),
                        0, wx.ALIGN_CENTER_VERTICAL)
                grid.Add(wx.StaticText(panel, label=value),
                        0, wx.ALIGN_CENTER_VERTICAL)


                prev_path = prev_hex.get(ref, "")
                hex_tc = wx.TextCtrl(panel, value=prev_path,
                                    style=wx.TE_READONLY, size=(200, -1))
                self._mcu_hex_paths[ref] = {
                    'tc': hex_tc,
                    'instance_id': instance_id,
                    'value': value
                }
                grid.Add(hex_tc, 1, wx.EXPAND)

                add_btn = wx.Button(panel, label="Add Hex File")
                add_btn.Bind(wx.EVT_BUTTON,
                    lambda evt, r=ref: self._pick_hex_file(r))
                grid.Add(add_btn, 0)

            mcu_bsz.Add(grid, 0, wx.EXPAND | wx.ALL, 8)

            if not nghdl_installed:
                warn = wx.StaticText(panel,
                    label="Note: NGHDL is required to simulate these components.")
                warn.SetForegroundColour(wx.Colour(200, 100, 0))
                mcu_bsz.Add(warn, 0, wx.ALL, 8)

        sizer.Add(mcu_bsz, 0, wx.EXPAND | wx.ALL, 8)

        # Info box
        info_box = wx.StaticBox(panel, label="About Microcontroller Simulation")
        info_bsz = wx.StaticBoxSizer(info_box, wx.VERTICAL)
        info_text = wx.StaticText(panel,
            label="eSim uses NGHDL to simulate microcontrollers alongside\n"
                "analog circuits. NGHDL converts compiled .hex firmware\n"
                "into a behavioral SPICE model that ngspice can simulate.\n\n"
                "Workflow:\n"
                "1. Write MCU firmware in C/Arduino\n"
                "2. Compile to .hex using avr-gcc or Arduino IDE\n"
                "3. Install NGHDL from github.com/FOSSEE/NGHDL\n"
                "4. Add .hex file here\n"
                "5. Run simulation in eSim")
        info_text.SetForegroundColour(wx.Colour(80, 80, 80))
        info_bsz.Add(info_text, 0, wx.ALL, 10)
        sizer.Add(info_bsz, 0, wx.EXPAND | wx.ALL, 8)

        panel.SetSizer(sizer)
        self.nb.AddPage(panel, "Microcontroller")


    def _save_mcu_previous_values(self):
        """Save MCU hex file paths for next session - mirrors eSim's Previous_Values.xml"""
        if not hasattr(self, '_mcu_hex_paths') or not self._mcu_hex_paths:
            return
        try:
            save_dir = os.path.expanduser('~/.esim-bridge')
            os.makedirs(save_dir, exist_ok=True)
            root_elem = _ET.Element('microcontroller')
            for ref, data in self._mcu_hex_paths.items():
                hexpath = data['tc'].GetValue().strip()
                if hexpath:
                    child = _ET.SubElement(root_elem, 'mcu')
                    child.set('ref', ref)
                    child.set('value', data.get('value', ''))
                    child.set('instance_id', data.get('instance_id', '0'))
                    child.set('hexpath', hexpath)
            tree = _ET.ElementTree(root_elem)
            tree.write(os.path.expanduser('~/.esim-bridge/mcu_previous_values.xml'))
        except Exception as e:
            print(f"Could not save MCU previous values: {e}")


    def _make_dc_group(self, parent):
        box   = wx.StaticBox(parent, label="DC Analysis")
        bsz   = wx.StaticBoxSizer(box, wx.VERTICAL)
        UNITS = ["Volts or Amperes", "mV or mA",
                 "uV or uA", "nV or nA", "pV or pA"]

        def _row(lbl, default, units=None):
            rs = wx.BoxSizer(wx.HORIZONTAL)
            rs.Add(wx.StaticText(parent, label=lbl, size=(130, -1)),
                   0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
            tc = wx.TextCtrl(parent, value=default, size=(100, -1))
            rs.Add(tc, 0)
            ch = None
            if units:
                ch = wx.Choice(parent, choices=units)
                ch.SetSelection(0)
                rs.Add(ch, 0, wx.LEFT, 6)
            return rs, tc, ch

        bsz.Add(wx.StaticText(parent, label="Source 1"), 0, wx.ALL, 4)
        r, self._dc_src1,   _ = _row("Enter Source 1", "V1")
        bsz.Add(r, 0, wx.ALL, 3)
        r, self._dc_start1, self._dc_start1_u = _row("Start",     "0",   UNITS)
        bsz.Add(r, 0, wx.ALL, 3)
        r, self._dc_inc1,   self._dc_inc1_u   = _row("Increment", "0.1", UNITS)
        bsz.Add(r, 0, wx.ALL, 3)
        r, self._dc_stop1,  self._dc_stop1_u  = _row("Stop",      "5",   UNITS)
        bsz.Add(r, 0, wx.ALL, 3)

        bsz.Add(wx.StaticLine(parent), 0, wx.EXPAND | wx.ALL, 4)
        bsz.Add(wx.StaticText(parent, label="Source 2 (optional)"), 0, wx.ALL, 4)
        r, self._dc_src2,   _ = _row("Enter Source 2", "")
        bsz.Add(r, 0, wx.ALL, 3)
        r, self._dc_start2, self._dc_start2_u = _row("Start",     "0",   UNITS)
        bsz.Add(r, 0, wx.ALL, 3)
        r, self._dc_inc2,   self._dc_inc2_u   = _row("Increment", "0.1", UNITS)
        bsz.Add(r, 0, wx.ALL, 3)
        r, self._dc_stop2,  self._dc_stop2_u  = _row("Stop",      "5",   UNITS)
        bsz.Add(r, 0, wx.ALL, 3)

        self._dc_op_check = wx.CheckBox(
            parent, label="Operating Point Analysis")
        bsz.Add(self._dc_op_check, 0, wx.ALL, 6)
        return bsz
    
    def _pick_hex_file(self, ref):
        dlg = wx.FileDialog(
            self, f"Select .hex file for {ref}",
            wildcard="HEX files (*.hex)|*.hex|Text files (*.txt)|*.txt",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self._mcu_hex_paths[ref]['tc'].SetValue(path)
        dlg.Destroy()

    def _make_tran_group(self, parent):
        box  = wx.StaticBox(parent, label="Transient Analysis")
        bsz  = wx.StaticBoxSizer(box, wx.VERTICAL)
        grid = wx.FlexGridSizer(rows=0, cols=3, vgap=6, hgap=10)
        grid.AddGrowableCol(1)
        UNITS = ["sec", "ms", "us", "ns", "ps"]

        def _trow(lbl, val, unit_idx):
            grid.Add(wx.StaticText(parent, label=lbl),
                     0, wx.ALIGN_CENTER_VERTICAL)
            tc = wx.TextCtrl(parent, value=val)
            grid.Add(tc, 1, wx.EXPAND)
            ch = wx.Choice(parent, choices=UNITS)
            ch.SetSelection(unit_idx)
            grid.Add(ch, 0)
            return tc, ch

        self._tran_start, self._tran_start_u = _trow("Start Time", "0",   1)
        self._tran_step,  self._tran_step_u  = _trow("Step Time",  "0.1", 1)
        self._tran_stop,  self._tran_stop_u  = _trow("Stop Time",  "10",  1)
        bsz.Add(grid, 0, wx.EXPAND | wx.ALL, 6)
        return bsz
    

    def _make_noise_group(self, parent):
        box  = wx.StaticBox(parent, label="Noise Analysis")
        bsz  = wx.StaticBoxSizer(box, wx.VERTICAL)
        grid = wx.FlexGridSizer(rows=0, cols=3, vgap=6, hgap=10)
        grid.AddGrowableCol(1)
        UNITS = ["Hz", "KHz", "Meg", "GHz"]

        grid.Add(wx.StaticText(parent, label="Output Node"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._noise_output = wx.TextCtrl(parent, value="out")
        grid.Add(self._noise_output, 1, wx.EXPAND)
        grid.Add(wx.StaticText(parent, label="e.g. out, net_r1"), 0)

        grid.Add(wx.StaticText(parent, label="Input Source"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._noise_source = wx.TextCtrl(parent, value="V1")
        grid.Add(self._noise_source, 1, wx.EXPAND)
        grid.Add(wx.StaticText(parent, label="e.g. V1, V2"), 0)

        grid.Add(wx.StaticText(parent, label="Start Frequency"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._noise_fstart = wx.TextCtrl(parent, value="1")
        grid.Add(self._noise_fstart, 1, wx.EXPAND)
        self._noise_fstart_unit = wx.Choice(parent, choices=UNITS)
        self._noise_fstart_unit.SetSelection(0)
        grid.Add(self._noise_fstart_unit, 0)

        grid.Add(wx.StaticText(parent, label="Stop Frequency"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._noise_fstop = wx.TextCtrl(parent, value="1")
        grid.Add(self._noise_fstop, 1, wx.EXPAND)
        self._noise_fstop_unit = wx.Choice(parent, choices=UNITS)
        self._noise_fstop_unit.SetSelection(2)
        grid.Add(self._noise_fstop_unit, 0)

        grid.Add(wx.StaticText(parent, label="No. of Points"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._noise_points = wx.TextCtrl(parent, value="100")
        grid.Add(self._noise_points, 1, wx.EXPAND)
        grid.Add(wx.StaticText(parent, label=""), 0)

        bsz.Add(grid, 0, wx.EXPAND | wx.ALL, 6)
        return bsz
    


    def _make_tf_group(self, parent):
        box  = wx.StaticBox(parent, label="Transfer Function Analysis")
        bsz  = wx.StaticBoxSizer(box, wx.VERTICAL)
        grid = wx.FlexGridSizer(rows=0, cols=2, vgap=6, hgap=10)
        grid.AddGrowableCol(1)

        grid.Add(wx.StaticText(parent, label="Output Node (e.g. out)"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._tf_output = wx.TextCtrl(parent, value="out")
        grid.Add(self._tf_output, 1, wx.EXPAND)

        grid.Add(wx.StaticText(parent, label="Input Source (e.g. V1)"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._tf_source = wx.TextCtrl(parent, value="V1")
        grid.Add(self._tf_source, 1, wx.EXPAND)

        bsz.Add(grid, 0, wx.EXPAND | wx.ALL, 6)

        info = wx.StaticText(parent,
            label="Transfer Function gives: gain, input impedance, output impedance.\n"
                  "Example: output=out, source=V1 → tf v(out) V1")
        info.SetForegroundColour(wx.Colour(80, 80, 80))
        bsz.Add(info, 0, wx.ALL, 6)
        return bsz
    

    def _make_sens_group(self, parent):
        box  = wx.StaticBox(parent, label="Sensitivity Analysis")
        bsz  = wx.StaticBoxSizer(box, wx.VERTICAL)
        grid = wx.FlexGridSizer(rows=0, cols=2, vgap=6, hgap=10)
        grid.AddGrowableCol(1)

        grid.Add(wx.StaticText(parent, label="Output Variable (e.g. v(out))"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._sens_output = wx.TextCtrl(parent, value="v(out)")
        grid.Add(self._sens_output, 1, wx.EXPAND)

        bsz.Add(grid, 0, wx.EXPAND | wx.ALL, 6)

        info = wx.StaticText(parent,
            label="Sensitivity shows how much each component affects the output.\n"
                  "Example: output=v(net_r1_pad2) → sens v(net_r1_pad2)\n"
                  "Results show: which resistor/capacitor has the most impact.")
        info.SetForegroundColour(wx.Colour(80, 80, 80))
        bsz.Add(info, 0, wx.ALL, 6)
        return bsz

    def _on_analysis_checkbox(self, event):
        clicked = event.GetEventObject()
        for cb in (self._cb_ac, self._cb_dc, self._cb_tran, self._cb_noise, self._cb_tf, self._cb_sens):
            if cb is not clicked:
                cb.SetValue(False)
        clicked.SetValue(True)
        self._ac_panel.Show(clicked is self._cb_ac)
        self._dc_panel.Show(clicked is self._cb_dc)
        self._tran_panel.Show(clicked is self._cb_tran)
        self._noise_panel.Show(clicked is self._cb_noise)
        self._tf_panel.Show(clicked is self._cb_tf)
        self._sens_panel.Show(clicked is self._cb_sens)
        self._analysis_panel.Layout()
        self._analysis_panel.FitInside()

    # ══════════════════════════════════════════════════════════════
    # TAB 2 - SOURCE DETAILS
    # ══════════════════════════════════════════════════════════════

    def _build_source_tab(self):
        panel = wx.ScrolledWindow(self.nb)
        panel.SetScrollRate(0, 10)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sources = {ref: cd for ref, cd in self.components.items()
                   if ref[0].upper() in ('V', 'I')}

        if not sources:
            sizer.Add(wx.StaticText(panel,
                label="No voltage/current sources found in schematic."),
                0, wx.ALL, 15)
        else:
            for ref, cd in sorted(sources.items()):
                sizer.Add(self._make_source_group(panel, ref, cd),
                          0, wx.EXPAND | wx.ALL, 8)

        panel.SetSizer(sizer)
        self.nb.AddPage(panel, "Source Details")

    def _make_source_group(self, parent, ref, comp_data):
        value    = comp_data.get('value', '')
        sim_type = comp_data.get('sim_type', '').lower()
        stype    = self._detect_source_type(sim_type, value)
        self._source_types[ref] = stype

        box = wx.StaticBox(parent, label=f"{ref}  ({value})")
        bsz = wx.StaticBoxSizer(box, wx.VERTICAL)

        hdr = wx.BoxSizer(wx.HORIZONTAL)
        hdr.Add(wx.StaticText(parent, label="Source type:"),
                0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        type_choice = wx.Choice(
            parent, choices=["dc", "ac", "sine", "pulse", "pwl", "exp"])
        type_choice.SetStringSelection(stype)
        hdr.Add(type_choice, 0)
        bsz.Add(hdr, 0, wx.ALL, 6)

        param_panel = wx.Panel(parent)
        param_sizer = wx.BoxSizer(wx.VERTICAL)
        param_panel.SetSizer(param_sizer)
        bsz.Add(param_panel, 0, wx.EXPAND | wx.ALL, 4)

        self._build_source_params(param_panel, param_sizer, ref, stype, comp_data)

        def on_type_change(evt, pp=param_panel, ps=param_sizer,
                           r=ref, cd=comp_data):
            new_type = type_choice.GetStringSelection()
            self._source_types[r] = new_type
            self._build_source_params(pp, ps, r, new_type, cd)
            pp.Layout()
            parent.Layout()

        type_choice.Bind(wx.EVT_CHOICE, on_type_change)
        return bsz

    def _detect_source_type(self, sim_type, value):
        for t in ('sine', 'pulse', 'pwl', 'exp', 'ac', 'dc'):
            if t in sim_type or t in value.lower():
                return t
        return 'dc'

    def _build_source_params(self, panel, sizer, ref, stype, comp_data):
        sizer.Clear(True)
        self._source_widgets[ref] = {}
        kw = {}
        for p in comp_data.get('sim_params', '').split():
            if '=' in p:
                k, v = p.split('=', 1)
                kw[k.lower()] = v

        def _field(lbl, key, default):
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(wx.StaticText(panel, label=lbl, size=(210, -1)),
                    0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
            tc = wx.TextCtrl(panel, value=kw.get(key, default), size=(150, -1))
            row.Add(tc, 0)
            sizer.Add(row, 0, wx.ALL, 3)
            self._source_widgets[ref][key] = tc

        if stype == 'dc':
            _field("Value (Volts/Amps):",            'dc',    '0')
        elif stype == 'ac':
            _field("Amplitude (Volts/Amps):",        'ampl',  '1')
            _field("Phase Shift (degrees):",         'phase', '0')
        elif stype == 'sine':
            _field("Offset (Volts/Amps):",           'dc',    '0')
            _field("Amplitude (Volts/Amps):",        'ampl',  '1')
            _field("Frequency (Hz):",                'f',     '1k')
            _field("Delay Time (s):",                'td',    '0')
            _field("Damping Factor (1/s):",          'theta', '0')
        elif stype == 'pulse':
            _field("Initial Value (V/A):",           'v1',    '0')
            _field("Pulsed Value (V/A):",            'v2',    '5')
            _field("Delay Time (s):",                'td',    '0')
            _field("Rise Time (s):",                 'tr',    '1n')
            _field("Fall Time (s):",                 'tf',    '1n')
            _field("Pulse Width (s):",               'pw',    '5m')
            _field("Period (s):",                    'per',   '10m')
        elif stype == 'pwl':
            _field("PWL values (t1 v1 t2 v2 ...):", 'pwl',   '0 0 1m 1 2m 0')
        elif stype == 'exp':
            _field("Initial Value (V/A):",           'v1',    '0')
            _field("Pulsed Value (V/A):",            'v2',    '1')
            _field("Rise Delay Time (s):",           'td1',   '0')
            _field("Rise Time Constant (s):",        'tau1',  '1m')
            _field("Fall Delay Time (s):",           'td2',   '5m')
            _field("Fall Time Constant (s):",        'tau2',  '1m')
        panel.Layout()

    # ══════════════════════════════════════════════════════════════
    # TAB 3 - NGSPICE MODEL  (mirrors eSim's Model.py exactly)
    # ══════════════════════════════════════════════════════════════

    def _build_ngmodel_tab(self):
        panel = wx.ScrolledWindow(self.nb)
        panel.SetScrollRate(0, 10)
        sizer = wx.BoxSizer(wx.VERTICAL)

        u_comps = {ref: cd for ref, cd in self.components.items()
                   if ref[0].upper() == 'U'}

        if not u_comps:
            sizer.Add(wx.StaticText(panel,
                label="No Ngspice model components (U-prefix) found.\n"
                      "This tab is needed for analog/digital behavioral\n"
                      "models such as gain, comparator, adder, etc."),
                0, wx.ALL, 15)
        else:
            info = wx.StaticText(panel,
                label="Set parameters for each Ngspice behavioral model.\n"
                      "Values correspond to eSim's modelParamXML definitions.")
            info.SetForegroundColour(wx.Colour(80, 80, 80))
            sizer.Add(info, 0, wx.ALL, 8)

            for ref, cd in sorted(u_comps.items()):
                grp = self._make_ngmodel_group(panel, ref, cd)
                if grp:
                    sizer.Add(grp, 0, wx.EXPAND | wx.ALL, 6)

        panel.SetSizer(sizer)
        self.nb.AddPage(panel, "Ngspice Model")

    def _find_model_xml(self, model_type):
        """Search eSim modelParamXML subdirs for <model_type>.xml."""
        if not os.path.exists(self.MODEL_XML_DIR):
            return None, None
        for subdir in ('Analog', 'Digital', 'Hybrid', 'Nghdl', 'Ngveri'):
            xml_path = os.path.join(
                self.MODEL_XML_DIR, subdir, model_type + '.xml')
            if os.path.exists(xml_path):
                try:
                    return xml_path, _ET.parse(xml_path)
                except Exception:
                    return None, None
        return None, None

    def _parse_model_xml(self, tree):
        """
        Parse modelParamXML tree into list of param dicts.
        Each dict: {tag, label, default, vector}
        vector=0 means scalar; vector=N means N text fields.
        """
        params = []
        for param_node in tree.findall('param'):
            for item in param_node:
                params.append({
                    'tag':     item.tag,
                    'label':   item.text.strip() if item.text else item.tag,
                    'default': item.attrib.get('default', ''),
                    'vector':  int(item.attrib['vector'])
                               if 'vector' in item.attrib else 0,
                })
        return params

    def _make_ngmodel_group(self, parent, ref, comp_data):
        """Build one group-box per U-prefix component."""
        value = comp_data.get('value', '').lower()
        xml_path, tree = self._find_model_xml(value)

        if tree is None:
            box  = wx.StaticBox(parent,
                label=f"{ref}  ({value})  - model XML not found in eSim library")
            bsz  = wx.StaticBoxSizer(box, wx.VERTICAL)
            note = wx.StaticText(parent,
                label=f"No XML for '{value}' found in modelParamXML.\n"
                      "Component will use built-in/external model lookup.")
            note.SetForegroundColour(wx.Colour(150, 80, 0))
            bsz.Add(note, 0, wx.ALL, 6)
            return bsz

        title_node = tree.find('title')
        title_text = (title_node.text.strip()
                      if title_node is not None
                      else f"Add Parameters for {value} {ref}")

        params = self._parse_model_xml(tree)
        self._ngmodel_parsed[ref]  = {'model_type': value, 'params': params}
        self._ngmodel_widgets[ref] = {}

        box  = wx.StaticBox(parent, label=f"{title_text}  -  {ref}")
        bsz  = wx.StaticBoxSizer(box, wx.VERTICAL)
        grid = wx.FlexGridSizer(rows=0, cols=2, vgap=5, hgap=10)
        grid.AddGrowableCol(1)

        for p in params:
            tag, label, default, vector = (
                p['tag'], p['label'], p['default'], p['vector'])

            if vector > 0:
                # Vector param: create `vector` separate text controls
                # labelled "label 1", "label 2", ...
                for vi in range(1, vector + 1):
                    grid.Add(wx.StaticText(parent, label=f"{label} {vi}"),
                             0, wx.ALIGN_CENTER_VERTICAL)
                    tc = wx.TextCtrl(parent, value=default, size=(150, -1))
                    grid.Add(tc, 1, wx.EXPAND)
                    self._ngmodel_widgets[ref][f"{tag}_{vi}"] = tc
            else:
                grid.Add(wx.StaticText(parent, label=label),
                         0, wx.ALIGN_CENTER_VERTICAL)
                tc = wx.TextCtrl(parent, value=default, size=(150, -1))
                grid.Add(tc, 1, wx.EXPAND)
                self._ngmodel_widgets[ref][tag] = tc

        bsz.Add(grid, 0, wx.EXPAND | wx.ALL, 6)
        return bsz

    # ══════════════════════════════════════════════════════════════
    # TAB 4 - DEVICE MODELING
    # ══════════════════════════════════════════════════════════════

    def _build_device_tab(self):
        panel = wx.ScrolledWindow(self.nb)
        panel.SetScrollRate(0, 10)
        sizer = wx.BoxSizer(wx.VERTICAL)

        devices = {ref: cd for ref, cd in self.components.items()
                   if ref[0].upper() in ('Q', 'D', 'J', 'M', 'S')}

        if not devices:
            sizer.Add(wx.StaticText(panel,
                label="No active devices (Q/D/J/M/S) found in schematic.\n"
                      "Device Modeling tab is not needed."),
                0, wx.ALL, 15)
        else:
            info = wx.StaticText(panel,
                label="Select a .lib file for each active device.\n"
                      "Leave blank to use the built-in model library.")
            info.SetForegroundColour(wx.Colour(80, 80, 80))
            sizer.Add(info, 0, wx.ALL, 8)
            for ref, cd in sorted(devices.items()):
                sizer.Add(self._make_device_group(panel, ref, cd),
                          0, wx.EXPAND | wx.ALL, 6)

        panel.SetSizer(sizer)
        self.nb.AddPage(panel, "Device Modeling")

    def _make_device_group(self, parent, ref, comp_data):
        prefix = ref[0].upper()
        value  = comp_data.get('value', '')
        labels = {'Q': 'Transistor', 'D': 'Diode',
                  'J': 'JFET', 'M': 'MOSFET', 'S': 'Switch'}

        box = wx.StaticBox(
            parent,
            label=f"Add library for {labels.get(prefix,'Device')}  {ref} : {value}")
        bsz = wx.StaticBoxSizer(box, wx.VERTICAL)
        row = wx.BoxSizer(wx.HORIZONTAL)

        tc = wx.TextCtrl(parent, value="", style=wx.TE_READONLY, size=(360, -1))
        self._device_entry[ref] = tc
        row.Add(tc, 1, wx.EXPAND | wx.RIGHT, 6)
        add_btn = wx.Button(parent, label="Add")
        add_btn.Bind(wx.EVT_BUTTON, lambda evt, r=ref: self._pick_device_lib(r))
        row.Add(add_btn, 0)
        bsz.Add(row, 0, wx.EXPAND | wx.ALL, 6)

        # MOSFET dimension fields (mirrors eSim DeviceModel.py)
        if prefix == 'M':
            grid = wx.FlexGridSizer(rows=0, cols=2, vgap=4, hgap=8)
            grid.AddGrowableCol(1)
            for suffix, lbl, default in [
                ('_W', f"Width of MOSFET {ref} (default=100u):",     "100u"),
                ('_L', f"Length of MOSFET {ref} (default=100u):",    "100u"),
                ('_M', f"Mult. factor of MOSFET {ref} (default=1):", "1"),
            ]:
                grid.Add(wx.StaticText(parent, label=lbl),
                         0, wx.ALIGN_CENTER_VERTICAL)
                dim_tc = wx.TextCtrl(parent, value=default, size=(100, -1))
                self._device_entry[ref + suffix] = dim_tc
                grid.Add(dim_tc, 0)
            bsz.Add(grid, 0, wx.EXPAND | wx.ALL, 6)

        return bsz

    def _pick_device_lib(self, ref):
        dlg = wx.FileDialog(
            self, f"Select .lib file for {ref}",
            wildcard="SPICE Library (*.lib)|*.lib|All files|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self._device_entry[ref].SetValue(path)
            self._device_lib_paths[ref] = path
        dlg.Destroy()

    # ══════════════════════════════════════════════════════════════
    # TAB 5 - SUBCIRCUITS
    # ══════════════════════════════════════════════════════════════

    def _build_subcircuit_tab(self):
        panel = wx.ScrolledWindow(self.nb)
        panel.SetScrollRate(0, 10)
        sizer = wx.BoxSizer(wx.VERTICAL)

        subcircuits = {ref: cd for ref, cd in self.components.items()
                       if ref[0].upper() == 'X'}

        if not subcircuits:
            sizer.Add(wx.StaticText(panel,
                label="No subcircuit components (X-prefix) found.\n"
                      "Subcircuits tab is not needed."),
                0, wx.ALL, 15)
        else:
            info = wx.StaticText(panel,
                label="Select the subcircuit directory for each X-prefix "
                      "component.\nThe directory must contain a .sub file.")
            info.SetForegroundColour(wx.Colour(80, 80, 80))
            sizer.Add(info, 0, wx.ALL, 8)
            for ref, cd in sorted(subcircuits.items()):
                sizer.Add(self._make_subcircuit_group(panel, ref, cd),
                          0, wx.EXPAND | wx.ALL, 6)

        panel.SetSizer(sizer)
        self.nb.AddPage(panel, "Subcircuits")

    def _make_subcircuit_group(self, parent, ref, comp_data):
        value = comp_data.get('value', '')
        box   = wx.StaticBox(parent, label=f"Add subcircuit for  {ref} : {value}")
        bsz   = wx.StaticBoxSizer(box, wx.VERTICAL)
        row   = wx.BoxSizer(wx.HORIZONTAL)

        tc = wx.TextCtrl(parent, value="", style=wx.TE_READONLY, size=(360, -1))
        self._subckt_entry[ref] = tc
        row.Add(tc, 1, wx.EXPAND | wx.RIGHT, 6)
        add_btn = wx.Button(parent, label="Add")
        add_btn.Bind(wx.EVT_BUTTON,
                     lambda evt, r=ref: self._pick_subcircuit_dir(r))
        row.Add(add_btn, 0)
        bsz.Add(row, 0, wx.EXPAND | wx.ALL, 6)
        return bsz

    def _pick_subcircuit_dir(self, ref):
        dlg = wx.DirDialog(self, f"Select subcircuit directory for {ref}",
                           style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            sub_files = [f for f in os.listdir(path) if f.endswith('.sub')]
            if not sub_files:
                wx.MessageBox(
                    f"No .sub file found in:\n{path}\n\n"
                    "Please select a directory containing a .sub file.",
                    "Invalid Subcircuit Directory", wx.OK | wx.ICON_ERROR)
            else:
                self._subckt_entry[ref].SetValue(path)
                self._subcircuit_paths[ref] = path
        dlg.Destroy()

    # ══════════════════════════════════════════════════════════════
    # OK HANDLER
    # ══════════════════════════════════════════════════════════════

    def _on_ok(self, event):
        self._collect_analysis()
        self._collect_source_overrides()
        self._collect_ngmodel_lines()
        self._collect_device_libs()
        self._save_mcu_previous_values()   # ← ADD THIS LINE
        event.Skip()

    def _collect_analysis(self):
        if self._cb_ac.GetValue():
            self._analysis_type = 'ac'
            scale = ('dec' if self._ac_dec.GetValue() else
                     'lin' if self._ac_lin.GetValue() else 'oct')
            um = {'Hz': '', 'KHz': 'k', 'Meg': 'Meg', 'GHz': 'G', 'THz': 'T'}
            self._analysis_params = {
                'scale':  scale,
                'fstart': self._ac_fstart.GetValue() +
                          um.get(self._ac_fstart_unit.GetStringSelection(), ''),
                'fstop':  self._ac_fstop.GetValue() +
                          um.get(self._ac_fstop_unit.GetStringSelection(), ''),
                'points': self._ac_points.GetValue(),
            }
        elif self._cb_dc.GetValue():
            if self._dc_op_check.GetValue():
                self._analysis_type   = 'op'
                self._analysis_params = {}
            else:
                self._analysis_type = 'dc'
                um2 = {'Volts or Amperes': '', 'mV or mA': 'm',
                       'uV or uA': 'u',        'nV or nA': 'n',
                       'pV or pA': 'p'}
                def _u(ch): return um2.get(ch.GetStringSelection(), '')
                self._analysis_params = {
                    'source': self._dc_src1.GetValue() or 'V1',
                    'start':  self._dc_start1.GetValue() + _u(self._dc_start1_u),
                    'stop':   self._dc_stop1.GetValue()  + _u(self._dc_stop1_u),
                    'step':   self._dc_inc1.GetValue()   + _u(self._dc_inc1_u),
                }
                if self._dc_src2.GetValue().strip():
                    self._analysis_params.update({
                        'source2': self._dc_src2.GetValue(),
                        'start2':  self._dc_start2.GetValue() + _u(self._dc_start2_u),
                        'stop2':   self._dc_stop2.GetValue()  + _u(self._dc_stop2_u),
                        'step2':   self._dc_inc2.GetValue()   + _u(self._dc_inc2_u),
                    })



        elif self._cb_tf.GetValue():
            self._analysis_type = 'tf'
            self._analysis_params = {
                'output': self._tf_output.GetValue().strip() or 'out',
                'source': self._tf_source.GetValue().strip() or 'V1',
            }

        elif self._cb_sens.GetValue():
            self._analysis_type = 'sens'
            self._analysis_params = {
                'output': self._sens_output.GetValue().strip() or 'v(out)',
            }

        elif self._cb_noise.GetValue():
            self._analysis_type = 'noise'
            um = {'Hz': '', 'KHz': 'k', 'Meg': 'Meg', 'GHz': 'G'}
            self._analysis_params = {
                'output':  self._noise_output.GetValue().strip() or 'out',
                'source':  self._noise_source.GetValue().strip() or 'V1',
                'fstart':  self._noise_fstart.GetValue() +
                           um.get(self._noise_fstart_unit.GetStringSelection(), ''),
                'fstop':   self._noise_fstop.GetValue() +
                           um.get(self._noise_fstop_unit.GetStringSelection(), ''),
                'points':  self._noise_points.GetValue(),
            }

        else:  # TRAN default
            self._analysis_type = 'tran'
            um3 = {'sec': '', 'ms': 'm', 'us': 'u', 'ns': 'n', 'ps': 'p'}
            def _tu(ch): return um3.get(ch.GetStringSelection(), '')
            self._analysis_params = {
                'start': self._tran_start.GetValue() + _tu(self._tran_start_u),
                'step':  self._tran_step.GetValue()  + _tu(self._tran_step_u),
                'stop':  self._tran_stop.GetValue()  + _tu(self._tran_stop_u),
            }

    def _collect_source_overrides(self):
        for ref, widgets in self._source_widgets.items():
            stype = self._source_types.get(ref, 'dc')
            pins  = self.components[ref].get('pins', {})
            sp    = sorted(pins.keys(),
                           key=lambda x: int(x) if x.isdigit() else 0)
            nodes = [pins[p] for p in sp]
            while len(nodes) < 2:
                nodes.append('0')
            n0, n1 = nodes[0], nodes[1]

            def g(key, default='0'):
                tc = widgets.get(key)
                v  = tc.GetValue().strip() if tc else ''
                return v if v else default

            if stype == 'dc':
                line = f"{ref} {n0} {n1} DC {g('dc','0')}"
            elif stype == 'ac':
                line = f"{ref} {n0} {n1} AC {g('ampl','1')} {g('phase','0')}"
            elif stype == 'sine':
                line = (f"{ref} {n0} {n1} AC {g('ampl','1')} "
                        f"SIN({g('dc','0')} {g('ampl','1')} {g('f','1k')} "
                        f"{g('td','0')} {g('theta','0')})")
            elif stype == 'pulse':
                line = (f"{ref} {n0} {n1} "
                        f"PULSE({g('v1','0')} {g('v2','5')} {g('td','0')} "
                        f"{g('tr','1n')} {g('tf','1n')} "
                        f"{g('pw','5m')} {g('per','10m')})")
            elif stype == 'pwl':
                line = f"{ref} {n0} {n1} PWL({g('pwl','0 0')})"
            elif stype == 'exp':
                line = (f"{ref} {n0} {n1} "
                        f"EXP({g('v1','0')} {g('v2','1')} {g('td1','0')} "
                        f"{g('tau1','1m')} {g('td2','5m')} {g('tau2','1m')})")
            else:
                line = f"{ref} {n0} {n1} DC 0"
            self._source_overrides[ref] = line

    def _collect_ngmodel_lines(self):
        """
        Build .model lines from Ngspice Model tab widgets.
        Mirrors eSim's Convert.addModelParameter() logic exactly.
        """
        self._ngmodel_lines = []
        for ref, info in self._ngmodel_parsed.items():
            model_type = info['model_type']
            params     = info['params']
            widgets    = self._ngmodel_widgets.get(ref, {})

            model_line = f".model {ref} {model_type}("

            for p in params:
                tag, default, vector = p['tag'], p['default'], p['vector']
                if vector > 0:
                    model_line += f"{tag}=["
                    for vi in range(1, vector + 1):
                        tc  = widgets.get(f"{tag}_{vi}")
                        val = tc.GetValue().strip() if tc else ''
                        model_line += (val if val else default) + " "
                    model_line += "] "
                else:
                    tc  = widgets.get(tag)
                    val = tc.GetValue().strip() if tc else ''
                    model_line += f"{tag}={(val if val else default)} "

            model_line += ")"
            self._ngmodel_lines.append(
                f"* Schematic Name: {model_type}, Ngspice Name: {ref}")
            self._ngmodel_lines.append(model_line)

    def _collect_device_libs(self):
        for ref, tc in self._device_entry.items():
            if any(ref.endswith(s) for s in ('_W', '_L', '_M')):
                continue
            path = tc.GetValue().strip()
            if path:
                self._device_lib_paths[ref] = path

    # ══════════════════════════════════════════════════════════════
    # PUBLIC GETTERS
    # ══════════════════════════════════════════════════════════════

    def get_analysis_type(self):    return self._analysis_type
    def get_analysis_params(self):  return self._analysis_params
    def get_source_overrides(self): return self._source_overrides
    def get_ngmodel_lines(self):    return self._ngmodel_lines
    def get_device_lib_paths(self): return self._device_lib_paths
    def get_subcircuit_paths(self): return self._subcircuit_paths

    def get_mosfet_dimensions(self, ref):
        """Returns (width, length, multifactor) strings for a MOSFET ref."""
        w = self._device_entry.get(ref + '_W')
        l = self._device_entry.get(ref + '_L')
        m = self._device_entry.get(ref + '_M')
        return (
            w.GetValue() if w else '100u',
            l.GetValue() if l else '100u',
            m.GetValue() if m else '1',
        )


# ══════════════════════════════════════════════════════════════════════
# NEW RUN FLOW  -  paste into Run() replacing old Steps 1 & 2
# ══════════════════════════════════════════════════════════════════════
#
# DELETE this old block from Run():
#   dialog = AnalysisConfigDialog(None)
#   if dialog.ShowModal() != wx.ID_OK: ...
#   analysis_type   = dialog.get_analysis_type()
#   analysis_params = dialog.get_analysis_params()
#   dialog.Destroy()
#   schematic_path = self.get_schematic_path()   <- also delete this
#
# REPLACE WITH:
#
#   # Step 1: Get schematic path
#   schematic_path = self.get_schematic_path()
#   if not schematic_path:
#       wx.MessageBox("No schematic found.\nPlease open a schematic first.",
#                     "eSim Bridge", wx.OK | wx.ICON_ERROR)
#       return
#
#   # Step 2: Export netlist silently
#   netlist_xml_path = "/tmp/esim_bridge_netlist.net"
#   if not self.export_netlist(schematic_path, netlist_xml_path):
#       wx.MessageBox("Failed to export netlist.\n"
#                     "Make sure kicad-cli is available.",
#                     "eSim Bridge Error", wx.OK | wx.ICON_ERROR)
#       return
#
#   # Step 3: Parse netlist to populate dialog tabs
#   converter = SPICEConverter()
#   components_pre, _ = converter.parse_full_netlist(netlist_xml_path)
#
#   # Step 4: Show the tabbed KicadToNgspice dialog
#   ktn_dlg = KicadToNgspiceDialog(None, components_pre)
#   if ktn_dlg.ShowModal() != wx.ID_OK:
#       ktn_dlg.Destroy()
#       return
#
#   analysis_type    = ktn_dlg.get_analysis_type()
#   analysis_params  = ktn_dlg.get_analysis_params()
#   source_overrides = ktn_dlg.get_source_overrides()
#   ngmodel_lines    = ktn_dlg.get_ngmodel_lines()
#   device_lib_paths = ktn_dlg.get_device_lib_paths()
#   subcircuit_paths = ktn_dlg.get_subcircuit_paths()
#   ktn_dlg.Destroy()
#
#   # Step 5: Run preflight checks (keep existing code from here)
#   # Also inject ngmodel_lines into SPICE file after conversion:
#   #   if ngmodel_lines:
#   #       with open(spice_output_path, 'r') as f: content = f.read()
#   #       inject = '\n* -- Ngspice Model Tab --\n' + '\n'.join(ngmodel_lines)
#   #       content = content.replace('\n.end', inject + '\n.end')
#   #       with open(spice_output_path, 'w') as f: f.write(content)


# ══════════════════════════════════════════════════════════════════════
# ESIM LAUNCHER
# ══════════════════════════════════════════════════════════════════════

class ESimLauncher:
    """Finds and launches eSim with a pre-loaded netlist."""
    
    ESIM_SCRIPT = os.path.expanduser(
        '~/Downloads/eSim-2.5/src/frontEnd/Application.py')
    ESIM_PYTHON = os.path.expanduser('~/.esim/env/bin/python3')
    ESIM_SRC    = os.path.expanduser('~/Downloads/eSim-2.5/src')
    ESIM_DIR    = os.path.expanduser('~/Downloads/eSim-2.5/src/frontEnd')

    def find_esim(self):
        return (
            os.path.exists(self.ESIM_SCRIPT) and
            os.path.exists(self.ESIM_PYTHON)
        )

    def launch(self, netlist_path):
        import time

        if not self.find_esim():
            return False, (
                "eSim not found.\n\n"
                "Expected at:\n"
                f"{self.ESIM_SCRIPT}\n\n"
                "Please install eSim 2.5 from:\n"
                "https://static.fossee.in/esim/installation-files/eSim-2.5.zip\n\n"
                f"Your SPICE file has been saved to:\n{netlist_path}\n"
                "You can open it manually once eSim is installed."
            )

        home_netlist = os.path.expanduser('~/esim_bridge_simulation.cir')
        try:
            shutil.copy2(netlist_path, home_netlist)
        except Exception:
            home_netlist = netlist_path

        try:
            env = os.environ.copy()
            env['PYTHONPATH'] = self.ESIM_SRC

            cmd = [self.ESIM_PYTHON, 'Application.py']
            process = subprocess.Popen(
                cmd, cwd=self.ESIM_DIR, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )

            time.sleep(3)

            if process.poll() is None:
                return True, (
                    f"eSim launched successfully!\n"
                    f"PID: {process.pid}\n\n"
                    f"Your SPICE file is at:\n{home_netlist}"
                )
            else:
                stdout, stderr = process.communicate()
                return False, f"eSim failed to start.\n\nError:\n{stderr.decode()[:500]}"

        except FileNotFoundError:
            return False, f"Could not find Python:\n{self.ESIM_PYTHON}"
        except Exception as e:
            return False, f"Unexpected error:\n{str(e)}"


# ══════════════════════════════════════════════════════════════════════
# PREFLIGHT CHECKER
# ══════════════════════════════════════════════════════════════════════

class PreflightChecker:
    """Checks everything is ready before attempting simulation."""
    
    def run_all_checks(self, schematic_path):
        results = []
        
        if not os.path.exists(schematic_path):
            results.append(('error', 
                f"Schematic file not found:\n{schematic_path}"))
            return results
        
        results.append(('ok', f"Schematic found: {schematic_path}"))
        
        try:
            result = subprocess.run(
                ['kicad-cli', '--version'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                results.append(('ok', 
                    f"kicad-cli available: {result.stdout.strip()}"))
            else:
                results.append(('error', "kicad-cli not working correctly"))
        except FileNotFoundError:
            results.append(('error', 
                "kicad-cli not found. Is KiCad installed correctly?"))
        
        launcher = ESimLauncher()
        esim_path = launcher.find_esim()
        if esim_path:
            results.append(('ok', f"eSim found: {esim_path}"))
        else:
            results.append(('warning', 
                "eSim not found. SPICE file will be saved but eSim "
                "won't auto-launch."))
        
        try:
            test_file = '/tmp/esim_bridge_test.tmp'
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            results.append(('ok', "Write access to /tmp confirmed"))
        except:
            results.append(('error', "Cannot write to /tmp directory."))
        

        # ── .spiceinit auto-writer ──
        spiceinit_path = os.path.expanduser('~/.spiceinit')
        spiceinit_needed_line = 'set ngbehavior=ps'
        
        try:
            if os.path.exists(spiceinit_path):
                with open(spiceinit_path, 'r') as f:
                    content = f.read()
                if spiceinit_needed_line in content:
                    results.append(('ok', ".spiceinit already configured for PSPICE compatibility"))
                else:
                    with open(spiceinit_path, 'a') as f:
                        f.write(f'\n* Added by eSim-BRIDGE\n{spiceinit_needed_line}\n')
                    results.append(('ok', ".spiceinit updated: added ngbehavior=ps for PSPICE model compatibility"))
            else:
                with open(spiceinit_path, 'w') as f:
                    f.write(f'* eSim-BRIDGE auto-generated spiceinit\n{spiceinit_needed_line}\n')
                results.append(('ok', ".spiceinit created with ngbehavior=ps for PSPICE model compatibility"))
        except Exception as e:
            results.append(('warning', f"Could not write .spiceinit: {e}"))
        
        return results

    def run_netlist_checks(self, components, nets):
        """Wrapper that formats netlist check results same as run_all_checks."""
        return self.check_netlist(components, nets)
    




    def check_netlist(self, components, nets):
        """
        Check parsed netlist for common simulation-killing problems.
        Returns list of (severity, message) tuples.
        """
        issues = []

        # ── Check 1: Ground node exists ──
        has_ground = any(
            data['spice_name'] == '0'
            for data in nets.values()
        )
        if not has_ground:
            issues.append(('error',
                "No GND node found. Every circuit needs a ground reference (GND/0). "
                "Add a PWR_FLAG or GND symbol connected to your ground net."))
        else:
            issues.append(('ok', "Ground node (GND/0) present"))

        # ── Check 2: Build connection count per SPICE net ──
        # Count how many component pins connect to each net
        net_pin_count = {}   # {spice_net_name: count}
        net_pin_refs  = {}   # {spice_net_name: [ref, ...]} for error messages

        for net_name, net_data in nets.items():
            spice_name = net_data['spice_name']
            nodes      = net_data.get('nodes', [])
            net_pin_count[spice_name] = net_pin_count.get(spice_name, 0) + len(nodes)
            if spice_name not in net_pin_refs:
                net_pin_refs[spice_name] = []
            for ref, pin in nodes:
                net_pin_refs[spice_name].append(f"{ref}.{pin}")

        # ── Check 3: Floating nodes (connected to only 1 pin) ──
        floating = []
        for spice_net, count in net_pin_count.items():
            if spice_net == '0':
                continue   # GND is always fine
            if count == 1:
                refs = ', '.join(net_pin_refs[spice_net][:3])
                floating.append(f"  Net '{spice_net}' → only pin: {refs}")

        if floating:
            issues.append(('error',
                "Floating node(s) detected — ngspice will fail with 'singular matrix':\n"
                + '\n'.join(floating)
                + "\n  Fix: connect these pins to another component or add a large pull-down resistor."))
        else:
            issues.append(('ok', "No floating nodes detected"))

        # ── Check 4: Voltage source short circuit ──
        # Two voltage sources sharing both nodes = dead short
        vsource_nodes = {}  # {frozenset(node_a, node_b): ref}
        for ref, comp_data in components.items():
            if ref[0].upper() != 'V' and not ref.upper().startswith('BT'):
                continue
            pins = comp_data.get('pins', {})
            sorted_pins = sorted(pins.keys(),
                                key=lambda x: int(x) if x.isdigit() else 0)
            node_list = [pins[p] for p in sorted_pins]
            if len(node_list) >= 2:
                pair = frozenset([node_list[0], node_list[1]])
                if pair in vsource_nodes:
                    other_ref = vsource_nodes[pair]
                    issues.append(('error',
                        f"Voltage source short: {ref} and {other_ref} share "
                        f"both terminals ({node_list[0]}, {node_list[1]}). "
                        "ngspice cannot solve this — remove one or add a series resistor."))
                else:
                    vsource_nodes[pair] = ref

        if not any(s == 'error' and 'Voltage source short' in m
                for s, m in issues):
            issues.append(('ok', "No voltage source conflicts detected"))

        # ── Check 5: Components with no connections at all ──
        orphans = []
        for ref, comp_data in components.items():
            prefix = ref[0].upper()
            if prefix in ('R', 'C', 'L', 'V', 'I', 'D', 'Q', 'M', 'J', 'U', 'X'):
                pins = comp_data.get('pins', {})
                if not pins:
                    orphans.append(ref)

    
        if orphans:
            issues.append(('warning',
                f"Components with no net connections: {', '.join(orphans)}. "
                "These will be ignored by ngspice but may indicate a wiring error."))
        else:
            issues.append(('ok', "All components have at least one connection"))

        # ── Check 6: DC path violations (capacitor-only paths) ──
        cap_only_nets = []
        for net_name, net_data in nets.items():
            spice_name = net_data['spice_name']
            if spice_name == '0':
                continue
            nodes = net_data.get('nodes', [])
            refs_on_net = [ref for ref, pin in nodes]
            if len(refs_on_net) < 2:
                continue
            all_caps = all(
                ref[0].upper() == 'C'
                for ref in refs_on_net
            )
            if all_caps:
                cap_only_nets.append(spice_name)

        if cap_only_nets:
            issues.append(('warning',
                f"DC path violation — net(s) connected only through capacitors: "
                f"{', '.join(cap_only_nets)}. "
                "Add a resistor to ground or ngspice may fail with singular matrix."))
        else:
            issues.append(('ok', "No DC path violations detected"))

        return issues
    
    def show_results_dialog(self, results):
        errors = [r for r in results if r[0] == 'error']
        warnings = [r for r in results if r[0] == 'warning']
        oks = [r for r in results if r[0] == 'ok']
        
        if not errors and not warnings:
            return True
        
        message = ""
        
        if errors:
            message += "ERRORS (must fix before simulating):\n"
            for _, msg in errors:
                message += f"  ✗ {msg}\n"
            message += "\n"
        
        if warnings:
            message += "WARNINGS (simulation may still work):\n"
            for _, msg in warnings:
                message += f"  ⚠ {msg}\n"
            message += "\n"
        
        if oks:
            message += "OK:\n"
            for _, msg in oks:
                message += f"  ✓ {msg}\n"
        
        if errors:
            wx.MessageBox(message, "eSim Bridge - Preflight Check Failed",
                wx.OK | wx.ICON_ERROR)
            return False
        else:
            result = wx.MessageBox(
                message + "\nContinue anyway?",
                "eSim Bridge - Preflight Warnings",
                wx.YES_NO | wx.ICON_WARNING)
            return result == wx.YES








# ══════════════════════════════════════════════════════════════════════
# NGSPICE WAVEFORM VIEWER
# Drop-in replacement for the text-only ngspice output dialog.
#
# HOW TO INTEGRATE INTO esim_bridge.py:
#   1. Paste this entire block ABOVE the SimulationReadyDialog class
#   2. Replace the _on_run_ngspice method inside SimulationReadyDialog
#      with the NEW version at the bottom of this file
#   3. Add   import struct   near the top imports of esim_bridge.py
# ══════════════════════════════════════════════════════════════════════


# ── Raw file parser ────────────────────────────────────────────────────

class NgspiceRawParser:
    """
    Parses ngspice .raw files (both ASCII and binary real/complex).
    Returns a dict:
      {
        'title':    str,
        'type':     str,   # 'transient', 'ac', etc.
        'vars':     [{'name': str, 'unit': str}],
        'data':     {var_name: [float, ...]},   # real part only for AC
      }
    """

    def parse(self, raw_path):
        with open(raw_path, 'rb') as f:
            raw_bytes = f.read()

        # Try to detect ASCII vs binary
        # ngspice binary files have 'Binary:' header
        try:
            header_text = raw_bytes[:4096].decode('utf-8', errors='replace')
        except Exception:
            header_text = ''

        if 'Binary:' in header_text:
            return self._parse_binary(raw_bytes, header_text)
        else:
            return self._parse_ascii(raw_bytes.decode('utf-8', errors='replace'))

    # ── ASCII parser ───────────────────────────────────────────────

    def _parse_ascii(self, text):
        result = {'title': '', 'type': '', 'vars': [], 'data': {}}
        lines = text.splitlines()
        i = 0
        num_vars = 0
        num_points = 0

        while i < len(lines):
            line = lines[i]

            if line.startswith('Title:'):
                result['title'] = line[6:].strip()
            elif line.startswith('Plotname:'):
                result['type'] = line[9:].strip().lower()
            elif line.startswith('No. Variables:'):
                num_vars = int(line.split(':')[1].strip())
            elif line.startswith('No. Points:'):
                num_points = int(line.split(':')[1].strip())
            elif line.startswith('Variables:'):
                i += 1
                for _ in range(num_vars):
                    if i < len(lines):
                        parts = lines[i].split()
                        if len(parts) >= 3:
                            result['vars'].append({
                                'name': parts[1],
                                'unit': parts[2]
                            })
                            result['data'][parts[1]] = []
                        i += 1
                continue
            elif line.startswith('Values:'):
                i += 1
                # Each data point block: index\tval0\n\t\tval1\n ...
                var_idx = 0
                point_idx = 0
                while i < len(lines) and point_idx < num_points:
                    line = lines[i]
                    stripped = line.strip()
                    if not stripped:
                        i += 1
                        continue
                    parts = stripped.split()
                    # First line of a point has the index prepended
                    if len(parts) == 2 and var_idx == 0:
                        val_str = parts[1]
                    elif len(parts) == 1:
                        val_str = parts[0]
                    else:
                        val_str = parts[-1]
                    try:
                        val = float(val_str.replace(',', '.'))
                        var_name = result['vars'][var_idx]['name']
                        result['data'][var_name].append(val)
                    except (ValueError, IndexError):
                        pass
                    var_idx += 1
                    if var_idx >= num_vars:
                        var_idx = 0
                        point_idx += 1
                    i += 1
                continue
            i += 1

        return result

    # ── Binary parser ──────────────────────────────────────────────

    def _parse_binary(self, raw_bytes, header_text):
        result = {'title': '', 'type': '', 'vars': [], 'data': {}}

        # Parse text header
        lines = header_text.splitlines()
        num_vars = 0
        num_points = 0
        binary_start = 0

        for idx, line in enumerate(lines):
            if line.startswith('Title:'):
                result['title'] = line[6:].strip()
            elif line.startswith('Plotname:'):
                result['type'] = line[9:].strip().lower()
            elif line.startswith('No. Variables:'):
                num_vars = int(line.split(':')[1].strip())
            elif line.startswith('No. Points:'):
                num_points = int(line.split(':')[1].strip())
            elif line.startswith('Variables:'):
                for j in range(1, num_vars + 1):
                    if idx + j < len(lines):
                        parts = lines[idx + j].split()
                        if len(parts) >= 3:
                            result['vars'].append({
                                'name': parts[1],
                                'unit': parts[2]
                            })
                            result['data'][parts[1]] = []
            elif line.startswith('Binary:'):
                # Find byte offset of 'Binary:\n' in raw_bytes
                binary_tag = b'Binary:\n'
                offset = raw_bytes.find(binary_tag)
                if offset != -1:
                    binary_start = offset + len(binary_tag)
                break

        if not result['vars'] or binary_start == 0:
            return result

        data_bytes = raw_bytes[binary_start:]

        # ngspice stores doubles (8 bytes each), row-major:
        # for each point: var0_val, var1_val, ..., varN-1_val
        bytes_per_point = num_vars * 8
        is_complex = 'ac' in result['type']

        for pt in range(num_points):
            offset = pt * bytes_per_point * (2 if is_complex else 1)
            for vi, var in enumerate(result['vars']):
                byte_off = offset + vi * 8 * (2 if is_complex else 1)
                chunk = data_bytes[byte_off: byte_off + 8]
                if len(chunk) < 8:
                    break
                val = struct.unpack('d', chunk)[0]
                result['data'][var['name']].append(val)

        return result


# ── Waveform viewer dialog ──────────────────────────────────────────────

class NgspiceWaveformViewer(wx.Dialog):
    """
    Embeds a matplotlib figure inside a wx.Dialog.
    Displays all voltage/current waveforms from an ngspice .raw file.
    Matches the oscilloscope-style look: dark background, coloured traces,
    grid, legend — just like the ngspice standalone plotter.
    """

    # Dark oscilloscope colour palette (cycles through traces)
    TRACE_COLOURS = [
        '#FF4444',  # red
        '#4488FF',  # blue
        '#44FF88',  # green
        '#FFD700',  # gold
        '#FF88FF',  # magenta
        '#44FFFF',  # cyan
        '#FF8844',  # orange
        '#AAAAFF',  # lavender
    ]

    def __init__(self, parent, raw_path, analysis_type='tran', cir_path='', ngspice_output=''):
        self._ngspice_output = ngspice_output
        super().__init__(
            parent,
            title="ngspice Waveform Viewer  –  eSim Bridge",
            size=(900, 600),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX
        )
        self._raw_path     = raw_path
        self._analysis_type = analysis_type
        self._cir_path     = cir_path
        self._parsed       = None
        self._hidden_vars  = set()   # names toggled off

        self._build_ui()
        self._load_and_plot()
        if ngspice_output:
            self.set_stats_text(self._build_stats_text(ngspice_output))
        self.Centre()

    # ── UI skeleton ────────────────────────────────────────────────

    def _build_ui(self):
        from matplotlib.figure import Figure
        try:
            from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas
            from matplotlib.backends.backend_wxagg import NavigationToolbar2WxAgg as NavToolbar
        except ImportError:
            from matplotlib.backends.backend_wx import FigureCanvasWx as FigureCanvas
            from matplotlib.backends.backend_wx import NavigationToolbar2Wx as NavToolbar

        main = wx.BoxSizer(wx.VERTICAL)

        # ── Top info bar ──
        info_row = wx.BoxSizer(wx.HORIZONTAL)
        self._lbl_info = wx.StaticText(self, label="Loading…")
        self._lbl_info.SetFont(wx.Font(9, wx.FONTFAMILY_TELETYPE,
                                       wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        info_row.Add(self._lbl_info, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)

        refresh_btn = wx.Button(self, label="⟳ Refresh", size=(80, -1))
        refresh_btn.Bind(wx.EVT_BUTTON, lambda e: self._load_and_plot())
        info_row.Add(refresh_btn, 0, wx.RIGHT | wx.TOP | wx.BOTTOM, 4)

        save_btn = wx.Button(self, label="💾 Save PNG", size=(90, -1))
        save_btn.Bind(wx.EVT_BUTTON, self._on_save_png)
        info_row.Add(save_btn, 0, wx.RIGHT | wx.TOP | wx.BOTTOM, 4)

        self._fft_btn = wx.Button(self, label="📊 Show FFT", size=(150, -1))
        self._fft_btn.Bind(wx.EVT_BUTTON, self._on_show_fft)
        # Only show FFT button for transient analysis
        self._fft_btn.Show(self._analysis_type == 'tran')
        info_row.Add(self._fft_btn, 0, wx.RIGHT | wx.TOP | wx.BOTTOM, 4)

        self._meas_btn = wx.Button(self, label="📏 Measure", size=(100, -1))
        self._meas_btn.Bind(wx.EVT_BUTTON, self._on_measure)
        self._meas_btn.Show(self._analysis_type == 'tran')
        info_row.Add(self._meas_btn, 0, wx.RIGHT | wx.TOP | wx.BOTTOM, 4)

        self._bode_btn = wx.Button(self, label="📈 Bode Plot", size=(110, -1))
        self._bode_btn.Bind(wx.EVT_BUTTON, self._on_show_bode)
        self._bode_btn.Show(self._analysis_type == 'ac')
        info_row.Add(self._bode_btn, 0, wx.RIGHT | wx.TOP | wx.BOTTOM, 4)

        self._cursor_btn = wx.Button(self, label="🖱 Cursor", size=(90, -1))
        self._cursor_btn.Bind(wx.EVT_BUTTON, self._on_toggle_cursor)
        self._cursor_active = False
        self._cursor_annotation = None
        self._cursor_cid = None
        info_row.Add(self._cursor_btn, 0, wx.RIGHT | wx.TOP | wx.BOTTOM, 4)

        self._sweep_btn = wx.Button(self, label="🔁 Sweep", size=(90, -1))
        self._sweep_btn.Bind(wx.EVT_BUTTON, self._on_param_sweep)
        self._sweep_btn.Show(self._analysis_type == 'tran')
        info_row.Add(self._sweep_btn, 0, wx.RIGHT | wx.TOP | wx.BOTTOM, 4)

        main.Add(info_row, 0, wx.EXPAND)

        # ── Splitter: canvas left, trace toggles right ──
        splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)

        # Left: matplotlib canvas
        canvas_panel = wx.Panel(splitter)
        canvas_sizer = wx.BoxSizer(wx.VERTICAL)

        self._fig = Figure(facecolor='#1a1a2e')
        self._ax  = self._fig.add_subplot(111)
        self._canvas = FigureCanvas(canvas_panel, -1, self._fig)
        self._toolbar = NavToolbar(self._canvas)
        self._toolbar.DeleteToolByPos(6)
        self._toolbar.Realize()

        canvas_sizer.Add(self._toolbar, 0, wx.EXPAND)
        canvas_sizer.Add(self._canvas, 1, wx.EXPAND)
        canvas_panel.SetSizer(canvas_sizer)

        # Right: trace checkboxes
        toggle_panel = wx.ScrolledWindow(splitter)
        toggle_panel.SetScrollRate(0, 10)
        self._toggle_sizer = wx.BoxSizer(wx.VERTICAL)
        self._toggle_sizer.Add(
            wx.StaticText(toggle_panel, label="Traces"), 0, wx.ALL, 6)
        toggle_panel.SetSizer(self._toggle_sizer)
        self._toggle_panel = toggle_panel

        splitter.SplitVertically(canvas_panel, toggle_panel, sashPosition=-160)
        splitter.SetMinimumPaneSize(100)
        main.Add(splitter, 1, wx.EXPAND | wx.ALL, 4)



        # ── Stats text panel ──
        self._stats_ctrl = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
            size=(-1, 160))
        self._stats_ctrl.SetFont(wx.Font(10, wx.FONTFAMILY_TELETYPE,
                                          wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self._stats_ctrl.SetBackgroundColour(wx.Colour(15, 15, 30))
        self._stats_ctrl.SetForegroundColour(wx.Colour(180, 220, 180))
        main.Add(self._stats_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        # ── Bottom buttons ──
        btn_row = wx.StdDialogButtonSizer()
        close_btn = wx.Button(self, wx.ID_OK, "Close")
        close_btn.SetDefault()
        btn_row.AddButton(close_btn)
        btn_row.Realize()
        main.Add(btn_row, 0, wx.ALL | wx.ALIGN_RIGHT, 6)

        self.SetSizer(main)

    # ── Data loading & plotting ────────────────────────────────────

    def _load_and_plot(self):
        if not os.path.exists(self._raw_path):
            self._lbl_info.SetLabel(f"Raw file not found: {self._raw_path}")
            return

        try:
            parser = NgspiceRawParser()
            self._parsed = parser.parse(self._raw_path)
        except Exception as e:
            self._lbl_info.SetLabel(f"Parse error: {e}")
            return

        vars_list = self._parsed.get('vars', [])
        if not vars_list:
            self._lbl_info.SetLabel("No variables found in .raw file.")
            return

        # Rebuild trace toggles
        self._rebuild_toggles(vars_list)
        self._draw_plot()

    def _rebuild_toggles(self, vars_list):
        # Clear old checkboxes
        self._toggle_sizer.Clear(True)
        self._toggle_sizer.Add(
            wx.StaticText(self._toggle_panel, label="Traces"), 0, wx.ALL, 6)

        self._trace_checks = {}
        for i, var in enumerate(vars_list):
            name = var['name']
            if name.lower() in ('time', 'frequency'):
                continue
            colour = self.TRACE_COLOURS[i % len(self.TRACE_COLOURS)]
            cb = wx.CheckBox(self._toggle_panel, label=name)
            cb.SetValue(name not in self._hidden_vars)
            cb.SetForegroundColour(wx.Colour(
                int(colour[1:3], 16),
                int(colour[3:5], 16),
                int(colour[5:7], 16)
            ))
            cb.Bind(wx.EVT_CHECKBOX,
                    lambda evt, n=name: self._on_toggle(n, evt))
            self._toggle_sizer.Add(cb, 0, wx.LEFT | wx.BOTTOM, 6)
            self._trace_checks[name] = cb

        self._toggle_panel.Layout()
        self._toggle_panel.FitInside()

    def _on_toggle(self, name, evt):
        if evt.IsChecked():
            self._hidden_vars.discard(name)
        else:
            self._hidden_vars.add(name)
        self._draw_plot()

    def _draw_plot(self):
        if not self._parsed:
            return

        ax  = self._ax
        ax.clear()

        # Dark oscilloscope style
        ax.set_facecolor('#0d0d1a')
        self._fig.patch.set_facecolor('#1a1a2e')
        ax.tick_params(colors='white', labelsize=8)
        ax.spines[:].set_color('#444466')
        ax.grid(True, color='white', linestyle='dotted', linewidth=0.6, alpha=0.4)
        ax.yaxis.label.set_color('white')
        ax.xaxis.label.set_color('white')
        ax.title.set_color('white')

        data    = self._parsed['data']
        vars_   = self._parsed['vars']
        title   = self._parsed.get('title', '')
        ptype   = self._parsed.get('type', self._analysis_type)

        # X axis variable
        x_var = None
        if 'time' in data:
            x_var = 'time'
            x_label = 'Time (s)'
        elif 'frequency' in data:
            x_var = 'frequency'
            x_label = 'Frequency (Hz)'
        else:
            x_label = 'Sample'

        x_data = data.get(x_var, []) if x_var else []

        trace_count = 0
        for i, var in enumerate(vars_):
            name = var['name']
            if name == x_var:
                continue
            if name in self._hidden_vars:
                continue

            y_data = data.get(name, [])
            if not y_data:
                continue

            colour = self.TRACE_COLOURS[i % len(self.TRACE_COLOURS)]

            if x_data and len(x_data) == len(y_data):
                ax.plot(x_data, y_data, color=colour,
                        linewidth=1.4, label=f"v({name})" if 'v' not in name.lower() else name)
            else:
                ax.plot(y_data, color=colour,
                        linewidth=1.4, label=name)
            trace_count += 1
        

        ax.set_xlabel(x_label, color='white', fontsize=9)
        ax.set_ylabel('Voltage (V) / Current (A)', color='white', fontsize=9)
        ax.set_title(
            title or f"ngspice – {ptype.upper()} Analysis",
            color='white', fontsize=10, pad=8)

        if trace_count > 0:
            legend = ax.legend(
                loc='upper right', fontsize=8,
                facecolor='#1a1a2e', edgecolor='#444466',
                labelcolor='#ccccff', framealpha=0.8)

        if trace_count == 0:
            ax.text(0.5, 0.5, 'No traces selected',
                    transform=ax.transAxes,
                    ha='center', va='center',
                    color='#888899', fontsize=12)

        self._fig.subplots_adjust(left=0.12, bottom=0.12, right=0.97, top=0.92)
        self._canvas.draw()

        # Update info label
        pts = len(list(data.values())[0]) if data else 0
        n_traces = sum(1 for v in vars_ if v['name'] not in (x_var,))
        self._lbl_info.SetLabel(
            f"Raw: {os.path.basename(self._raw_path)}   "
            f"| {n_traces} traces | {pts} points | "
            f"{ptype.upper()}"
        )

    def _on_save_png(self, event):
        dlg = wx.FileDialog(
            self, "Save waveform as PNG",
            wildcard="PNG Image (*.png)|*.png",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            defaultFile="ngspice_waveform.png"
        )
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self._fig.savefig(path, dpi=150, bbox_inches='tight',
                              facecolor=self._fig.get_facecolor())
            wx.MessageBox(f"Saved to:\n{path}", "Saved", wx.OK | wx.ICON_INFORMATION)
        dlg.Destroy()


    def _on_show_fft(self, event):
        """Compute and display FFT of visible transient traces."""
        import numpy as np

        if not self._parsed or not self._parsed.get('data'):
            wx.MessageBox("No data to compute FFT.", "FFT", wx.OK | wx.ICON_WARNING)
            return

        data  = self._parsed['data']
        vars_ = self._parsed['vars']

        time_data = data.get('time', [])
        if not time_data or len(time_data) < 4:
            wx.MessageBox("Not enough time-domain data for FFT.\nRun a transient simulation first.",
                          "FFT", wx.OK | wx.ICON_WARNING)
            return

        # Compute sample rate from time vector
        dt = (time_data[-1] - time_data[0]) / (len(time_data) - 1)
        fs = 1.0 / dt
        freqs = np.fft.rfftfreq(len(time_data), d=dt)

        # Switch axes to FFT mode
        ax = self._ax
        ax.clear()
        ax.set_facecolor('#0d0d1a')
        self._fig.patch.set_facecolor('#1a1a2e')
        ax.tick_params(colors='white', labelsize=8)
        ax.spines[:].set_color('#444466')
        ax.grid(True, color='white', linestyle='dotted', linewidth=0.6, alpha=0.4)
        ax.yaxis.label.set_color('white')
        ax.xaxis.label.set_color('white')
        ax.title.set_color('white')

        trace_count = 0
        for i, var in enumerate(vars_):
            name = var['name']
            if name == 'time':
                continue
            if name in self._hidden_vars:
                continue
            y_data = data.get(name, [])
            if not y_data or len(y_data) != len(time_data):
                continue

            y_arr = np.array(y_data)
            fft_mag = np.abs(np.fft.rfft(y_arr)) * 2 / len(y_arr)

            colour = self.TRACE_COLOURS[i % len(self.TRACE_COLOURS)]
            ax.plot(freqs, fft_mag, color=colour, linewidth=1.2, label=name)
            trace_count += 1

        ax.set_xlabel('Frequency (Hz)', color='white', fontsize=9)
        ax.set_ylabel('Magnitude (V)', color='white', fontsize=9)
        ax.set_title('FFT Spectrum  –  eSim Bridge', color='white', fontsize=10, pad=8)

        if trace_count > 0:
            ax.legend(loc='upper right', fontsize=8,
                      facecolor='#1a1a2e', edgecolor='#444466',
                      labelcolor='#ccccff', framealpha=0.8)
        else:
            ax.text(0.5, 0.5, 'No traces selected',
                    transform=ax.transAxes, ha='center', va='center',
                    color='#888899', fontsize=12)
            


        self._fig.subplots_adjust(left=0.12, bottom=0.12, right=0.97, top=0.92)
        self._canvas.draw()
        self._lbl_info.SetLabel(
            f"FFT | {trace_count} traces | {len(freqs)} freq points | "
            f"fs={fs:.0f} Hz | max={freqs[-1]:.0f} Hz"
        )

        # Change button to go back to waveform view
        self._fft_btn.SetLabel("📈 Show Waveform")
        self._fft_btn.SetSize((160, -1))
        self._fft_btn.Unbind(wx.EVT_BUTTON)
        self._fft_btn.Bind(wx.EVT_BUTTON, self._on_back_to_waveform)

    def _on_back_to_waveform(self, event):
        """Switch back from FFT to time-domain waveform view."""
        self._draw_plot()
        self._fft_btn.SetLabel("📊 Show FFT")
        self._fft_btn.Unbind(wx.EVT_BUTTON)
        self._fft_btn.Bind(wx.EVT_BUTTON, self._on_show_fft)
    

    def _on_show_bode(self, event):
        """Display dual-pane Bode plot (gain dB + phase degrees) for AC analysis."""
        import numpy as np

        if not self._parsed or not self._parsed.get('data'):
            wx.MessageBox("No data to plot. Run an AC simulation first.",
                          "Bode Plot", wx.OK | wx.ICON_WARNING)
            return

        data  = self._parsed['data']
        vars_ = self._parsed['vars']

        freq_data = data.get('frequency', [])
        if not freq_data or len(freq_data) < 2:
            wx.MessageBox("No frequency data found.\nRun an AC simulation first.",
                          "Bode Plot", wx.OK | wx.ICON_WARNING)
            return

        freq_arr = np.array(freq_data)

        # Clear single axes and replace with two subplots
        self._fig.clear()
        ax_gain  = self._fig.add_subplot(211)  # top: gain in dB
        ax_phase = self._fig.add_subplot(212)  # bottom: phase in degrees

        dark_style = dict(facecolor='#0d0d1a')
        for ax in (ax_gain, ax_phase):
            ax.set_facecolor('#0d0d1a')
            ax.tick_params(colors='white', labelsize=8)
            ax.spines[:].set_color('#444466')
            ax.grid(True, color='white', linestyle='dotted',
                    linewidth=0.6, alpha=0.4)
            ax.yaxis.label.set_color('white')
            ax.xaxis.label.set_color('white')
            ax.title.set_color('white')
        self._fig.patch.set_facecolor('#1a1a2e')

        trace_count = 0
        for i, var in enumerate(vars_):
            name = var['name']
            if name == 'frequency':
                continue
            if name in self._hidden_vars:
                continue

            y_data = data.get(name, [])
            if not y_data or len(y_data) != len(freq_arr):
                continue

            y_arr = np.array(y_data)

            # Magnitude in dB
            magnitude = np.abs(y_arr)
            # Avoid log(0)
            magnitude = np.where(magnitude == 0, 1e-12, magnitude)
            gain_db = 20 * np.log10(magnitude)

            # Phase in degrees
            phase_deg = np.angle(y_arr, deg=True) if np.iscomplexobj(y_arr) \
                        else np.zeros_like(y_arr)

            colour = self.TRACE_COLOURS[i % len(self.TRACE_COLOURS)]

            ax_gain.semilogx(freq_arr, gain_db,
                             color=colour, linewidth=1.4, label=name)
            ax_phase.semilogx(freq_arr, phase_deg,
                              color=colour, linewidth=1.4, label=name)
            trace_count += 1

        # Labels
        ax_gain.set_ylabel('Gain (dB)', color='white', fontsize=9)
        ax_gain.set_title('Bode Plot  –  eSim Bridge', color='white',
                          fontsize=10, pad=6)

        ax_phase.set_xlabel('Frequency (Hz)', color='white', fontsize=9)
        ax_phase.set_ylabel('Phase (°)', color='white', fontsize=9)

        if trace_count > 0:
            for ax in (ax_gain, ax_phase):
                ax.legend(loc='upper right', fontsize=8,
                          facecolor='#1a1a2e', edgecolor='#444466',
                          labelcolor='#ccccff', framealpha=0.8)

        self._fig.subplots_adjust(left=0.12, bottom=0.10,
                                  right=0.97, top=0.92, hspace=0.35)
        self._canvas.draw()

        self._lbl_info.SetLabel(
            f"Bode Plot | {trace_count} traces | "
            f"{len(freq_arr)} freq points | "
            f"{freq_arr[0]:.1f} Hz – {freq_arr[-1]:.1f} Hz"
        )

        # Toggle button to go back
        self._bode_btn.SetLabel("📉 Show Waveform")
        self._bode_btn.Unbind(wx.EVT_BUTTON)
        self._bode_btn.Bind(wx.EVT_BUTTON, self._on_back_from_bode)

    def _on_back_from_bode(self, event):
        """Restore single-axes waveform view from Bode plot."""
        self._fig.clear()
        self._ax = self._fig.add_subplot(111)
        self._draw_plot()
        self._bode_btn.SetLabel("📈 Bode Plot")
        self._bode_btn.Unbind(wx.EVT_BUTTON)
        self._bode_btn.Bind(wx.EVT_BUTTON, self._on_show_bode)
    

    def _on_toggle_cursor(self, event):
        """Toggle interactive cursor on/off."""
        if self._cursor_active:
            # Disable cursor
            if self._cursor_cid is not None:
                self._canvas.mpl_disconnect(self._cursor_cid)
                self._cursor_cid = None
            if self._cursor_annotation is not None:
                try:
                    self._cursor_annotation.remove()
                except Exception:
                    pass
                self._cursor_annotation = None
            self._cursor_active = False
            self._cursor_btn.SetLabel("🖱 Cursor")
            self._canvas.draw()
        else:
            # Enable cursor
            self._cursor_active = True
            self._cursor_btn.SetLabel("✖ Cursor OFF")
            self._cursor_cid = self._canvas.mpl_connect(
                'motion_notify_event', self._on_cursor_move)

    def _on_cursor_move(self, event):
        """Show crosshair annotation at mouse position."""
        if not self._cursor_active:
            return
        if event.inaxes is None:
            return

        ax = event.inaxes
        x, y = event.xdata, event.ydata
        if x is None or y is None:
            return

        # Format x label based on analysis type
        if self._analysis_type == 'tran':
            # Auto-scale time
            if abs(x) < 1e-6:
                x_str = f"{x*1e9:.3f} ns"
            elif abs(x) < 1e-3:
                x_str = f"{x*1e6:.3f} µs"
            elif abs(x) < 1:
                x_str = f"{x*1e3:.3f} ms"
            else:
                x_str = f"{x:.4f} s"
            label = f"t={x_str}\nV={y:.4f} V"
        elif self._analysis_type == 'ac':
            if x >= 1e6:
                x_str = f"{x/1e6:.3f} MHz"
            elif x >= 1e3:
                x_str = f"{x/1e3:.3f} kHz"
            else:
                x_str = f"{x:.1f} Hz"
            label = f"f={x_str}\n{y:.4f}"
        else:
            label = f"x={x:.4f}\ny={y:.4f}"

        # Remove old annotation
        if self._cursor_annotation is not None:
            try:
                self._cursor_annotation.remove()
            except Exception:
                pass

        # Draw crosshair lines
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()

        # Add annotation box
        self._cursor_annotation = ax.annotate(
            label,
            xy=(x, y),
            xytext=(15, 15),
            textcoords='offset points',
            fontsize=8,
            color='white',
            bbox=dict(
                boxstyle='round,pad=0.4',
                facecolor='#1a1a2e',
                edgecolor='#FFD700',
                alpha=0.9
            ),
            arrowprops=dict(
                arrowstyle='-',
                color='#FFD700',
                lw=1.2
            )
        )

        # Draw crosshair
        if not hasattr(self, '_cursor_hline'):
            self._cursor_hline = ax.axhline(
                y=y, color='#FFD700', linewidth=0.8,
                linestyle='--', alpha=0.7)
            self._cursor_vline = ax.axvline(
                x=x, color='#FFD700', linewidth=0.8,
                linestyle='--', alpha=0.7)
        else:
            try:
                self._cursor_hline.set_ydata([y, y])
                self._cursor_vline.set_xdata([x, x])
            except Exception:
                self._cursor_hline = ax.axhline(
                    y=y, color='#FFD700', linewidth=0.8,
                    linestyle='--', alpha=0.7)
                self._cursor_vline = ax.axvline(
                    x=x, color='#FFD700', linewidth=0.8,
                    linestyle='--', alpha=0.7)

        self._canvas.draw_idle()



    def _on_param_sweep(self, event):
        """Run parametric sweep — vary one component value, overlay results."""
        import numpy as np

        if not self._cir_path or not os.path.exists(self._cir_path):
            wx.MessageBox("No .cir file found. Run a simulation first.",
                          "Param Sweep", wx.OK | wx.ICON_WARNING)
            return

        # Read the .cir.out file to find component references
        cir_out = self._cir_path.replace('.cir', '.cir.out')
        if not os.path.exists(cir_out):
            cir_out = self._cir_path

        try:
            with open(cir_out, 'r') as f:
                cir_content = f.read()
        except Exception as e:
            wx.MessageBox(f"Could not read circuit file:\n{e}",
                          "Param Sweep", wx.OK | wx.ICON_ERROR)
            return

        # Find all resistors/capacitors/inductors in the file
        comps = re.findall(r'^([RCL]\w+)\s', cir_content, re.MULTILINE)
        if not comps:
            wx.MessageBox("No R/C/L components found in circuit file.",
                          "Param Sweep", wx.OK | wx.ICON_WARNING)
            return

        # Build sweep dialog
        dlg = wx.Dialog(self, title="🔁 Parametric Sweep", size=(420, 320))
        sizer = wx.BoxSizer(wx.VERTICAL)

        grid = wx.FlexGridSizer(rows=0, cols=2, vgap=8, hgap=10)
        grid.AddGrowableCol(1)

        grid.Add(wx.StaticText(dlg, label="Component:"), 0, wx.ALIGN_CENTER_VERTICAL)
        comp_choice = wx.Choice(dlg, choices=comps)
        comp_choice.SetSelection(0)
        grid.Add(comp_choice, 1, wx.EXPAND)

        grid.Add(wx.StaticText(dlg, label="Start value (e.g. 1k):"), 0, wx.ALIGN_CENTER_VERTICAL)
        start_tc = wx.TextCtrl(dlg, value="1k")
        grid.Add(start_tc, 1, wx.EXPAND)

        grid.Add(wx.StaticText(dlg, label="Stop value (e.g. 100k):"), 0, wx.ALIGN_CENTER_VERTICAL)
        stop_tc = wx.TextCtrl(dlg, value="100k")
        grid.Add(stop_tc, 1, wx.EXPAND)

        grid.Add(wx.StaticText(dlg, label="Steps (2–8):"), 0, wx.ALIGN_CENTER_VERTICAL)
        steps_tc = wx.TextCtrl(dlg, value="5")
        grid.Add(steps_tc, 1, wx.EXPAND)

        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 12)

        info = wx.StaticText(dlg,
            label="Each step reruns the simulation with a different\n"
                  "component value. Results are overlaid on one plot.")
        info.SetForegroundColour(wx.Colour(80, 80, 80))
        sizer.Add(info, 0, wx.LEFT | wx.BOTTOM, 12)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(dlg, wx.ID_OK, "Run Sweep")
        ok_btn.SetDefault()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(dlg, wx.ID_CANCEL, "Cancel"))
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        dlg.SetSizer(sizer)

        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return

        comp    = comp_choice.GetStringSelection()
        start_s = start_tc.GetValue().strip()
        stop_s  = stop_tc.GetValue().strip()
        try:
            n_steps = max(2, min(8, int(steps_tc.GetValue().strip())))
        except ValueError:
            n_steps = 5
        dlg.Destroy()

        def parse_val(s):
            """Convert SPICE value string to float."""
            s = s.strip().lower()
            mul = {'k': 1e3, 'm': 1e-3, 'u': 1e-6, 'n': 1e-9,
                   'p': 1e-12, 'meg': 1e6, 'g': 1e9}
            for suffix, factor in sorted(mul.items(), key=lambda x: -len(x[0])):
                if s.endswith(suffix):
                    return float(s[:-len(suffix)]) * factor
            return float(s)

        def fmt_val(v):
            """Format float back to readable SPICE string."""
            if v >= 1e6:   return f"{v/1e6:.3g}Meg"
            if v >= 1e3:   return f"{v/1e3:.3g}k"
            if v >= 1:     return f"{v:.3g}"
            if v >= 1e-3:  return f"{v*1e3:.3g}m"
            if v >= 1e-6:  return f"{v*1e6:.3g}u"
            if v >= 1e-9:  return f"{v*1e9:.3g}n"
            return f"{v:.3g}p"

        try:
            start_v = parse_val(start_s)
            stop_v  = parse_val(stop_s)
        except Exception:
            wx.MessageBox("Invalid start or stop value.\nUse SPICE notation: 1k, 100k, 10u",
                          "Param Sweep", wx.OK | wx.ICON_ERROR)
            return

        # Generate sweep values (log scale if ratio > 10, else linear)
        ratio = stop_v / start_v if start_v > 0 else 1
        if ratio > 10:
            values = np.logspace(np.log10(start_v), np.log10(stop_v), n_steps)
        else:
            values = np.linspace(start_v, stop_v, n_steps)

        # Progress dialog
        progress = wx.ProgressDialog(
            "Parametric Sweep",
            f"Running {n_steps} simulations…",
            maximum=n_steps,
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE | wx.PD_ELAPSED_TIME
        )

        # Run sweep
        sweep_results = []   # [(label, parsed_data)]
        SWEEP_COLOURS = [
            '#FF4444', '#4488FF', '#44FF88', '#FFD700',
            '#FF88FF', '#44FFFF', '#FF8844', '#AAAAFF'
        ]

        for step_i, val in enumerate(values):
            val_str = fmt_val(val)
            progress.Update(step_i, f"Step {step_i+1}/{n_steps}: {comp}={val_str}")

            # Modify circuit: replace component line value
            modified = re.sub(
                rf'^({re.escape(comp)}\s+\S+\s+\S+\s+)\S+',
                rf'\g<1>{val_str}',
                cir_content, count=1, flags=re.MULTILINE
            )

            # Write temp file
            tmp_cir = f'/tmp/esim_sweep_{step_i}.cir.out'
            raw_out = f'/tmp/esim_sweep_{step_i}.raw'

            # Inject binary write
            if '.control' in modified:
                modified = modified.replace(
                    '.control\n', f'.control\nset filetype=binary\n')
                modified = modified.replace(
                    '.endc\n', f'write {raw_out}\n.endc\n')

            with open(tmp_cir, 'w') as f:
                f.write(modified)

            try:
                env = os.environ.copy()
                env['PYTHONPATH'] = os.path.expanduser('~/Downloads/eSim-2.5/src')
                subprocess.run(
                    ['ngspice', '-b', tmp_cir],
                    capture_output=True, text=True, timeout=30,
                    env=env
                )
            except Exception:
                continue

            if os.path.exists(raw_out):
                try:
                    parser = NgspiceRawParser()
                    parsed = parser.parse(raw_out)
                    sweep_results.append((f"{comp}={val_str}", parsed))
                except Exception:
                    pass

        progress.Destroy()

        if not sweep_results:
            wx.MessageBox("Sweep produced no results. Check component name and values.",
                          "Param Sweep", wx.OK | wx.ICON_WARNING)
            return

        # Plot all sweep results overlaid
        ax = self._ax
        ax.clear()
        ax.set_facecolor('#0d0d1a')
        self._fig.patch.set_facecolor('#1a1a2e')
        ax.tick_params(colors='white', labelsize=8)
        ax.spines[:].set_color('#444466')
        ax.grid(True, color='white', linestyle='dotted', linewidth=0.6, alpha=0.4)
        ax.yaxis.label.set_color('white')
        ax.xaxis.label.set_color('white')
        ax.title.set_color('white')

        for idx, (label, parsed) in enumerate(sweep_results):
            data  = parsed.get('data', {})
            vars_ = parsed.get('vars', [])
            x_var = 'time' if 'time' in data else None
            if not x_var:
                continue
            x_data = data[x_var]
            colour = SWEEP_COLOURS[idx % len(SWEEP_COLOURS)]

            plotted = 0
            for var in vars_:
                name = var['name']
                if name == x_var:
                    continue
                if name in self._hidden_vars:
                    continue
                y_data = data.get(name, [])
                if y_data and len(y_data) == len(x_data):
                    plotted += 1
                    if plotted == 1:
                        continue  # skip first node (input/source)
                    ax.plot(x_data, y_data, color=colour,
                            linewidth=1.3, label=label, alpha=0.85)
                    break

        ax.set_xlabel('Time (s)', color='white', fontsize=9)
        ax.set_ylabel('Voltage (V)', color='white', fontsize=9)
        ax.set_title(f'Parametric Sweep  –  {comp}  ({start_s} → {stop_s})',
                     color='white', fontsize=10, pad=8)
        ax.legend(loc='upper right', fontsize=8,
                  facecolor='#1a1a2e', edgecolor='#444466',
                  labelcolor='#ccccff', framealpha=0.8)

        self._fig.subplots_adjust(left=0.12, bottom=0.12, right=0.97, top=0.92)
        self._canvas.draw()
        self._lbl_info.SetLabel(
            f"Param Sweep | {comp} | {len(sweep_results)} steps | "
            f"{start_s} → {stop_s}"
        )


    def _on_measure(self, event):
        """Run .meas analysis on transient data and show results."""
        if not self._parsed or not self._parsed.get('data'):
            wx.MessageBox("No data available. Run a transient simulation first.",
                          "Measure", wx.OK | wx.ICON_WARNING)
            return

        # Get available node names
        data = self._parsed['data']
        nodes = [v['name'] for v in self._parsed.get('vars', [])
                 if v['name'] != 'time']
        if not nodes:
            wx.MessageBox("No nodes found in simulation data.",
                          "Measure", wx.OK | wx.ICON_WARNING)
            return

        # Build dialog
        dlg = wx.Dialog(self, title="📏 Measurements", size=(420, 280))
        sizer = wx.BoxSizer(wx.VERTICAL)

        grid = wx.FlexGridSizer(rows=0, cols=2, vgap=8, hgap=10)
        grid.AddGrowableCol(1)

        grid.Add(wx.StaticText(dlg, label="Node:"), 0, wx.ALIGN_CENTER_VERTICAL)
        node_choice = wx.Choice(dlg, choices=nodes)
        node_choice.SetSelection(0)
        grid.Add(node_choice, 1, wx.EXPAND)

        grid.Add(wx.StaticText(dlg, label="Measurement:"), 0, wx.ALIGN_CENTER_VERTICAL)
        meas_choice = wx.Choice(dlg, choices=[
            "RMS Voltage", "Average Voltage", "Peak Voltage",
            "Min Voltage", "Max Voltage", "Frequency (zero-cross)"
        ])
        meas_choice.SetSelection(0)
        grid.Add(meas_choice, 1, wx.EXPAND)

        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 12)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(dlg, wx.ID_OK, "Measure")
        ok_btn.SetDefault()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(dlg, wx.ID_CANCEL, "Cancel"))
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        dlg.SetSizer(sizer)

        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return

        node = node_choice.GetStringSelection()
        meas = meas_choice.GetStringSelection()
        dlg.Destroy()

        # Compute from parsed data
        import math
        vals = data.get(node, [])
        time_vals = data.get('time', [])
        if not vals:
            wx.MessageBox(f"No data for node {node}.", "Measure", wx.OK | wx.ICON_WARNING)
            return

        if meas == "RMS Voltage":
            result = math.sqrt(sum(v**2 for v in vals) / len(vals))
            label = "RMS Voltage"
            unit = "V (rms)"
        elif meas == "Average Voltage":
            result = sum(vals) / len(vals)
            label = "Average Voltage"
            unit = "V"
        elif meas == "Peak Voltage":
            result = max(abs(v) for v in vals)
            label = "Peak Voltage"
            unit = "V"
        elif meas == "Min Voltage":
            result = min(vals)
            label = "Min Voltage"
            unit = "V"
        elif meas == "Max Voltage":
            result = max(vals)
            label = "Max Voltage"
            unit = "V"
        elif meas == "Frequency (zero-cross)":
            # Count zero crossings (rising)
            crossings = []
            for i in range(1, len(vals)):
                if vals[i-1] <= 0 < vals[i] and time_vals:
                    crossings.append(time_vals[i])
            if len(crossings) >= 2:
                period = (crossings[-1] - crossings[0]) / (len(crossings) - 1)
                result = 1.0 / period if period > 0 else 0
            else:
                result = 0
            label = "Frequency"
            unit = "Hz"
        else:
            result = 0
            label = meas
            unit = ""

        wx.MessageBox(
            f"Measurement Results\n"
            f"{'─'*35}\n"
            f"  Node      : {node}\n"
            f"  Measure   : {label}\n"
            f"  Result    : {result:.6g} {unit}\n",
            "eSim Bridge – Measurements",
            wx.OK | wx.ICON_INFORMATION
        )



    def set_stats_text(self, text):
        """Populate the bottom stats panel."""
        self._stats_ctrl.SetValue(text)


    def _build_stats_text(self, combined):
        """Build numerical summary from ngspice text output."""
        lines_out = []
        analysis = self._analysis_type.upper()
        lines_out.append(f"{'═'*60}")
        lines_out.append(f"  ngspice Simulation Summary  |  Analysis: {analysis}")
        lines_out.append(f"{'═'*60}")

        # ── Node voltage stats from .raw data ──
        if self._parsed and self._parsed.get('data'):
            data = self._parsed['data']
            x_var = 'time' if 'time' in data else ('frequency' if 'frequency' in data else None)
            node_lines = []
            for var in self._parsed.get('vars', []):
                name = var['name']
                if name == x_var:
                    continue
                vals = data.get(name, [])
                if not vals:
                    continue
                vmax  = max(vals)
                vmin  = min(vals)
                vavg  = sum(vals) / len(vals)
                vpeak = max(abs(vmax), abs(vmin))
                node_lines.append(
                    f"  {name:<22}  peak={vpeak:+.4f}V  "
                    f"max={vmax:+.4f}V  min={vmin:+.4f}V  avg={vavg:+.4f}V  "
                    f"pts={len(vals)}"
                )
            if node_lines:
                lines_out.append("")
                lines_out.append("  Node Voltages:")
                lines_out.extend(node_lines)

        # ── Noise analysis results ──
        noise_hits = [l.strip() for l in combined.splitlines()
                      if any(kw in l.lower() for kw in
                             ('inoise', 'onoise', 'noise', 'spectral'))]
        if noise_hits:
            lines_out.append("")
            lines_out.append("  Noise Analysis Results:")
            for nl in noise_hits[:20]:
                lines_out.append(f"    {nl}")
            lines_out.append("  (inoise = input-referred noise, onoise = output noise)")

        # ── Timing / rusage ──
        timing = [l.strip() for l in combined.splitlines()
                  if any(kw in l.lower() for kw in
                         ('total analysis time', 'total elapsed', 'cpu time',
                          'accepted', 'rejected', 'time step'))]
        if timing:
            lines_out.append("")
            lines_out.append("  Simulation Timing / Solver Stats:")
            for tl in timing[:10]:
                lines_out.append(f"    {tl}")

        # ── Warnings / errors ──
        warns = [l.strip() for l in combined.splitlines()
                 if any(kw in l.lower() for kw in ('warning', 'error', 'fatal'))
                 and l.strip()]
        if warns:
            lines_out.append("")
            lines_out.append("  ⚠ Warnings/Errors:")
            for wl in warns[:8]:
                lines_out.append(f"    {wl}")

        lines_out.append(f"{'─'*60}")
        return '\n'.join(lines_out)

# ══════════════════════════════════════════════════════════════════════
# REPLACEMENT _on_run_ngspice METHOD
# Cut out the old _on_run_ngspice from SimulationReadyDialog and
# paste this one in its place (inside the SimulationReadyDialog class).
# ══════════════════════════════════════════════════════════════════════

    def _on_run_ngspice(self, event):
        """Run ngspice directly and show interactive waveform viewer."""
        if not self.cir_out_path or not os.path.exists(self.cir_out_path):
            wx.MessageBox(
                "ngspice input file not found.\nPlease try again.",
                "ngspice Error", wx.OK | wx.ICON_ERROR)
            return

        # Output .raw file alongside the .cir.out
        raw_path = self.cir_out_path.replace('.cir.out', '.raw')
        if not raw_path.endswith('.raw'):
            raw_path = self.cir_out_path + '.raw'

        # Delete stale raw file
        try:
            if os.path.exists(raw_path):
                os.remove(raw_path)
        except Exception:
            pass

        # Inject  -r <raw_path>  into a temporary copy of the .cir.out
        # so ngspice writes binary data we can parse
        import tempfile, shutil
        tmp_cir = raw_path.replace('.raw', '_viewer.cir.out')
        try:
            with open(self.cir_out_path, 'r') as f:
                cir_content = f.read()

            # Insert  set filetype=binary  and  write  inside .control block
            # (ngspice dumps .raw only when told to write)
            if '.control' in cir_content:
                cir_content = cir_content.replace(
                    '.control\n',
                    f'.control\nset filetype=binary\n'
                )
                # Add write command before .endc
                cir_content = cir_content.replace(
                    '.endc\n',
                    f'write {raw_path}\n.endc\n'
                )
            with open(tmp_cir, 'w') as f:
                f.write(cir_content)
        except Exception as e:
            wx.MessageBox(f"Could not prepare ngspice input:\n{e}",
                          "Error", wx.OK | wx.ICON_ERROR)
            return

        # Progress dialog
        progress = wx.ProgressDialog(
            "ngspice Runner",
            "Running simulation…",
            maximum=100,
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
        )
        progress.Pulse()

        try:
            env = os.environ.copy()
            env['PYTHONPATH'] = os.path.expanduser('~/Downloads/eSim-2.5/src')

            result = subprocess.run(
                ['ngspice', '-b', tmp_cir],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=os.path.dirname(self.cir_out_path),
                env=env
            )
            progress.Destroy()

        except subprocess.TimeoutExpired:
            progress.Destroy()
            wx.MessageBox(
                "ngspice timed out after 60 seconds.\n"
                "Circuit may be too complex or have a convergence issue.",
                "ngspice Timeout", wx.OK | wx.ICON_ERROR)
            return
        except FileNotFoundError:
            progress.Destroy()
            wx.MessageBox(
                "ngspice not found.\n"
                "Install it with:  sudo apt install ngspice",
                "ngspice Not Found", wx.OK | wx.ICON_ERROR)
            return
        except Exception as e:
            progress.Destroy()
            wx.MessageBox(f"Unexpected error:\n{e}",
                          "ngspice Error", wx.OK | wx.ICON_ERROR)
            return

        # Check for errors
        combined = (result.stdout or '') + '\n' + (result.stderr or '')
        if result.returncode != 0 and not os.path.exists(raw_path):
            err_lines = [l for l in combined.splitlines()
                         if 'error' in l.lower() or 'fatal' in l.lower()]
            err_text = '\n'.join(err_lines[:15]) or combined[:800]
            wx.MessageBox(
                f"ngspice returned error code {result.returncode}.\n\n"
                f"{err_text}",
                "ngspice Error", wx.OK | wx.ICON_ERROR)
            return


        # Show waveform viewer
        if os.path.exists(raw_path):
            viewer = NgspiceWaveformViewer(
                self,
                raw_path=raw_path,
                analysis_type=self.analysis_type,
                cir_path=self.cir_out_path,
                ngspice_output=combined
            )
            viewer.ShowModal()
            viewer.Destroy()
        else:
            # Fallback: show text summary if no raw file produced
            wx.MessageBox(
                f"Simulation finished but no .raw file was produced.\n\n"
                f"ngspice output (last 20 lines):\n"
                + '\n'.join(combined.splitlines()[-20:]),
                "ngspice – No Waveform Data",
                wx.OK | wx.ICON_WARNING)







# ══════════════════════════════════════════════════════════════════════
# SIMULATION READY DIALOG
# ══════════════════════════════════════════════════════════════════════

class SimulationReadyDialog(wx.Dialog):
    """Shows after successful conversion, before launching eSim."""

    def __init__(self, parent, spice_path, components, analysis_type, params,
                 unsupported_summary=None, cir_out_path=None):
        super().__init__(parent, title="Ready to Simulate", size=(600, 750))
        self.cir_out_path = cir_out_path
        self.analysis_type = analysis_type
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        header = wx.StaticText(self, 
            label="✓ Schematic converted successfully!")
        header.SetForegroundColour(wx.Colour(0, 128, 0))
        font = wx.Font(11, wx.FONTFAMILY_DEFAULT, 
                      wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        header.SetFont(font)
        sizer.Add(header, 0, wx.ALL, 10)
        
        summary = (
            f"Components converted: {len(components)}\n"
            f"Analysis type: {analysis_type.upper()}\n"
            f"SPICE file: {spice_path}\n"
        )
        if params:
            summary += f"Parameters: {params}"
        
        summary_text = wx.StaticText(self, label=summary)
        sizer.Add(summary_text, 0, wx.ALL, 10)
        
        # Show warnings about unsupported components
        if unsupported_summary:
            warn_label = wx.StaticText(self, label="⚠ Conversion Notes:")
            warn_label.SetForegroundColour(wx.Colour(200, 100, 0))
            sizer.Add(warn_label, 0, wx.LEFT | wx.TOP, 10)
            
            warn_text = wx.TextCtrl(
                self, value=unsupported_summary,
                style=wx.TE_MULTILINE | wx.TE_READONLY,
                size=(-1, 120))
            warn_text.SetForegroundColour(wx.Colour(200, 100, 0))
            sizer.Add(warn_text, 0, wx.ALL | wx.EXPAND, 10)
        
        preview_label = wx.StaticText(self, label="Generated SPICE file:")
        sizer.Add(preview_label, 0, wx.LEFT | wx.TOP, 10)
        
        try:
            with open(spice_path, 'r') as f:
                spice_content = f.read()
        except:
            spice_content = "Could not read file"
        
        preview = wx.TextCtrl(
            self, value=spice_content,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
            size=(-1, 300))
        preview.SetFont(wx.Font(9, wx.FONTFAMILY_TELETYPE,
                               wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        sizer.Add(preview, 1, wx.ALL | wx.EXPAND, 10)
        
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        launch_btn = wx.Button(self, wx.ID_OK, "Launch eSim →")
        launch_btn.SetDefault()
        
        open_file_btn = wx.Button(self, wx.ID_ANY, "Open .cir File")
        open_file_btn.Bind(wx.EVT_BUTTON, 
            lambda e: os.system(f'xdg-open {spice_path}'))
        
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Close")
        


        ngspice_btn = wx.Button(self, wx.ID_ANY, "Run with ngspice →")
        ngspice_btn.SetBackgroundColour(wx.Colour(0, 80, 160))
        ngspice_btn.SetForegroundColour(wx.Colour(255, 255, 255))
        ngspice_btn.Bind(wx.EVT_BUTTON, self._on_run_ngspice)
        
        btn_sizer.Add(launch_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(ngspice_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(open_file_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(cancel_btn, 0)
        
        sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        self.SetSizer(sizer)

    






    def _on_run_ngspice(self, event):
        """Run ngspice directly and show interactive waveform viewer."""
        if not self.cir_out_path or not os.path.exists(self.cir_out_path):
            wx.MessageBox(
                "ngspice input file not found.\nPlease try again.",
                "ngspice Error", wx.OK | wx.ICON_ERROR)
            return

        # Output .raw file alongside the .cir.out
        raw_path = self.cir_out_path.replace('.cir.out', '.raw')
        if not raw_path.endswith('.raw'):
            raw_path = self.cir_out_path + '.raw'

        # Delete stale raw file
        try:
            if os.path.exists(raw_path):
                os.remove(raw_path)
        except Exception:
            pass

        # Inject  -r <raw_path>  into a temporary copy of the .cir.out
        # so ngspice writes binary data we can parse
        import tempfile, shutil
        tmp_cir = raw_path.replace('.raw', '_viewer.cir.out')
        try:
            with open(self.cir_out_path, 'r') as f:
                cir_content = f.read()

            # Insert  set filetype=binary  and  write  inside .control block
            # (ngspice dumps .raw only when told to write)
            if '.control' in cir_content:
                cir_content = cir_content.replace(
                    '.control\n',
                    f'.control\nset filetype=binary\n'
                )
                # Add write command before .endc
                cir_content = cir_content.replace(
                    '.endc\n',
                    f'write {raw_path}\n.endc\n'
                )
            with open(tmp_cir, 'w') as f:
                f.write(cir_content)
        except Exception as e:
            wx.MessageBox(f"Could not prepare ngspice input:\n{e}",
                        "Error", wx.OK | wx.ICON_ERROR)
            return

        # Progress dialog
        progress = wx.ProgressDialog(
            "ngspice Runner",
            "Running simulation…",
            maximum=100,
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
        )
        progress.Pulse()

        try:
            env = os.environ.copy()
            env['PYTHONPATH'] = os.path.expanduser('~/Downloads/eSim-2.5/src')

            result = subprocess.run(
                ['ngspice', '-b', tmp_cir],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=os.path.dirname(self.cir_out_path),
                env=env
            )
            progress.Destroy()

        except subprocess.TimeoutExpired:
            progress.Destroy()
            wx.MessageBox(
                "ngspice timed out after 60 seconds.\n"
                "Circuit may be too complex or have a convergence issue.",
                "ngspice Timeout", wx.OK | wx.ICON_ERROR)
            return
        except FileNotFoundError:
            progress.Destroy()
            wx.MessageBox(
                "ngspice not found.\n"
                "Install it with:  sudo apt install ngspice",
                "ngspice Not Found", wx.OK | wx.ICON_ERROR)
            return
        except Exception as e:
            progress.Destroy()
            wx.MessageBox(f"Unexpected error:\n{e}",
                        "ngspice Error", wx.OK | wx.ICON_ERROR)
            return

        # Check for errors
        combined = (result.stdout or '') + '\n' + (result.stderr or '')
        if result.returncode != 0 and not os.path.exists(raw_path):
            err_lines = [l for l in combined.splitlines()
                        if 'error' in l.lower() or 'fatal' in l.lower()]
            err_text = '\n'.join(err_lines[:15]) or combined[:800]
            wx.MessageBox(
                f"ngspice returned error code {result.returncode}.\n\n"
                f"{err_text}",
                "ngspice Error", wx.OK | wx.ICON_ERROR)
            return


        # Show waveform viewer
        if os.path.exists(raw_path):
            viewer = NgspiceWaveformViewer(
                self,
                raw_path=raw_path,
                analysis_type=self.analysis_type,
                cir_path=self.cir_out_path,
                ngspice_output=combined
            )
            viewer.ShowModal()
            viewer.Destroy()
        else:
            # Fallback: show text summary if no raw file produced
            wx.MessageBox(
                f"Simulation finished but no .raw file was produced.\n\n"
                f"ngspice output (last 20 lines):\n"
                + '\n'.join(combined.splitlines()[-20:]),
                "ngspice – No Waveform Data",
                wx.OK | wx.ICON_WARNING)












            


    def _parse_ngspice_output(self, combined, returncode):
        """Parse ngspice raw output into a clean human-readable summary."""
        lines = combined.split('\n')
        
        # Collect data rows per node
        node_data = {}  # {node_name: [float values]}
        current_nodes = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            


            # Detect header line like: Index   time   net_r1_pad1   net_r2_pad1
            if line.startswith('Index') and 'time' in line.lower():
                parts = line.split()
                try:
                    time_idx = next(i for i, p in enumerate(parts) if p.lower() == 'time')
                    raw_nodes = parts[time_idx + 1:]
                    current_nodes = []
                    for node in raw_nodes:
                        # Normalize v(net_r1_pad1) → net_r1_pad1
                        clean = re.sub(r'^v\((.+)\)$', r'\1', node, flags=re.IGNORECASE)
                        # Skip non-node entries like 'alli', 'allv'
                        if clean.lower() in ('alli', 'allv', 'all'):
                            continue
                        current_nodes.append(clean)
                        if clean not in node_data:
                            node_data[clean] = []
                except StopIteration:
                    pass
                continue
            
            # Skip separator lines
            if line.startswith('---'):
                continue
            
            # Try to parse data rows: index  time  val1  val2 ...
            parts = line.split()
            if len(parts) >= 3 and parts[0].isdigit():
                try:
                    values = [float(p) for p in parts[1:]]  # skip index
                    # values[0] = time, values[1:] = node values
                    for i, node in enumerate(current_nodes):
                        if i + 1 < len(values):
                            node_data[node].append(values[i + 1])
                except ValueError:
                    pass
        
        # Build summary
        summary_lines = []
        summary_lines.append("=" * 50)
        summary_lines.append(f"ngspice Simulation Summary")
        summary_lines.append(f"Analysis Type: {self.analysis_type.upper()}")
        summary_lines.append("=" * 50)
        
        if node_data:
            summary_lines.append("")
            summary_lines.append("Node Voltage Summary:")
            summary_lines.append("-" * 50)
            
            for node, values in node_data.items():
                if not values:
                    continue
                vmax = max(values)
                vmin = min(values)
                vavg = sum(values) / len(values)
                vpeak = max(abs(vmax), abs(vmin))
                
                summary_lines.append(f"\nNode: {node}")
                summary_lines.append(f"  Peak voltage  : {vpeak:.4f} V")
                summary_lines.append(f"  Max voltage   : {vmax:.4f} V")
                summary_lines.append(f"  Min voltage   : {vmin:.4f} V")
                summary_lines.append(f"  Avg voltage   : {vavg:.4f} V")
                summary_lines.append(f"  Data points   : {len(values)}")


        else:
            # Check for noise analysis results specifically
            noise_lines = [l.strip() for l in combined.split('\n')
                          if 'inoise' in l.lower() or 'onoise' in l.lower()]
            if noise_lines:
                summary_lines.append("")
                summary_lines.append("Noise Analysis Results:")
                summary_lines.append("-" * 50)
                for nl in noise_lines:
                    summary_lines.append(f"  {nl}")
                summary_lines.append("")
                summary_lines.append("Tip: inoise = input-referred noise, onoise = output noise")
            else:
                summary_lines.append("")
                summary_lines.append("No node data found in output.")
                summary_lines.append("Raw output (last 20 lines):")
                summary_lines.append("-" * 50)
                raw_lines = [l.strip() for l in combined.split('\n') if l.strip()]
                summary_lines.extend(raw_lines[-20:])

        # Add timing info
        timing_found = False
        for tline in combined.split('\n'):
            if 'Total analysis time' in tline or 'Total elapsed time' in tline:
                if not timing_found:
                    summary_lines.append("")
                    summary_lines.append("-" * 50)
                    summary_lines.append("Simulation Timing:")
                    timing_found = True
                summary_lines.append(tline.strip())
        
        if returncode != 0:
            summary_lines.append("")
            summary_lines.append("WARNING: ngspice returned a non-zero exit code.")
            summary_lines.append("Simulation may have encountered errors.")
        
        return '\n'.join(summary_lines)

# ══════════════════════════════════════════════════════════════════════
# MAIN PLUGIN CLASS
# ══════════════════════════════════════════════════════════════════════

class ESimBridgePlugin(pcbnew.ActionPlugin):
    
    def defaults(self):
        self.name = "eSim Simulation Bridge"
        self.category = "eSim Tools"
        self.description = "Launch eSim simulation with one click - supports passive, active & user-provided models"
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(
            os.path.dirname(__file__), 'icon.png'
        )
    
    def Run(self):
        """Main function - called when user clicks the plugin button"""
        
        LOG_FILE = os.path.expanduser("~/.local/share/kicad/esim_bridge.log")
        logging.basicConfig(
            filename=LOG_FILE,
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        logger = logging.getLogger('ESimBridge')
        logger.info("Plugin Run() called - eSim Bridge v2.1.0")
        
        # Delete stale .raw file
        workspace = os.path.expanduser("~/eSim-Workspace")
        project_name = "esim_bridge_project"
        project_folder = os.path.join(workspace, project_name)
        raw_file = os.path.join(project_folder, project_name + ".raw")
        try:
            if os.path.exists(raw_file):
                os.remove(raw_file)
        except Exception:
            pass
        
        

        # ── Step 1: Get schematic path ────────────────────────
        app = wx.App.Get()
        if not app:
            app = wx.App()

        schematic_path = self.get_schematic_path()
        if not schematic_path:
            wx.MessageBox(
                "No schematic found.\nPlease open a schematic first.",
                "eSim Bridge", wx.OK | wx.ICON_ERROR)
            return

        # ── Step 2: Export netlist silently ───────────────────
        netlist_xml_path = "/tmp/esim_bridge_netlist.net"
        if not self.export_netlist(schematic_path, netlist_xml_path):
            wx.MessageBox(
                "Failed to export netlist.\n"
                "Make sure kicad-cli is available.",
                "eSim Bridge Error", wx.OK | wx.ICON_ERROR)
            return

        # ── Step 3: Parse netlist & show tabbed dialog ────────
        converter = SPICEConverter()
        components_pre, nets_pre = converter.parse_full_netlist(netlist_xml_path)

        ktn_dlg = KicadToNgspiceDialog(None, components_pre)
        if ktn_dlg.ShowModal() != wx.ID_OK:
            ktn_dlg.Destroy()
            return

        analysis_type    = ktn_dlg.get_analysis_type()
        analysis_params  = ktn_dlg.get_analysis_params()
        source_overrides = ktn_dlg.get_source_overrides()
        ngmodel_lines    = ktn_dlg.get_ngmodel_lines()
        device_lib_paths = ktn_dlg.get_device_lib_paths()
        subcircuit_paths = ktn_dlg.get_subcircuit_paths()
        ktn_dlg.Destroy()



        # ── Step 3b: Netlist sanity check ────────────────────
        checker = PreflightChecker()
        netlist_issues = checker.run_netlist_checks(components_pre, nets_pre)
        logger.info(f"Netlist check: {len(netlist_issues)} issues found: {netlist_issues}")
        errors   = [m for s, m in netlist_issues if s == 'error']
        warnings = [m for s, m in netlist_issues if s == 'warning']

        if errors:
            error_text = "\n\n".join(errors)
            result = wx.MessageBox(
                f"Netlist Problems Detected:\n\n{error_text}\n\n"
                "These will cause ngspice to fail. Continue anyway?",
                "eSim Bridge - Netlist Check",
                wx.YES_NO | wx.ICON_ERROR)
            if result != wx.YES:
                return
        elif warnings:
            warning_text = "\n\n".join(warnings)
            wx.MessageBox(
                f"Netlist Warnings:\n\n{warning_text}",
                "eSim Bridge - Netlist Check",
                wx.OK | wx.ICON_WARNING)
        
        # ── Step 4: Convert to SPICE format ──────────────────
        progress = wx.ProgressDialog(
            "eSim Bridge",
            "Converting to SPICE format...",
            maximum=3,
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
        )
        
        spice_output_path = "/tmp/esim_bridge_simulation.cir"
        
        converter = SPICEConverter()
        success = converter.convert(
            netlist_path=netlist_xml_path,
            output_path=spice_output_path,
            analysis_type=analysis_type,
            analysis_params=analysis_params
        )
        
        if not success:
            progress.Destroy()
            wx.MessageBox(
                "Failed to convert netlist to SPICE format.",
                "eSim Bridge Error", wx.OK | wx.ICON_ERROR)
            return
        
        # Get unsupported component warnings
        unsupported_summary = converter.get_unsupported_summary()
        # Inject Ngspice Model tab lines into SPICE file
        if ngmodel_lines:
            with open(spice_output_path, 'r') as f:
                content = f.read()
            inject = '\n* -- Ngspice Model Tab --\n' + '\n'.join(ngmodel_lines)
            content = content.replace('\n.end', inject + '\n.end')
            with open(spice_output_path, 'w') as f:
                f.write(content)

        # ── NEW: eSim-SPICE Model Auto-Linker ───────────────────
        try:
            import sys
            plugin_dir = os.path.dirname(__file__)
            if plugin_dir not in sys.path:
                sys.path.insert(0, plugin_dir)
            from esim_spice_linker import SPICEAutoLinker
            linker = SPICEAutoLinker()


            components_raw, nets_raw = converter.parse_full_netlist(netlist_xml_path)
            # Don't re-check components whose models eSim-BRIDGE already resolved
            match_results = linker.check_models(components_raw)
            
            progress.Destroy()  # Close progress before showing report
            
            if not linker.show_report(None, components_raw, match_results):
                return  # User cancelled
            
            esim_models, esim_subcircuits = linker.get_injection_data(match_results)


            # Remove duplicates - eSim-BRIDGE already injected what eSim-SPICE found
            for name in list(esim_subcircuits.keys()):
                if name in converter.required_subcircuits:
                    esim_subcircuits.pop(name)
            for name in list(esim_models.keys()):
                if name in converter.required_models:
                    esim_models.pop(name)



            converter.required_models.update(esim_models)
            converter.required_subcircuits.update(esim_subcircuits)
            
            # Re-write the SPICE file with eSim library models included
            converter._rewrite_with_models(spice_output_path)
        except Exception as e:
            logger.warning(f"eSim-SPICE model linking skipped: {e}")
            try:
                progress.Destroy()
            except Exception:
                pass




        
        # ── Step 6: Prepare eSim project ─────────────────────        
        os.makedirs(project_folder, exist_ok=True)
        # Copy dependency .sub files for any subcircuits that need them
        esim_subckt_dir = os.path.expanduser('~/Downloads/eSim-2.5/library/SubcircuitLibrary')
        for root, dirs, files in os.walk(esim_subckt_dir):
            for filename in files:
                if filename.endswith('.sub') and filename != os.path.basename(spice_output_path):
                    # Check if this .sub is referenced in the .cir file
                    with open(spice_output_path, 'r') as f:
                        cir_content = f.read()
                    if filename.replace('.sub', '') in cir_content or filename in cir_content:
                        shutil.copy(os.path.join(root, filename), project_folder)
        os.makedirs(os.path.join(project_folder, "images"), exist_ok=True)
        
        # Build .cir.out with control block
        with open(spice_output_path, 'r') as f:
            spice_content = f.read()
        

        spice_content = spice_content.replace('.end\n', '').strip() + "\n"
        # Remove existing analysis command to avoid duplicate runs in ngspice
        spice_content = re.sub(r'\.(tran|ac|dc|op|tf)\s+[^\n]*\n', '', spice_content, flags=re.IGNORECASE)
        spice_content += "* Control Statements\n"
        spice_content += ".control\n"

        # Analysis-specific simulation command
        if analysis_type == 'tran':
            step = analysis_params.get('step', '1us')
            stop = analysis_params.get('stop', '10ms')
            start = analysis_params.get('start', '0')
            spice_content += f"tran {step} {stop} {start}\n"
        elif analysis_type == 'ac':
            scale = analysis_params.get('scale', 'dec')
            points = analysis_params.get('points', '100')
            fstart = analysis_params.get('fstart', '1Hz')
            fstop = analysis_params.get('fstop', '1MEGHz')
            spice_content += f"ac {scale} {points} {fstart} {fstop}\n"
        elif analysis_type == 'dc':
            source = analysis_params.get('source', 'V1')
            start = analysis_params.get('start', '0')
            stop = analysis_params.get('stop', '5')
            step = analysis_params.get('step', '0.1')
            spice_content += f"dc {source} {start} {stop} {step}\n"
        elif analysis_type == 'op':
            spice_content += "op\n"

        
        
        elif analysis_type == 'tf':
            output = analysis_params.get('output', 'out')
            source = analysis_params.get('source', 'V1')
            spice_content += f"tf v({output}) {source}\n"
        
        elif analysis_type == 'noise':
            output = analysis_params.get('output', 'out')
            source = analysis_params.get('source', 'V1')
            fstart = analysis_params.get('fstart', '1')
            fstop  = analysis_params.get('fstop', '1Meg')
            points = analysis_params.get('points', '100')
            spice_content += f"noise v({output}) {source} dec {points} {fstart} {fstop}\n"

        
        elif analysis_type == 'sens':
            output = analysis_params.get('output', 'v(out)')
            spice_content += f"op\n"
            spice_content += f"sens {output}\n"

        spice_content += "run\n"
        spice_content += "rusage all\n"
        spice_content += "print allv\n"
        spice_content += "print alli\n"
        spice_content += "print allv > plot_data_v.txt\n"
        spice_content += "print alli > plot_data_i.txt\n"
        spice_content += ".endc\n"
        spice_content += ".end\n"


        
        
        # Delete stale .raw
        raw_file_pre = os.path.join(project_folder, project_name + ".raw")
        try:
            if os.path.exists(raw_file_pre):
                os.remove(raw_file_pre)
        except Exception:
            pass
        
        # Write files
        dest = os.path.join(project_folder, project_name + ".cir.out")
        with open(dest, 'w') as f:
            f.write(spice_content)
        
        cir_dest = os.path.join(project_folder, project_name + ".cir")
        shutil.copy(spice_output_path, cir_dest)
        
        proj_file = os.path.join(project_folder, project_name + ".proj")
        open(proj_file, 'w').close()
        
        # Write analysis file
        analysis_file = os.path.join(project_folder, "analysis")
        if analysis_type == 'ac':
            scale = analysis_params.get('scale', 'dec')
            fstart = analysis_params.get('fstart', '1Hz')
            fstop = analysis_params.get('fstop', '1MEGHz')
            points = analysis_params.get('points', '100')
            analysis_content = f".ac {scale} {points} {fstart} {fstop}"
        elif analysis_type == 'tran':
            start = analysis_params.get('start', '0')
            step = analysis_params.get('step', '1us')
            stop = analysis_params.get('stop', '10ms')
            analysis_content = f".tran {step} {stop} {start}"
        elif analysis_type == 'dc':
            source = analysis_params.get('source', 'V1')
            start = analysis_params.get('start', '0')
            stop = analysis_params.get('stop', '5')
            step = analysis_params.get('step', '0.1')
            analysis_content = f".dc {source} {start} {stop} {step}"
        else:
            analysis_content = ".op"
        
        with open(analysis_file, 'w') as f:
            f.write(analysis_content)
                
        # ── Step 7: Show results / handle OP ─────────────────
        components_temp, _ = converter.parse_full_netlist(netlist_xml_path)
        
        if analysis_type == 'op':
            try:
                env = os.environ.copy()
                env['PYTHONPATH'] = os.path.expanduser(
                    '~/Downloads/eSim-2.5/src')
                result = subprocess.run(
                    ['ngspice', '-b', dest],
                    capture_output=True, text=True, timeout=10,
                    cwd=project_folder, env=env
                )
                output = result.stdout + result.stderr
                lines = [l.strip() for l in output.split('\n') 
                         if '=' in l and ('net_' in l.lower() or 'v(' in l.lower()
                         or any(c.isdigit() for c in l))]
                values = '\n'.join(lines) if lines else output[:500]
            except Exception as e:
                values = f"Could not get values: {e}"
            
            wx.MessageBox(
                f"Operating Point Analysis completed!\n\n"
                f"DC Node Voltages:\n{values}\n\n"
                "Note: OP analysis does not produce a waveform graph.",
                "eSim Bridge - OP Analysis",
                wx.OK | wx.ICON_INFORMATION)
            return
        

        if analysis_type == 'tf':
            try:
                env = os.environ.copy()
                env['PYTHONPATH'] = os.path.expanduser('~/Downloads/eSim-2.5/src')
                result = subprocess.run(
                    ['ngspice', '-b', dest],
                    capture_output=True, text=True, timeout=10,
                    cwd=project_folder, env=env
                )
                output = result.stdout + result.stderr
                output_node = analysis_params.get('output', 'out')
                source = analysis_params.get('source', 'V1')

                tf_val = in_imp = out_imp = None
                for l in output.split('\n'):
                    ll = l.lower()
                    if 'transfer_function' in ll or 'transfer function' in ll:
                        tf_val = l.strip()
                    elif 'input_impedance' in ll or 'input impedance' in ll:
                        in_imp = l.strip()
                    elif 'output_impedance' in ll or 'output impedance' in ll:
                        out_imp = l.strip()

                msg = (
                    f"Transfer Function Analysis\n"
                    f"  Output node : v({output_node})\n"
                    f"  Input source: {source}\n"
                    f"{'─'*40}\n"
                    f"  Gain (v({output_node}) / {source}):\n"
                    f"    {tf_val or 'not found'}\n\n"
                    f"  Input Impedance (seen by {source}):\n"
                    f"    {in_imp or 'not found'}\n\n"
                    f"  Output Impedance (at v({output_node})):\n"
                    f"    {out_imp or 'not found'}\n"
                )
            except Exception as e:
                msg = f"Could not get values: {e}"

            wx.MessageBox(msg, "eSim Bridge - Transfer Function",
                          wx.OK | wx.ICON_INFORMATION)
            return

        if analysis_type == 'sens':
            try:
                env = os.environ.copy()
                env['PYTHONPATH'] = os.path.expanduser('~/Downloads/eSim-2.5/src')
                result = subprocess.run(
                    ['ngspice', '-b', dest],
                    capture_output=True, text=True, timeout=15,
                    cwd=project_folder, env=env
                )
                output = result.stdout + result.stderr
                output_var = analysis_params.get('output', 'v(out)')


                sens_lines = []
                for line in output.split('\n'):
                    line = line.strip()
                    if not line or '=' not in line:
                        continue
                    parts = line.split('=')
                    if len(parts) != 2:
                        continue
                    key = parts[0].strip().lower()
                    val = parts[1].strip()
                    if re.match(r'^[rclvi]\d+$', key):
                        try:
                            float(val)
                            sens_lines.append(line)
                        except ValueError:
                            pass

                if sens_lines:
                    def abs_val(s):
                        try:
                            return abs(float(s.split('=')[1].strip()))
                        except Exception:
                            return 0
                    sens_lines.sort(key=abs_val, reverse=True)
                    table = '\n'.join(f"  {l}" for l in sens_lines[:20])
                else:
                    table = output[:600] or "No sensitivity data found."

                wx.MessageBox(
                    f"Sensitivity Analysis\n"
                    f"  Output : {output_var}\n"
                    f"{'─'*45}\n"
                    f"  Note: Sensitivity requires a DC operating point.\n"
                    f"  If all values are zero, add a DC value to your source\n"
                    f"  (e.g. change V1 from SIN to DC 5).\n\n"
                    f"  Components ranked by impact (highest first):\n\n"
                    f"{table}\n\n"
                    f"  Positive = increasing component increases output\n"
                    f"  Negative = increasing component decreases output",
                    "eSim Bridge – Sensitivity Analysis",
                    wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                wx.MessageBox(f"Sensitivity analysis failed:\n{e}",
                              "eSim Bridge", wx.OK | wx.ICON_ERROR)
            return


        results_dialog = SimulationReadyDialog(
            None, spice_output_path, components_temp,
            analysis_type, analysis_params, unsupported_summary,
            cir_out_path=dest)
        
        if results_dialog.ShowModal() != wx.ID_OK:
            results_dialog.Destroy()
            return
        
        results_dialog.Destroy()
        
        # Delete stale .raw
        try:
            if os.path.exists(raw_file):
                os.remove(raw_file)
        except Exception:
            pass
        
        # Launch eSim
        env = os.environ.copy()
        env['PYTHONPATH'] = os.path.expanduser('~/Downloads/eSim-2.5/src')
        
        subprocess.Popen(
            [os.path.expanduser('~/.esim/env/bin/python3'), 'Application.py'],
            cwd=os.path.expanduser(
                '~/Downloads/eSim-2.5/src/frontEnd'),
            env=env
        )
        
        wx.MessageBox(
            "eSim launched successfully!\n\n"
            "Your project is ready. Inside eSim:\n"
            "1. Double-click 'esim_bridge_project' in the project tree\n"
            "2. Click 'Simulate'\n"
            "3. Click 'Plot' to see the graph",
            "eSim Bridge - Success!",
            wx.OK | wx.ICON_INFORMATION)
    
    def get_schematic_path(self):
        try:
            board = pcbnew.GetBoard()
            if board:
                project_path = board.GetFileName()
                if project_path:
                    sch_path = project_path.replace('.kicad_pcb', '.kicad_sch')
                    if os.path.exists(sch_path):
                        return sch_path
        except:
            pass
        
        dialog = wx.FileDialog(
            None,
            "Select KiCad Schematic File",
            wildcard="KiCad Schematic (*.kicad_sch)|*.kicad_sch",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        )
        
        if dialog.ShowModal() == wx.ID_OK:
            return dialog.GetPath()
        
        return None
    
    def export_netlist(self, schematic_path, output_path):
        try:
            command = [
                'kicad-cli', 'sch', 'export', 'netlist',
                '--output', output_path,
                '--format', 'kicadsexpr',
                schematic_path
            ]
            
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0 and os.path.exists(output_path):
                return True
            else:
                print(f"kicad-cli error: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("Error: kicad-cli timed out")
            return False
        except FileNotFoundError:
            print("Error: kicad-cli not found")
            return False
        except Exception as e:
            print(f"Error: {e}")
            return False


# Register plugin with KiCad
ESimBridgePlugin().register()# esim_bridge.py
# eSim-BRIDGE v2.1.0 - eSim One-Click Simulation Bridge
# Enhanced with comprehensive component model library + external model loading

import pcbnew
import wx
import os
import subprocess
import re
import shutil
import logging
import random
import traceback
import tempfile
from datetime import datetime
import xml.etree.ElementTree as _ET
import struct

# ══════════════════════════════════════════════════════════════════════
# EXTERNAL MODEL LOADER - Scan user folder for .lib/.model/.subckt files
# ══════════════════════════════════════════════════════════════════════

class ExternalModelLoader:
    """
    Scans a user-specified folder for SPICE model files (.lib, .mod, .sub, .spice, .txt).
    Users simply drop manufacturer-provided model files into the folder,
    and eSim-BRIDGE automatically finds and includes them during simulation.
    
    This gives the plugin infinite scalability - no code changes needed
    to support new components.
    
    Folder structure example:
        ~/.esim-bridge/models/
        ├── 2N2222.lib          (BJT model)
        ├── TL072.lib           (op-amp subcircuit)
        ├── IRF540.spice        (MOSFET model)
        └── my_custom_ic.sub    (user's custom subcircuit)
    """
    
    # Default folder where users put their model files
    DEFAULT_MODEL_DIR = os.path.expanduser('~/.esim-bridge/models')
    
    def __init__(self, model_dir=None):
        self.model_dir = model_dir or self.DEFAULT_MODEL_DIR
        
        # Parsed models and subcircuits from external files
        # Format: {clean_name: {name, definition, source_file, type}}
        self.external_models = {}
        self.external_subcircuits = {}
        
        # Supported file extensions
        self.SUPPORTED_EXTENSIONS = ('.lib', '.mod', '.sub', '.spice', '.txt', '.cir', '.model')
        
        # Ensure the model directory exists (create it for first-time users)
        self._ensure_model_dir()
        
        # Scan and load all model files
        self._scan_model_directory()
    
    def _ensure_model_dir(self):
        """Create the model directory if it doesn't exist, with a README."""
        if not os.path.exists(self.model_dir):
            try:
                os.makedirs(self.model_dir, exist_ok=True)
                
                # Create a helpful README for first-time users
                readme_path = os.path.join(self.model_dir, 'README.txt')
                with open(readme_path, 'w') as f:
                    f.write(
                        "eSim-BRIDGE External SPICE Model Library\n"
                        "======================================\n\n"
                        "Drop your SPICE model files here!\n\n"
                        "Supported file types: .lib, .mod, .sub, .spice, .txt, .cir, .model\n\n"
                        "How to use:\n"
                        "1. Download a SPICE model from a manufacturer website\n"
                        "   (TI, Analog Devices, NXP, ON Semi, etc.)\n"
                        "2. Save the file in this folder\n"
                        "3. Run eSim-BRIDGE - it will automatically find and use the model\n\n"
                        "The file can contain .model or .subckt definitions.\n"
                        "eSim-BRIDGE will parse them automatically.\n\n"
                        "Example .model file content:\n"
                        "  .model 2N2222 NPN(Is=14.34f Bf=255.9 Vaf=74.03)\n\n"
                        "Example .subckt file content:\n"
                        "  .subckt TL072 inp inn out vcc vee\n"
                        "  ... (circuit definition) ...\n"
                        "  .ends TL072\n"
                    )
            except Exception as e:
                print(f"Could not create model directory: {e}")
    
    def _scan_model_directory(self):
        """Scan the model folder and parse all model files."""
        if not os.path.exists(self.model_dir):
            return
        
        for root, dirs, files in os.walk(self.model_dir):
            for filename in files:
                # Skip non-model files
                if not filename.lower().endswith(self.SUPPORTED_EXTENSIONS):
                    continue
                
                filepath = os.path.join(root, filename)
                try:
                    self._parse_model_file(filepath)
                except Exception as e:
                    print(f"Warning: Could not parse model file {filepath}: {e}")
    
    def _parse_model_file(self, filepath):
        """
        Parse a single SPICE model file and extract all .model and .subckt definitions.
        
        A single file can contain multiple models/subcircuits.
        """
        with open(filepath, 'r', errors='ignore') as f:
            content = f.read()
        
        filename = os.path.basename(filepath)
        
        # ── Parse .model definitions ──
        # Pattern: .model <name> <type>(<params>)
        # Can span multiple lines with + continuation
        model_pattern = re.compile(
            r'^\s*\.model\s+(\S+)\s+(NPN|PNP|NMOS|PMOS|D|NJF|PJF|NMOS|PMOS)\s*\(([^)]*)\)',
            re.MULTILINE | re.IGNORECASE
        )
        
        for match in model_pattern.finditer(content):
            model_name = match.group(1)
            model_type = match.group(2).upper()
            model_params = match.group(3)
            
            # Reconstruct the full .model line
            full_definition = f".model {model_name} {model_type}({model_params})"
            
            # Store with clean lookup key
            clean_key = re.sub(r'[^a-z0-9]', '', model_name.lower())
            
            self.external_models[clean_key] = {
                'name': model_name,
                'definition': full_definition,
                'type': model_type,
                'source_file': filename
            }
        
        # ── Parse .subckt definitions ──
        # Pattern: .subckt <name> <nodes...> \n ... \n .ends [name]
        subckt_pattern = re.compile(
            r'(^\s*\.subckt\s+(\S+)\s+.*?^\s*\.ends\b[^\n]*)',
            re.MULTILINE | re.IGNORECASE | re.DOTALL
        )
        
        for match in subckt_pattern.finditer(content):
            full_subckt = match.group(1).strip()
            subckt_name = match.group(2)
            
            clean_key = re.sub(r'[^a-z0-9]', '', subckt_name.lower())
            
            self.external_subcircuits[clean_key] = {
                'name': subckt_name,
                'definition': full_subckt,
                'source_file': filename
            }
    
    def find_model(self, component_value, description=''):
        """
        Search external models for a match.
        
        Args:
            component_value: The component's value field from KiCad (e.g., "2N2222", "TL072")
            description: Additional description text to help matching
        
        Returns:
            (model_name, model_definition, model_type) or (None, None, None)
        """
        search = (component_value + ' ' + description).lower()
        search_clean = re.sub(r'[^a-z0-9]', '', search)
        
        # Try matching against external .model definitions
        for clean_key, model_data in self.external_models.items():
            if clean_key in search_clean or search_clean in clean_key:
                return (
                    model_data['name'],
                    model_data['definition'],
                    model_data['type']
                )
        
        return None, None, None
    
    def find_subcircuit(self, component_value, description=''):
        """
        Search external subcircuits for a match.
        
        Args:
            component_value: The component's value field from KiCad
            description: Additional description text
        
        Returns:
            (subckt_name, subckt_definition) or (None, None)
        """
        search = (component_value + ' ' + description).lower()
        search_clean = re.sub(r'[^a-z0-9]', '', search)
        
        for clean_key, subckt_data in self.external_subcircuits.items():
            if clean_key in search_clean or search_clean in clean_key:
                return subckt_data['name'], subckt_data['definition']
        
        return None, None
    
    def get_stats(self):
        """Return a summary of loaded external models."""
        return {
            'model_dir': self.model_dir,
            'dir_exists': os.path.exists(self.model_dir),
            'num_models': len(self.external_models),
            'num_subcircuits': len(self.external_subcircuits),
            'models': list(self.external_models.keys()),
            'subcircuits': list(self.external_subcircuits.keys()),
        }
    
    def get_summary_text(self):
        """Return a human-readable summary for the UI."""
        stats = self.get_stats()
        if not stats['dir_exists']:
            return f"External model folder not found: {self.model_dir}"
        
        total = stats['num_models'] + stats['num_subcircuits']
        if total == 0:
            return (
                f"External model folder: {self.model_dir}\n"
                f"No external models found. Drop .lib files here to add more components."
            )
        
        return (
            f"External model folder: {self.model_dir}\n"
            f"Loaded: {stats['num_models']} device models, "
            f"{stats['num_subcircuits']} subcircuits"
        )


# ══════════════════════════════════════════════════════════════════════
# MODEL LIBRARY - Auto-injected SPICE models for common components
# ══════════════════════════════════════════════════════════════════════

class SPICEModelLibrary:
    """
    Built-in SPICE model library for common components.
    When eSim-BRIDGE encounters a component, it looks up the model here
    and auto-injects the .model or .subckt definition into the SPICE file.
    
    This eliminates the need for users to manually add model files.
    """
    
    # ── DIODE MODELS ────────────────────────────────────────────────
    DIODE_MODELS = {
        # Generic / fallback
        'default':    '.model DDEFAULT D(Is=1e-14 N=1.0 Rs=0 Cjo=10p Bv=100 Ibv=100u)',
        'dled':       '.model DLED D(Is=2.52e-9 N=1.752 Rs=0.568 Cjo=825p Bv=30 Ibv=10u)',
        'dgeneric':   '.model DGENERIC D(Is=1e-14 N=1.0 Rs=0 Cjo=10p Bv=100 Ibv=100u)',
        
        # Common signal diodes
        '1n4148':     '.model D1N4148 D(Is=2.52e-9 Rs=0.568 N=1.752 Bv=100 Ibv=100u Cjo=4p M=0.4 tt=5.76n)',
        '1n4007':     '.model D1N4007 D(Is=7.02e-9 Rs=0.0341 N=1.8 Bv=1000 Ibv=5u Cjo=26.5p M=0.35 tt=4.32u)',
        '1n4001':     '.model D1N4001 D(Is=29.5e-9 Rs=0.073 N=1.96 Bv=50 Ibv=5u Cjo=26.5p M=0.35)',
        '1n4002':     '.model D1N4002 D(Is=29.5e-9 Rs=0.073 N=1.96 Bv=100 Ibv=5u Cjo=26.5p M=0.35)',
        '1n4003':     '.model D1N4003 D(Is=29.5e-9 Rs=0.073 N=1.96 Bv=200 Ibv=5u Cjo=26.5p M=0.35)',
        '1n4004':     '.model D1N4004 D(Is=29.5e-9 Rs=0.073 N=1.96 Bv=400 Ibv=5u Cjo=26.5p M=0.35)',
        '1n5819':     '.model D1N5819 D(Is=40.7e-9 Rs=0.042 N=1.2 Bv=40 Ibv=1m Cjo=110p)',
        '1n5817':     '.model D1N5817 D(Is=31.7e-9 Rs=0.051 N=1.1 Bv=20 Ibv=1m Cjo=110p)',
        
        # Zener diodes
        'bzt52c3v3':  '.model DBZT52C3V3 D(Is=1e-14 N=1.0 Rs=10 Bv=3.3 Ibv=5m Cjo=50p)',
        'bzt52c5v1':  '.model DBZT52C5V1 D(Is=1e-14 N=1.0 Rs=10 Bv=5.1 Ibv=5m Cjo=50p)',
        '1n4733':     '.model D1N4733 D(Is=1e-14 N=1.0 Rs=10 Bv=5.1 Ibv=20m Cjo=100p)',
        '1n4740':     '.model D1N4740 D(Is=1e-14 N=1.0 Rs=10 Bv=10 Ibv=20m Cjo=100p)',
        '1n4742':     '.model D1N4742 D(Is=1e-14 N=1.0 Rs=10 Bv=12 Ibv=20m Cjo=100p)',
        '1n4744':     '.model D1N4744 D(Is=1e-14 N=1.0 Rs=10 Bv=15 Ibv=20m Cjo=100p)',
        
        # LEDs
        'led':        '.model DLED D(Is=2.52e-9 N=1.752 Rs=0.568 Cjo=825p Bv=30 Ibv=10u)',
        'led_red':    '.model DLED_RED D(Is=9.3e-10 N=3.0 Rs=1.5 Cjo=15p Bv=5 Ibv=10u)',
        'led_green':  '.model DLED_GREEN D(Is=2.3e-10 N=3.2 Rs=2.0 Cjo=15p Bv=5 Ibv=10u)',
        'led_blue':   '.model DLED_BLUE D(Is=5.4e-11 N=3.5 Rs=3.0 Cjo=15p Bv=5 Ibv=10u)',
    }
    
    # ── BJT TRANSISTOR MODELS ───────────────────────────────────────
    BJT_MODELS = {
        # Generic fallback
        'npn_default': '.model QNPN_DEFAULT NPN(Is=1e-15 Bf=100 Vaf=100 Cjc=10p Cje=15p Rb=100 Tf=0.3n)',
        'pnp_default': '.model QPNP_DEFAULT PNP(Is=1e-15 Bf=100 Vaf=100 Cjc=10p Cje=15p Rb=100 Tf=0.3n)',
        
        # Common NPN transistors
        '2n2222':     '.model Q2N2222 NPN(Is=14.34e-15 Bf=255.9 Vaf=74.03 Ikf=0.2847 Ise=14.34e-15 Ne=1.307 Br=6.092 Var=28 Ikr=0 Isc=0 Nc=2 Rb=10 Rc=1 Cjc=7.306p Mjc=0.3416 Vjc=0.75 Cje=22.01p Mje=0.377 Vje=0.75 Tf=0.345n Tr=46.91n)',
        '2n3904':     '.model Q2N3904 NPN(Is=6.734e-15 Bf=416.4 Vaf=74.03 Ikf=66.78e-3 Ise=6.734e-15 Ne=1.259 Br=0.7389 Var=28 Ikr=0 Isc=0 Nc=2 Rb=10 Rc=1 Cjc=3.638p Mjc=0.3085 Vjc=0.75 Cje=4.493p Mje=0.2593 Vje=0.75 Tf=0.301n Tr=239.5n)',
        '2n3906':     '.model Q2N3906 PNP(Is=1.41e-15 Bf=180.7 Vaf=18.7 Ikf=80e-3 Ise=0 Ne=1.5 Br=4.977 Var=100 Ikr=0 Isc=0 Nc=2 Rb=10 Rc=2.5 Cjc=9.728p Mjc=0.5776 Vjc=0.75 Cje=8.063p Mje=0.3677 Vje=0.75 Tf=0.3n Tr=50n)',
        'bc547':      '.model QBC547 NPN(Is=1.8e-14 Bf=400 Vaf=80 Ikf=0.1 Ise=5e-14 Ne=1.46 Br=35.5 Var=12.5 Ikr=0.01 Rb=10 Rc=1 Cjc=5.25p Cje=11.5p Tf=0.64n Tr=50n)',
        'bc547b':     '.model QBC547B NPN(Is=1.8e-14 Bf=400 Vaf=80 Ikf=0.1 Ise=5e-14 Ne=1.46 Br=35.5 Var=12.5 Ikr=0.01 Rb=10 Rc=1 Cjc=5.25p Cje=11.5p Tf=0.64n Tr=50n)',
        'bc548':      '.model QBC548 NPN(Is=1.95e-14 Bf=400 Vaf=80 Ikf=0.08 Ise=5e-14 Ne=1.46 Br=35.5 Var=12.5 Rb=10 Rc=1 Cjc=5.25p Cje=11.5p Tf=0.64n Tr=50n)',
        'bc557':      '.model QBC557 PNP(Is=2e-14 Bf=290 Vaf=60 Ikf=0.1 Ise=5e-14 Ne=1.46 Br=20 Var=12.5 Rb=10 Rc=1 Cjc=7.5p Cje=12.5p Tf=0.6n Tr=50n)',
        'bc558':      '.model QBC558 PNP(Is=2e-14 Bf=290 Vaf=60 Ikf=0.1 Rb=10 Rc=1 Cjc=7.5p Cje=12.5p Tf=0.6n Tr=50n)',
        '2n2907':     '.model Q2N2907 PNP(Is=650.6e-18 Bf=231.7 Vaf=116.1 Ikf=0.1856 Ise=54.81e-15 Ne=1.829 Br=3.563 Var=100 Ikr=0 Isc=0 Nc=2 Rb=10 Rc=1 Cjc=14.76p Cje=19.82p Tf=0.5n Tr=50n)',
        '2n2219':     '.model Q2N2219 NPN(Is=14.34e-15 Bf=200 Vaf=74 Ikf=0.28 Rb=10 Rc=1 Cjc=7.3p Cje=22p Tf=0.35n Tr=47n)',
        'tip31':      '.model QTIP31 NPN(Is=2e-12 Bf=60 Vaf=100 Ikf=3 Rb=5 Rc=0.1 Cjc=50p Cje=100p Tf=10n Tr=500n)',
        'tip32':      '.model QTIP32 PNP(Is=2e-12 Bf=60 Vaf=100 Ikf=3 Rb=5 Rc=0.1 Cjc=50p Cje=100p Tf=10n Tr=500n)',
    }
    
    # ── MOSFET MODELS ───────────────────────────────────────────────
    MOSFET_MODELS = {
        # Generic fallback
        'nmos_default': '.model MNMOS_DEFAULT NMOS(Level=1 Vto=0.7 Kp=110u W=10u L=1u)',
        'pmos_default': '.model MPMOS_DEFAULT PMOS(Level=1 Vto=-0.7 Kp=50u W=10u L=1u)',
        
        # Common MOSFETs
        'irf540':     '.model MIRF540 NMOS(Level=3 Vto=3.0 Kp=20.43 Rs=0.0768 Rd=0.2 Cbd=1.36n Cgso=1.95n Cgdo=0.13n)',
        'irf540n':    '.model MIRF540N NMOS(Level=3 Vto=3.0 Kp=20.43 Rs=0.0768 Rd=0.2 Cbd=1.36n Cgso=1.95n Cgdo=0.13n)',
        'irf9540':    '.model MIRF9540 PMOS(Level=3 Vto=-3.0 Kp=10.2 Rs=0.12 Rd=0.3 Cbd=1.36n Cgso=1.95n Cgdo=0.13n)',
        'irf3205':    '.model MIRF3205 NMOS(Level=3 Vto=2.0 Kp=40 Rs=0.008 Rd=0.1 Cbd=3.6n Cgso=3.2n Cgdo=0.2n)',
        'irf830':     '.model MIRF830 NMOS(Level=3 Vto=3.0 Kp=5.0 Rs=0.4 Rd=1.0 Cbd=0.5n Cgso=0.8n Cgdo=0.1n)',
        '2n7000':     '.model M2N7000 NMOS(Level=3 Vto=2.0 Kp=0.15 Rs=5.0 Rd=1.5 Cbd=35p Cgso=40p Cgdo=5p)',
        '2n7002':     '.model M2N7002 NMOS(Level=3 Vto=1.8 Kp=0.15 Rs=5.0 Rd=1.5 Cbd=35p Cgso=40p Cgdo=5p)',
        'bs170':      '.model MBS170 NMOS(Level=3 Vto=1.5 Kp=0.12 Rs=5.0 Rd=2.0 Cbd=30p Cgso=35p Cgdo=5p)',
        'bs250':      '.model MBS250 PMOS(Level=3 Vto=-2.0 Kp=0.06 Rs=8.0 Rd=3.0 Cbd=30p Cgso=35p Cgdo=5p)',
    }
    
    # ── OP-AMP SUBCIRCUITS ──────────────────────────────────────────
    OPAMP_SUBCIRCUITS = {
        'lm741': (
            '.subckt LM741 inp inn out vcc vee\n'
            '* Simplified LM741 op-amp subcircuit\n'
            'Rin inp inn 2Meg\n'
            'Egain mid 0 inp inn 200000\n'
            'Rout mid out 75\n'
            'Icc vcc vee 1.7m\n'
            '.ends LM741'
        ),
        'ua741': (
            '.subckt UA741 inp inn out vcc vee\n'
            '* Simplified UA741 op-amp subcircuit\n'
            'Rin inp inn 2Meg\n'
            'Egain mid 0 inp inn 200000\n'
            'Rout mid out 75\n'
            'Icc vcc vee 1.7m\n'
            '.ends UA741'
        ),
        'lm358': (
            '.subckt LM358 inp inn out vcc vee\n'
            '* Simplified LM358 op-amp subcircuit\n'
            'Rin inp inn 1Meg\n'
            'Egain mid 0 inp inn 100000\n'
            'Rout mid out 150\n'
            'Icc vcc vee 0.5m\n'
            '.ends LM358'
        ),
        'lm324': (
            '.subckt LM324 inp inn out vcc vee\n'
            '* Simplified LM324 op-amp subcircuit\n'
            'Rin inp inn 1Meg\n'
            'Egain mid 0 inp inn 100000\n'
            'Rout mid out 150\n'
            'Icc vcc vee 0.5m\n'
            '.ends LM324'
        ),
        'ne555': (
            '.subckt NE555 gnd trigger output reset control threshold discharge vcc\n'
            '* Simplified 555 timer subcircuit (astable behavior)\n'
            'Rctrl vcc control 5k\n'
            'Rctrl2 control gnd 10k\n'
            '.ends NE555'
        ),
        'opamp_generic': (
            '.subckt OPAMP_GENERIC inp inn out vcc vee\n'
            '* Generic ideal op-amp subcircuit\n'
            'Rin inp inn 10Meg\n'
            'Egain mid 0 inp inn 1000000\n'
            'Rout mid out 10\n'
            '.ends OPAMP_GENERIC'
        ),
    }
    
    # ── VOLTAGE REGULATOR SUBCIRCUITS ───────────────────────────────
    REGULATOR_SUBCIRCUITS = {
        '7805': (
            '.subckt REG7805 in out gnd\n'
            '* Simplified 7805 5V regulator\n'
            'Rin in mid 1\n'
            'Vreg mid out DC 0\n'
            'Breg out gnd V=min(max(V(in,gnd)-2, 0), 5)\n'
            'Rload out gnd 100k\n'
            '.ends REG7805'
        ),
        '7812': (
            '.subckt REG7812 in out gnd\n'
            '* Simplified 7812 12V regulator\n'
            'Rin in mid 1\n'
            'Vreg mid out DC 0\n'
            'Breg out gnd V=min(max(V(in,gnd)-2, 0), 12)\n'
            'Rload out gnd 100k\n'
            '.ends REG7812'
        ),
        '7833': (
            '.subckt REG7833 in out gnd\n'
            '* Simplified 78L33 3.3V regulator\n'
            'Rin in mid 1\n'
            'Vreg mid out DC 0\n'
            'Breg out gnd V=min(max(V(in,gnd)-1.5, 0), 3.3)\n'
            'Rload out gnd 100k\n'
            '.ends REG7833'
        ),
    }
    
    @classmethod
    def lookup_diode_model(cls, value, description=''):
        """
        Find the best matching diode model.
        Returns (model_name, model_definition) tuple.
        """
        search = (value + ' ' + description).lower()
        search = re.sub(r'[^a-z0-9]', '', search)
        
        # Try exact match first
        for key, model_def in cls.DIODE_MODELS.items():
            clean_key = re.sub(r'[^a-z0-9]', '', key)
            if clean_key in search or search in clean_key:
                model_name = model_def.split()[1]  # Extract model name from .model line
                return model_name, model_def
        
        # Check if it's an LED
        if any(kw in search for kw in ['led', 'lightemit']):
            return 'DLED', cls.DIODE_MODELS['dled']
        
        # Check if it's a Zener
        if any(kw in search for kw in ['zener', 'bzt', 'bzx']):
            return 'DBZT52C5V1', cls.DIODE_MODELS['bzt52c5v1']
        
        # Fallback to generic diode
        return 'DDEFAULT', cls.DIODE_MODELS['default']
    
    @classmethod
    def lookup_bjt_model(cls, value, description=''):
        """
        Find the best matching BJT model.
        Returns (model_name, model_definition, is_npn) tuple.
        """
        search = (value + ' ' + description).lower()
        search = re.sub(r'[^a-z0-9]', '', search)
        
        # Try exact match
        for key, model_def in cls.BJT_MODELS.items():
            clean_key = re.sub(r'[^a-z0-9]', '', key)
            if clean_key in search or search in clean_key:
                model_name = model_def.split()[1]
                is_npn = 'NPN' in model_def
                return model_name, model_def, is_npn
        
        # Detect PNP from description
        if any(kw in search for kw in ['pnp', '2n3906', '2n2907', 'bc557', 'bc558', 'tip32']):
            return 'QPNP_DEFAULT', cls.BJT_MODELS['pnp_default'], False
        
        # Default to NPN
        return 'QNPN_DEFAULT', cls.BJT_MODELS['npn_default'], True
    
    @classmethod
    def lookup_mosfet_model(cls, value, description=''):
        """
        Find the best matching MOSFET model.
        Returns (model_name, model_definition, is_nmos) tuple.
        """
        search = (value + ' ' + description).lower()
        search = re.sub(r'[^a-z0-9]', '', search)
        
        # Try exact match
        for key, model_def in cls.MOSFET_MODELS.items():
            clean_key = re.sub(r'[^a-z0-9]', '', key)
            if clean_key in search or search in clean_key:
                model_name = model_def.split()[1]
                is_nmos = 'NMOS' in model_def
                return model_name, model_def, is_nmos
        
        # Detect PMOS from description
        if any(kw in search for kw in ['pmos', 'pchannel', 'p-channel', 'irf9', 'bs250']):
            return 'MPMOS_DEFAULT', cls.MOSFET_MODELS['pmos_default'], False
        
        # Default to NMOS
        return 'MNMOS_DEFAULT', cls.MOSFET_MODELS['nmos_default'], True
    
    @classmethod
    def lookup_opamp_subcircuit(cls, value, description=''):
        """
        Find the best matching op-amp subcircuit.
        Returns (subckt_name, subckt_definition) or (None, None).
        """
        search = (value + ' ' + description).lower()
        search = re.sub(r'[^a-z0-9]', '', search)
        
        for key, subckt_def in cls.OPAMP_SUBCIRCUITS.items():
            clean_key = re.sub(r'[^a-z0-9]', '', key)
            if clean_key in search or search in clean_key:
                # Extract subcircuit name from .subckt line
                subckt_name = subckt_def.split('\n')[0].split()[1]
                return subckt_name, subckt_def
        
        # Check for generic op-amp keywords
        if any(kw in search for kw in ['opamp', 'op_amp', 'operational']):
            subckt_name = 'OPAMP_GENERIC'
            return subckt_name, cls.OPAMP_SUBCIRCUITS['opamp_generic']
        
        return None, None
    
    @classmethod
    def lookup_regulator_subcircuit(cls, value, description=''):
        """
        Find voltage regulator subcircuit.
        Returns (subckt_name, subckt_definition) or (None, None).
        """
        search = (value + ' ' + description).lower()
        search = re.sub(r'[^a-z0-9]', '', search)
        
        for key, subckt_def in cls.REGULATOR_SUBCIRCUITS.items():
            clean_key = re.sub(r'[^a-z0-9]', '', key)
            if clean_key in search or search in clean_key:
                subckt_name = subckt_def.split('\n')[0].split()[1]
                return subckt_name, subckt_def
        
        return None, None


# ══════════════════════════════════════════════════════════════════════
# SPICE CONVERTER - Enhanced with model library integration
# ══════════════════════════════════════════════════════════════════════

class SPICEConverter:
    """
    Converts KiCad netlist data into a SPICE deck (.cir file)
    that Ngspice/eSim can simulate.
    
    v2.1: Built-in models + external user-provided model library.
    """
    
    def __init__(self):
        self.supported_types = {
            'R': 'resistor',
            'C': 'capacitor', 
            'L': 'inductor',
            'V': 'voltage_source',
            'I': 'current_source',
            'D': 'diode',
            'Q': 'bjt_transistor',
            'M': 'mosfet',
            'J': 'jfet',
            'U': 'ic_subcircuit',
            'X': 'subcircuit',
            'SW': 'switch',
            'S': 'vswitch',
        }
        
        # Track which models need to be injected
        self.required_models = {}      # {model_name: model_definition}
        self.required_subcircuits = {}  # {subckt_name: subckt_definition}
        self.unsupported_components = []  # Track what couldn't be converted
        
        # Load external user-provided models
        self.external_loader = ExternalModelLoader()
    
    def convert(self, netlist_path, output_path, analysis_type='tran',
                analysis_params=None):
        """
        Main conversion function.
        """
        try:
            # Reset tracking
            self.required_models = {}
            self.required_subcircuits = {}
            self.unsupported_components = []
            
            # Read and parse the netlist
            components, nets = self.parse_full_netlist(netlist_path)
            
            if not components:
                return False
            
            # Build SPICE content
            spice_lines = []
            
            # Header
            spice_lines.append("* eSim Bridge Plugin - Auto-generated SPICE file")
            spice_lines.append(f"* Source: {netlist_path}")
            spice_lines.append(f"* Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            spice_lines.append(f"* eSim Bridge v2.1.0")
            ext_stats = self.external_loader.get_stats()
            spice_lines.append(f"* Built-in models: 47+ | External models: {ext_stats['num_models']} models, {ext_stats['num_subcircuits']} subcircuits")
            spice_lines.append("")
            
            # Component lines
            spice_lines.append("* ── Components ──")
            for ref, comp_data in components.items():
                spice_line = self.component_to_spice(ref, comp_data, nets)
                if spice_line:
                    spice_lines.append(spice_line)
            
            spice_lines.append("")
            
            # Inject all required models
            if self.required_models:
                spice_lines.append("* ── Auto-injected Device Models (by eSim) ──")
                for model_name, model_def in self.required_models.items():
                    spice_lines.append(model_def)
                spice_lines.append("")
            
            # Inject all required subcircuits
            if self.required_subcircuits:
                spice_lines.append("* ── Auto-injected Subcircuits (by eSim) ──")
                for subckt_name, subckt_def in self.required_subcircuits.items():
                    spice_lines.append(subckt_def)
                    spice_lines.append("")
            
            # Warn about unsupported components
            if self.unsupported_components:
                spice_lines.append("* ── Unsupported Components (skipped) ──")
                for warning in self.unsupported_components:
                    spice_lines.append(f"* WARNING: {warning}")
                spice_lines.append("")
            
            # Analysis command
            spice_lines.append("* ── Simulation Analysis ──")
            analysis_cmd = self.get_analysis_command(analysis_type, analysis_params)
            spice_lines.append(analysis_cmd)
            spice_lines.append("")
            
            # Output commands
            spice_lines.append("* ── Output ──")
            output_cmds = self.get_output_commands(nets, analysis_type)
            spice_lines.extend(output_cmds)
            spice_lines.append("")
            
            # End
            spice_lines.append(".end")
            
            # Write to file
            with open(output_path, 'w') as f:
                f.write('\n'.join(spice_lines) + '\n')
            
            return True
            
        except Exception as e:
            print(f"SPICE conversion error: {e}")
            traceback.print_exc()
            return False
    
    def parse_full_netlist(self, netlist_path):
        """
        Parse KiCad netlist file.
        Returns:
            components: {ref: {value, description, pins: {pin_num: net_name}}}
            nets: {net_name: [list of (ref, pin) connections]}
        """
        components = {}
        nets = {}
        
        with open(netlist_path, 'r') as f:
            content = f.read()
        
        # Parse components
        parts = content.split('(comp ')
        
        for part in parts[1:]:
            ref_match = re.search(r'\(ref\s+"([^"]+)"\)', part)
            if not ref_match:
                continue
            ref = ref_match.group(1)
            
            val_match = re.search(r'\(value\s+"([^"]+)"\)', part)
            value = val_match.group(1) if val_match else "?"
            
            desc_match = re.search(r'\(description\s+"([^"]+)"\)', part)
            description = desc_match.group(1) if desc_match else ""
            
            # Extract library name (helps identify component type)
            lib_match = re.search(r'\(lib\s+\(name\s+"([^"]+)"\)', part)
            lib_name = lib_match.group(1) if lib_match else ""
            
            # Extract footprint (can help distinguish packages)
            fp_match = re.search(r'\(footprint\s+"([^"]+)"\)', part)
            footprint = fp_match.group(1) if fp_match else ""
            
            # Sim.Type and Sim.Params for simulation sources
            sim_type_match = re.search(
                r'\(property\s+\(name\s+"Sim\.Type"\)\s+\(value\s+"([^"]+)"\)', part)
            sim_params_match = re.search(
                r'\(property\s+\(name\s+"Sim\.Params"\)\s+\(value\s+"([^"]+)"\)', part)
            
            sim_type = sim_type_match.group(1) if sim_type_match else ""
            sim_params = sim_params_match.group(1) if sim_params_match else ""
            
            # Sim.Name override
            sim_name_match = re.search(
                r'\(property\s+\(name\s+"Sim\.Name"\)\s+\(value\s+"([^"]+)"\)', part)
            sim_name = sim_name_match.group(1) if sim_name_match else ""
            
            components[ref] = {
                'value': value,
                'description': description,
                'lib_name': lib_name,
                'footprint': footprint,
                'sim_type': sim_type,
                'sim_params': sim_params,
                'sim_name': sim_name,
                'pins': {}
            }
        
        # Parse nets
        net_parts = content.split('(net ')
        
        for part in net_parts[1:]:
            name_match = re.search(r'\(name\s+"([^"]+)"\)', part)
            if not name_match:
                continue
            net_name = name_match.group(1)
            
            spice_net = self.clean_net_name(net_name)
            
            nets[net_name] = {
                'spice_name': spice_net,
                'nodes': []
            }
            
            node_matches = re.findall(
                r'\(node\s+\(ref\s+"([^"]+)"\)\s+\(pin\s+"([^"]+)"\)',
                part
            )
            
            for ref, pin in node_matches:
                nets[net_name]['nodes'].append((ref, pin))
                if ref in components:
                    if 'pins' not in components[ref]:
                        components[ref]['pins'] = {}
                    components[ref]['pins'][pin] = spice_net
        
        return components, nets
    
    def clean_net_name(self, net_name):
        """Clean net name for SPICE compatibility"""
        if net_name.upper() in ['GND', 'GROUND', 'VSS', '0']:
            return '0'
        
        cleaned = net_name.lstrip('/')
        cleaned = re.sub(r'[^a-zA-Z0-9]', '_', cleaned)
        cleaned = re.sub(r'_+', '_', cleaned)
        cleaned = cleaned.strip('_')
        cleaned = cleaned[:20]
        
        if not cleaned or cleaned[0].isdigit():
            cleaned = 'N' + cleaned
        
        return cleaned
    
    def component_to_spice(self, ref, comp_data, nets):
        """
        Convert a single component to its SPICE line.
        Now with automatic model lookup and injection.
        """
        if not ref:
            return None
        
        prefix = ref[0].upper()
        value = comp_data.get('value', '?')
        description = comp_data.get('description', '')
        lib_name = comp_data.get('lib_name', '')
        pins = comp_data.get('pins', {})
        
        # Get nodes in pin order
        sorted_pins = sorted(pins.keys(),
                           key=lambda x: int(x) if x.isdigit() else 0)
        nodes = [pins[p] for p in sorted_pins]
        
        # Pad with GND if missing pins
        while len(nodes) < 2:
            nodes.append('0')
        
        # ══ MULTI-CHARACTER PREFIX CHECKS (must come first!) ══
        
        # ── MICROPHONE / SENSOR (MK prefix - must check before M) ──        
        if ref.startswith('MK'):
            self.unsupported_components.append(
                f"{ref} ({value}): Microphone modeled as 10mV AC source at 1kHz")
            return f"V{ref} {nodes[1]} {nodes[0]} AC 0.01 SIN(0 0.01 1k)"
        
        # ── BATTERY (BT prefix - must check before B) ──
        elif ref.startswith('BT'):
            voltage = self._extract_numeric_value(value, default='3.7')
            return f"V{ref} {nodes[0]} {nodes[1]} DC {voltage}"
        
        # ── SWITCH (SW prefix - must check before S) ──
        elif ref.startswith('SW'):
            self.unsupported_components.append(
                f"{ref} ({value}): Switch converted to 1 ohm resistor (closed state)")
            return f"R{ref} {nodes[0]} {nodes[1]} 1"
        
        # ══ SINGLE-CHARACTER PREFIX CHECKS ══
        
        # ── RESISTOR ──        
        elif prefix == 'R':
            sanitized = re.sub(r'\s+.*', '', value)  # strip everything after first space
            if not re.match(r'^[\d.]+([rRkKmMgGuUnNpPfFtT]|meg|Meg|MEG)?$', sanitized):
                sanitized = '1k'  # fallback for "5mm LDR", "5mm", etc.
            return f"{ref} {nodes[0]} {nodes[1]} {sanitized}"
        
        # ── CAPACITOR ──
        elif prefix == 'C':
            return f"{ref} {nodes[0]} {nodes[1]} {value}"
        
        # ── INDUCTOR ──
        elif prefix == 'L':
            return f"{ref} {nodes[0]} {nodes[1]} {value}"
        
        # ── VOLTAGE SOURCE ──
        elif prefix == 'V':
            return self._convert_voltage_source(ref, comp_data, nodes)
        
        # ── CURRENT SOURCE ──
        elif prefix == 'I':
            return f"{ref} {nodes[0]} {nodes[1]} DC {value}"
        
        # ── DIODE / LED ──
        elif prefix == 'D':
            # Try external user models first, then built-in
            ext_name, ext_def, ext_type = self.external_loader.find_model(
                value, description + ' ' + lib_name)
            if ext_name and ext_type == 'D':
                model_name, model_def = ext_name, ext_def
            else:
                model_name, model_def = SPICEModelLibrary.lookup_diode_model(
                    value, description + ' ' + lib_name)
            self.required_models[model_name] = model_def
            
            # KiCad LED/Diode: pin1=Cathode(K), pin2=Anode(A)
            # SPICE diode: D<name> <anode> <cathode> <model>
            anode = nodes[1] if len(nodes) > 1 else nodes[0]
            cathode = nodes[0]
            return f"{ref} {anode} {cathode} {model_name}"
        
        # ── BJT TRANSISTOR ──
        elif prefix == 'Q':
            # Try external user models first, then built-in
            ext_name, ext_def, ext_type = self.external_loader.find_model(
                value, description + ' ' + lib_name)
            if ext_name and ext_type in ('NPN', 'PNP'):
                model_name, model_def = ext_name, ext_def
                is_npn = ext_type == 'NPN'
            else:
                model_name, model_def, is_npn = SPICEModelLibrary.lookup_bjt_model(
                    value, description + ' ' + lib_name)
            self.required_models[model_name] = model_def
            
            # Ensure we have 3 nodes: collector, base, emitter
            while len(nodes) < 3:
                nodes.append('0')
            

            # BC547 KiCad: pin1=Collector, pin2=Base, pin3=Emitter
            # SPICE BJT: Q<name> <collector> <base> <emitter> <model>
            collector = nodes[0]   # pin 1 = Collector
            base      = nodes[1]   # pin 2 = Base
            emitter   = nodes[2] if len(nodes) > 2 else '0'   # pin 3 = Emitter
            return f"{ref} {collector} {base} {emitter} {model_name}"
        
        # ── MOSFET ──
        elif prefix == 'M':
            # Try external user models first, then built-in
            ext_name, ext_def, ext_type = self.external_loader.find_model(
                value, description + ' ' + lib_name)
            if ext_name and ext_type in ('NMOS', 'PMOS'):
                model_name, model_def = ext_name, ext_def
                is_nmos = ext_type == 'NMOS'
            else:
                model_name, model_def, is_nmos = SPICEModelLibrary.lookup_mosfet_model(
                    value, description + ' ' + lib_name)
            self.required_models[model_name] = model_def
            
            # Ensure 4 nodes: drain, gate, source, bulk
            while len(nodes) < 4:
                nodes.append('0')
            
            # KiCad typical: 1=Gate, 2=Drain, 3=Source
            # SPICE: M<name> <drain> <gate> <source> <bulk> <model>
            drain = nodes[1] if len(nodes) > 1 else nodes[0]
            gate = nodes[0]
            source = nodes[2] if len(nodes) > 2 else '0'
            bulk = nodes[3] if len(nodes) > 3 else source
            return f"{ref} {drain} {gate} {source} {bulk} {model_name}"
        
        # ── JFET ──
        elif prefix == 'J':
            # JFET: J<name> <drain> <gate> <source> <model>
            while len(nodes) < 3:
                nodes.append('0')
            # Try external user models first
            ext_name, ext_def, ext_type = self.external_loader.find_model(
                value, description + ' ' + lib_name)
            if ext_name and ext_type in ('NJF', 'PJF'):
                model_name, model_def = ext_name, ext_def
            else:
                model_name = 'JNFET_DEFAULT'
                model_def = '.model JNFET_DEFAULT NJF(Vto=-2.0 Beta=1.304m Lambda=2.25m Rd=0 Rs=0 Cgs=3.1p Cgd=1.6p Is=33.57f)'
            self.required_models[model_name] = model_def
            return f"{ref} {nodes[0]} {nodes[1]} {nodes[2]} {model_name}"
        
        # ── IC / SUBCIRCUIT (U prefix) ──
        elif prefix == 'U' or prefix == 'X':
            return self._convert_ic_subcircuit(ref, comp_data, nodes)
        
        # ── VOLTAGE-CONTROLLED SWITCH (S prefix, not SW) ──
        elif prefix == 'S':
            self.unsupported_components.append(
                f"{ref} ({value}): Switch converted to 1 ohm resistor (closed state)")
            return f"R{ref} {nodes[0]} {nodes[1]} 1"
        
        # ── FUSE ──
        elif prefix == 'F':
            # Fuse - model as small resistance
            return f"R{ref} {nodes[0]} {nodes[1]} 0.01"
        
        # ── TRANSFORMER ──
        elif prefix == 'T':
            self.unsupported_components.append(
                f"{ref} ({value}): Transformer needs manual .subckt definition")
            return f"* TRANSFORMER {ref}: needs .subckt - {value}"
        
        # ── UNKNOWN ──
        else:
            node_str = ' '.join(nodes)
            self.unsupported_components.append(
                f"{ref} ({value}): Unknown component type '{prefix}'")
            return f"* UNKNOWN: {ref} {node_str} {value}"
    
    def _convert_voltage_source(self, ref, comp_data, nodes):
        """Handle voltage source conversion with all source types"""
        value = comp_data.get('value', '5')
        sim_type = comp_data.get('sim_type', '')
        sim_params = comp_data.get('sim_params', '')
        
        if sim_type == 'SIN' and sim_params:
            params = {}
            for p in sim_params.split():
                if '=' in p:
                    k, v = p.split('=')
                    params[k] = v
            dc = params.get('dc', '0')
            ampl = params.get('ampl', '1')
            freq = params.get('f', '1k')
            ac = params.get('ac', '1')
            return f"{ref} {nodes[0]} {nodes[1]} AC {ac} SIN({dc} {ampl} {freq})"
        
        elif sim_type == 'PULSE' and sim_params:
            params = {}
            for p in sim_params.split():
                if '=' in p:
                    k, v = p.split('=')
                    params[k] = v
            v1 = params.get('v1', '0')
            v2 = params.get('v2', '5')
            td = params.get('td', '0')
            tr = params.get('tr', '1n')
            tf = params.get('tf', '1n')
            pw = params.get('pw', '5m')
            per = params.get('per', '10m')
            return f"{ref} {nodes[0]} {nodes[1]} PULSE({v1} {v2} {td} {tr} {tf} {pw} {per})"
        
        elif sim_type == 'DC':
            params = {}
            for p in sim_params.split():
                if '=' in p:
                    k, v = p.split('=', 1)
                    params[k.lower()] = v
            dc_val = params.get('dc', '5')
            return f"{ref} {nodes[0]} {nodes[1]} DC {dc_val}"
        
        elif value.upper() in ('VSIN', 'VPULSE', 'VAC', 'VDC'):
            # KiCad symbol name used as value — default to DC 5
            return f"{ref} {nodes[0]} {nodes[1]} DC 5"
        
        elif any(kw in value.upper() for kw in ['DC', 'AC', 'PULSE', 'SIN']):
            return f"{ref} {nodes[0]} {nodes[1]} {value}"
        
        else:
            return f"{ref} {nodes[0]} {nodes[1]} DC {value}"
    
    def _convert_ic_subcircuit(self, ref, comp_data, nodes):
        """Handle IC/subcircuit conversion with model lookup.
        Search order: 1) Built-in library  2) External user models  3) Unsupported"""
        value = comp_data.get('value', '')
        description = comp_data.get('description', '')
        lib_name = comp_data.get('lib_name', '')
        search_text = value + ' ' + description + ' ' + lib_name
        
        # 1) Try built-in op-amp lookup
        subckt_name, subckt_def = SPICEModelLibrary.lookup_opamp_subcircuit(
            value, description)
        if subckt_name:
            self.required_subcircuits[subckt_name] = subckt_def
            node_str = ' '.join(nodes)
            return f"X{ref} {node_str} {subckt_name}"
        
        # 2) Try built-in regulator lookup
        subckt_name, subckt_def = SPICEModelLibrary.lookup_regulator_subcircuit(
            value, description)
        if subckt_name:
            self.required_subcircuits[subckt_name] = subckt_def
            node_str = ' '.join(nodes)
            return f"X{ref} {node_str} {subckt_name}"
        
        # 3) Try external user-provided subcircuit
        subckt_name, subckt_def = self.external_loader.find_subcircuit(
            value, description)
        if subckt_name:
            self.required_subcircuits[subckt_name] = subckt_def
            node_str = ' '.join(nodes)
            return f"X{ref} {node_str} {subckt_name}"
        
        # 4) Try external user-provided model (some ICs use .model instead of .subckt)
        model_name, model_def, model_type = self.external_loader.find_model(
            value, description)
        if model_name:
            self.required_models[model_name] = model_def
            node_str = ' '.join(nodes)
            return f"X{ref} {node_str} {model_name}"
        

        # 5) Check if eSim SPICE can find it in eSim library
        try:
            import sys
            plugin_dir = os.path.dirname(__file__)
            if plugin_dir not in sys.path:
                sys.path.insert(0, plugin_dir)
            from esim_spice_linker import SPICEAutoLinker
            if not hasattr(self, '_pspice_linker'):
                self._pspice_linker = SPICEAutoLinker()
            result = self._pspice_linker.get_model_for_component(ref, value, '')
            if result['status'] in ('esim_subcircuit', 'equivalent'):
                subckt_name = result['model_name']
                subckt_def = result['model_definition']
                self.required_subcircuits[subckt_name] = subckt_def
                # Also inject dependencies
                for dep in result.get('dependencies', []):
                    if dep.get('name') and dep.get('definition'):
                        self.required_models[dep['name']] = dep['definition']
                node_str = ' '.join(nodes)
                return f"X{ref} {node_str} {subckt_name}"
        except Exception:
            pass

        # 6) Nothing found anywhere - report as unsupported
        node_str = ' '.join(nodes)
        self.unsupported_components.append(
            f"{ref} ({value}): IC needs .subckt model - not in built-in or external library. "
            f"Download the SPICE model and save it to: {self.external_loader.model_dir}")
        return f"* UNSUPPORTED IC: {ref} {node_str} {value}"
    
    def _extract_numeric_value(self, value, default='5'):
        """Extract a numeric value from a component value string"""
        match = re.search(r'[\d.]+', value)
        if match:
            return match.group()
        return default
    
    def get_analysis_command(self, analysis_type, params=None):
        """Generate the Ngspice analysis command."""
        if params is None:
            params = {}
        
        if analysis_type == 'tran':
            start = params.get('start', '0')
            step = params.get('step', '1us')
            stop = params.get('stop', '10ms')
            return f".tran {step} {stop} {start}"
        
        elif analysis_type == 'ac':
            scale = params.get('scale', 'dec')
            points = params.get('points', '100')
            fstart = params.get('fstart', '1Hz')
            fstop = params.get('fstop', '1MEGHz')
            return f".ac {scale} {points} {fstart} {fstop}"
        
        elif analysis_type == 'dc':
            source = params.get('source', 'V1')
            start = params.get('start', '0')
            stop = params.get('stop', '5')
            step = params.get('step', '0.1')
            return f".dc {source} {start} {stop} {step}"
        
        elif analysis_type == 'op':
            return ".op"
        

        elif analysis_type == 'noise':
            output = params.get('output', 'out')
            source = params.get('source', 'V1')
            fstart = params.get('fstart', '1')
            fstop  = params.get('fstop', '1Meg')
            points = params.get('points', '100')
            return f".noise v({output}) {source} dec {points} {fstart} {fstop}"
        
        else:
            return ".tran 1us 10ms"
    
    def get_output_commands(self, nets, analysis_type):
        """Generate .print and .probe commands."""
        commands = []
        
        output_nets = [
            data['spice_name'] 
            for name, data in nets.items()
            if data['spice_name'] != '0'
        ]
        
        if not output_nets:
            return [".probe v(*)"]
        

        
        commands.append(".probe v(*)")
        return commands
    
    def get_unsupported_summary(self):
        """Return a summary of unsupported components for the user"""
        if not self.unsupported_components:
            return None
        return "\n".join(self.unsupported_components)
    
    
    def _rewrite_with_models(self, output_path):
        with open(output_path, 'r') as f:
            content = f.read()
        
        # Find model/subckt names already written to the file
        existing = set(re.findall(r'\.model\s+(\S+)', content, re.IGNORECASE))
        existing |= set(re.findall(r'\.subckt\s+(\S+)', content, re.IGNORECASE))
        
        content = content.replace('\n.end\n', '\n')
        
        new_models = {n: d for n, d in self.required_models.items() if n not in existing}
        if new_models:
            content += "\n* ── eSim Library Models (by eSim-SPICE) ──\n"
            for name, defn in new_models.items():
                content += defn + "\n"
        
        new_subcircuits = {n: d for n, d in self.required_subcircuits.items() if n not in existing}
        if new_subcircuits:
            content += "\n* ── eSim Library Subcircuits (by eSim-SPICE) ──\n"
            for name, defn in new_subcircuits.items():
                content += defn + "\n\n"
        
        content += "\n.end\n"
        
        with open(output_path, 'w') as f:
            f.write(content)



# ══════════════════════════════════════════════════════════════════════
# KICAD TO NGSPICE DIALOG - Replaces AnalysisConfigDialog
# Mirrors eSim's 5-tab KicadToNgspice window exactly:
#   Tab 1: Analysis        (AC / DC / Transient / OP)
#   Tab 2: Source Details  (sine/pulse/pwl/ac/dc/exp per source)
#   Tab 3: Ngspice Model   (U-prefix analog/digital behavioral models via XML)
#   Tab 4: Device Modeling (file picker for Q/D/J/M/S components)
#   Tab 5: Subcircuits     (directory picker for X-prefix components)
#
# HOW TO INTEGRATE:
#   1. Delete the entire AnalysisConfigDialog class from esim_bridge.py
#   2. Paste this entire file's content in its place
#   3. In Run(), replace the AnalysisConfigDialog block with the
#      NEW RUN FLOW shown at the bottom of this file
# ══════════════════════════════════════════════════════════════════════




class KicadToNgspiceDialog(wx.Dialog):
    """
    Single tabbed dialog mirroring eSim's KicadToNgspice window.
    Must be created AFTER the netlist is parsed so Source Details,
    Ngspice Model, Device Modeling and Subcircuits tabs are built
    dynamically from the schematic content.
    """

    MODEL_XML_DIR = os.path.expanduser(
        '~/Downloads/eSim-2.5/library/modelParamXML')

    def __init__(self, parent, components):
        super().__init__(
            parent,
            title="KiCad to Ngspice Converter  -  eSim Bridge v2.1",
            size=(1000, 700),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        )
        self.components = components

        # Analysis tab
        self._analysis_type   = 'tran'
        self._analysis_params = {}

        # Source Details tab
        self._source_overrides = {}
        self._source_widgets   = {}
        self._source_types     = {}

        # Ngspice Model tab
        self._ngmodel_parsed  = {}   # {ref: {model_type, params}}
        self._ngmodel_widgets = {}   # {ref: {key: wx.TextCtrl}}
        self._ngmodel_lines   = []   # filled on OK

        # Device Modeling tab
        self._device_lib_paths = {}
        self._device_entry     = {}

        # Subcircuits tab
        self._subcircuit_paths = {}
        self._subckt_entry     = {}

        self._build_ui()
        self.Centre()

    # ══════════════════════════════════════════════════════════════
    # TOP-LEVEL UI
    # ══════════════════════════════════════════════════════════════

    def _build_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(self, label="eSim One-Click Simulation Bridge")
        title.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT,
                              wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        main_sizer.Add(title, 0, wx.ALL, 10)

        ext_loader = ExternalModelLoader()
        ext_stats  = ext_loader.get_stats()
        ext_count  = ext_stats['num_models'] + ext_stats['num_subcircuits']
        ver_text   = "eSim Bridge v2.1 - 47+ built-in models"
        if ext_count > 0:
            ver_text += f" + {ext_count} external models"
        ver = wx.StaticText(self, label=ver_text)
        ver.SetForegroundColour(wx.Colour(0, 100, 0))
        main_sizer.Add(ver, 0, wx.LEFT | wx.BOTTOM, 10)

        main_sizer.Add(wx.StaticLine(self), 0,
                       wx.EXPAND | wx.LEFT | wx.RIGHT, 10)


        self.nb = wx.Notebook(self, style=wx.NB_TOP)
        main_sizer.Add(self.nb, 1, wx.EXPAND | wx.ALL, 10)

        self._build_analysis_tab()
        self._build_source_tab()
        self._build_ngmodel_tab()
        self._build_device_tab()
        self._build_subcircuit_tab()
        self._build_microcontroller_tab()

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn     = wx.Button(self, wx.ID_OK,     "Convert  ->")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Cancel")
        ok_btn.SetDefault()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        main_sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        ok_btn.Bind(wx.EVT_BUTTON, self._on_ok)
        self.SetSizer(main_sizer)
        self.Fit()



    

    # ══════════════════════════════════════════════════════════════
    # TAB 1 - ANALYSIS
    # ══════════════════════════════════════════════════════════════

    def _build_analysis_tab(self):
        panel = wx.ScrolledWindow(self.nb)
        panel.SetScrollRate(0, 10)
        sizer = wx.BoxSizer(wx.VERTICAL)

        type_box = wx.StaticBox(panel, label="Select Analysis Type")
        type_bsz = wx.StaticBoxSizer(type_box, wx.HORIZONTAL)
        self._cb_ac    = wx.CheckBox(panel, label="AC")
        self._cb_dc    = wx.CheckBox(panel, label="DC")
        self._cb_tran  = wx.CheckBox(panel, label="TRANSIENT")
        self._cb_noise = wx.CheckBox(panel, label="NOISE")
        self._cb_tf    = wx.CheckBox(panel, label="TRANSFER FUNCTION")
        self._cb_sens  = wx.CheckBox(panel, label="SENSITIVITY")
        self._cb_tran.SetValue(True)
        for cb in (self._cb_ac, self._cb_dc, self._cb_tran, self._cb_noise, self._cb_tf, self._cb_sens):
            type_bsz.Add(cb, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 8)
            cb.Bind(wx.EVT_CHECKBOX, self._on_analysis_checkbox)
        sizer.Add(type_bsz, 0, wx.EXPAND | wx.ALL, 8)

        # Wrap each group in its own panel for proper Show/Hide
        self._ac_panel = wx.Panel(panel)
        ac_sizer = wx.BoxSizer(wx.VERTICAL)
        ac_sizer.Add(self._make_ac_group(self._ac_panel), 0, wx.EXPAND)
        self._ac_panel.SetSizer(ac_sizer)
        sizer.Add(self._ac_panel, 0, wx.EXPAND | wx.ALL, 8)

        self._dc_panel = wx.Panel(panel)
        dc_sizer = wx.BoxSizer(wx.VERTICAL)
        dc_sizer.Add(self._make_dc_group(self._dc_panel), 0, wx.EXPAND)
        self._dc_panel.SetSizer(dc_sizer)
        sizer.Add(self._dc_panel, 0, wx.EXPAND | wx.ALL, 8)

        self._tran_panel = wx.Panel(panel)
        tran_sizer = wx.BoxSizer(wx.VERTICAL)
        tran_sizer.Add(self._make_tran_group(self._tran_panel), 0, wx.EXPAND)
        self._tran_panel.SetSizer(tran_sizer)
        sizer.Add(self._tran_panel, 0, wx.EXPAND | wx.ALL, 8)

        self._noise_panel = wx.Panel(panel)
        noise_sizer = wx.BoxSizer(wx.VERTICAL)
        noise_sizer.Add(self._make_noise_group(self._noise_panel), 0, wx.EXPAND)
        self._noise_panel.SetSizer(noise_sizer)
        sizer.Add(self._noise_panel, 0, wx.EXPAND | wx.ALL, 8)

        self._tf_panel = wx.Panel(panel)
        tf_sizer = wx.BoxSizer(wx.VERTICAL)
        tf_sizer.Add(self._make_tf_group(self._tf_panel), 0, wx.EXPAND)
        self._tf_panel.SetSizer(tf_sizer)
        sizer.Add(self._tf_panel, 0, wx.EXPAND | wx.ALL, 8)

        self._sens_panel = wx.Panel(panel)
        sens_sizer = wx.BoxSizer(wx.VERTICAL)
        sens_sizer.Add(self._make_sens_group(self._sens_panel), 0, wx.EXPAND)
        self._sens_panel.SetSizer(sens_sizer)
        sizer.Add(self._sens_panel, 0, wx.EXPAND | wx.ALL, 8)

        # Show only TRANSIENT by default
        self._ac_panel.Show(False)
        self._dc_panel.Show(False)
        self._tran_panel.Show(True)
        self._noise_panel.Show(False)
        self._tf_panel.Show(False)
        self._sens_panel.Show(False)

        panel.SetSizer(sizer)
        self.nb.AddPage(panel, "Analysis")
        self._analysis_panel = panel

    def _make_ac_group(self, parent):
        box  = wx.StaticBox(parent, label="AC Analysis")
        bsz  = wx.StaticBoxSizer(box, wx.VERTICAL)
        grid = wx.FlexGridSizer(rows=0, cols=3, vgap=6, hgap=10)
        grid.AddGrowableCol(1)

        grid.Add(wx.StaticText(parent, label="Scale"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        sp = wx.Panel(parent)
        ss = wx.BoxSizer(wx.HORIZONTAL)
        self._ac_lin = wx.RadioButton(sp, label="Lin", style=wx.RB_GROUP)
        self._ac_dec = wx.RadioButton(sp, label="Dec")
        self._ac_oct = wx.RadioButton(sp, label="Oct")
        self._ac_dec.SetValue(True)
        for rb in (self._ac_lin, self._ac_dec, self._ac_oct):
            ss.Add(rb, 0, wx.RIGHT, 8)
        sp.SetSizer(ss)
        grid.Add(sp, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(wx.StaticText(parent, label=""), 0)

        grid.Add(wx.StaticText(parent, label="Start Frequency"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._ac_fstart = wx.TextCtrl(parent, value="1")
        grid.Add(self._ac_fstart, 1, wx.EXPAND)
        self._ac_fstart_unit = wx.Choice(
            parent, choices=["Hz", "KHz", "Meg", "GHz", "THz"])
        self._ac_fstart_unit.SetSelection(0)
        grid.Add(self._ac_fstart_unit, 0)

        grid.Add(wx.StaticText(parent, label="Stop Frequency"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._ac_fstop = wx.TextCtrl(parent, value="1")
        grid.Add(self._ac_fstop, 1, wx.EXPAND)
        self._ac_fstop_unit = wx.Choice(
            parent, choices=["Hz", "KHz", "Meg", "GHz", "THz"])
        self._ac_fstop_unit.SetSelection(2)
        grid.Add(self._ac_fstop_unit, 0)

        grid.Add(wx.StaticText(parent, label="No. of Points"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._ac_points = wx.TextCtrl(parent, value="100")
        grid.Add(self._ac_points, 1, wx.EXPAND)
        grid.Add(wx.StaticText(parent, label=""), 0)

        bsz.Add(grid, 0, wx.EXPAND | wx.ALL, 6)
        return bsz
    


    def _build_microcontroller_tab(self):
        panel = wx.ScrolledWindow(self.nb)
        panel.SetScrollRate(0, 10)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Check NGHDL installation
        nghdl_config = os.path.expanduser('~/.nghdl/config.ini')
        nghdl_installed = os.path.exists(nghdl_config)

        # Status box
        status_box = wx.StaticBox(panel, label="NGHDL Status")
        status_bsz = wx.StaticBoxSizer(status_box, wx.VERTICAL)

        if nghdl_installed:
            status_text = wx.StaticText(panel,
                label="NGHDL is installed and available.")
            status_text.SetForegroundColour(wx.Colour(0, 128, 0))
        else:
            status_text = wx.StaticText(panel,
                label="NGHDL is NOT installed on this system.\n"
                    "Microcontroller simulation requires NGHDL.\n\n"
                    "Install NGHDL from:\n"
                    "https://github.com/FOSSEE/NGHDL")
            status_text.SetForegroundColour(wx.Colour(200, 0, 0))



        nghdl_home = "Not configured"
        if nghdl_installed:
            from configparser import ConfigParser
            parser = ConfigParser()
            parser.read(nghdl_config)
            try:
                nghdl_home = parser.get('NGHDL', 'NGHDL_HOME')
            except:
                nghdl_home = "Could not read NGHDL_HOME from config"

        # Then add this to the status_bsz display:
        if nghdl_installed:
            home_text = wx.StaticText(panel, label=f"NGHDL Home: {nghdl_home}")
            home_text.SetForegroundColour(wx.Colour(0, 80, 0))
            status_bsz.Add(home_text, 0, wx.LEFT | wx.BOTTOM, 10)

        status_bsz.Add(status_text, 0, wx.ALL, 10)
        sizer.Add(status_bsz, 0, wx.EXPAND | wx.ALL, 8)

        # MCU components detected
        mcu_keywords = ['attiny', 'arduino', 'atmega', 'pic', 'stm32',
                        'esp', 'avr', 'microcontroller', 'mcu']
        mcu_comps = {}
        for ref, cd in self.components.items():
            value = cd.get('value', '').lower()
            if any(kw in value for kw in mcu_keywords):
                mcu_comps[ref] = cd

        mcu_box = wx.StaticBox(panel, label="Microcontroller Components")
        mcu_bsz = wx.StaticBoxSizer(mcu_box, wx.VERTICAL)



        # Load previous hex file paths
        prev_hex = {}
        prev_xml = os.path.expanduser('~/.esim-bridge/mcu_previous_values.xml')
        if os.path.exists(prev_xml):
            try:
                tree = _ET.parse(prev_xml)
                root_elem = tree.getroot()
                for child in root_elem:
                    if child.tag == 'mcu':
                        ref = child.get('ref', '')
                        hexpath = child.get('hexpath', '')
                        if ref and hexpath:
                            prev_hex[ref] = hexpath
            except:
                pass

        if not mcu_comps:
            no_mcu = wx.StaticText(panel,
                label="No microcontroller components detected in schematic.\n"
                    "MCU components should have values like: ATtiny85,\n"
                    "Arduino, ATmega328, PIC16F877, STM32F103 etc.")
            no_mcu.SetForegroundColour(wx.Colour(100, 100, 100))
            mcu_bsz.Add(no_mcu, 0, wx.ALL, 10)
        else:
            self._mcu_hex_paths = {}
            grid = wx.FlexGridSizer(rows=0, cols=4, vgap=6, hgap=10)
            grid.AddGrowableCol(2)

            for ref, cd in sorted(mcu_comps.items()):
                value = cd.get('value', '')
                instance_id = str(random.randint(0, 99))

                grid.Add(wx.StaticText(panel, label=ref),
                        0, wx.ALIGN_CENTER_VERTICAL)
                grid.Add(wx.StaticText(panel, label=value),
                        0, wx.ALIGN_CENTER_VERTICAL)


                prev_path = prev_hex.get(ref, "")
                hex_tc = wx.TextCtrl(panel, value=prev_path,
                                    style=wx.TE_READONLY, size=(200, -1))
                self._mcu_hex_paths[ref] = {
                    'tc': hex_tc,
                    'instance_id': instance_id,
                    'value': value
                }
                grid.Add(hex_tc, 1, wx.EXPAND)

                add_btn = wx.Button(panel, label="Add Hex File")
                add_btn.Bind(wx.EVT_BUTTON,
                    lambda evt, r=ref: self._pick_hex_file(r))
                grid.Add(add_btn, 0)

            mcu_bsz.Add(grid, 0, wx.EXPAND | wx.ALL, 8)

            if not nghdl_installed:
                warn = wx.StaticText(panel,
                    label="Note: NGHDL is required to simulate these components.")
                warn.SetForegroundColour(wx.Colour(200, 100, 0))
                mcu_bsz.Add(warn, 0, wx.ALL, 8)

        sizer.Add(mcu_bsz, 0, wx.EXPAND | wx.ALL, 8)

        # Info box
        info_box = wx.StaticBox(panel, label="About Microcontroller Simulation")
        info_bsz = wx.StaticBoxSizer(info_box, wx.VERTICAL)
        info_text = wx.StaticText(panel,
            label="eSim uses NGHDL to simulate microcontrollers alongside\n"
                "analog circuits. NGHDL converts compiled .hex firmware\n"
                "into a behavioral SPICE model that ngspice can simulate.\n\n"
                "Workflow:\n"
                "1. Write MCU firmware in C/Arduino\n"
                "2. Compile to .hex using avr-gcc or Arduino IDE\n"
                "3. Install NGHDL from github.com/FOSSEE/NGHDL\n"
                "4. Add .hex file here\n"
                "5. Run simulation in eSim")
        info_text.SetForegroundColour(wx.Colour(80, 80, 80))
        info_bsz.Add(info_text, 0, wx.ALL, 10)
        sizer.Add(info_bsz, 0, wx.EXPAND | wx.ALL, 8)

        panel.SetSizer(sizer)
        self.nb.AddPage(panel, "Microcontroller")


    def _save_mcu_previous_values(self):
        """Save MCU hex file paths for next session - mirrors eSim's Previous_Values.xml"""
        if not hasattr(self, '_mcu_hex_paths') or not self._mcu_hex_paths:
            return
        try:
            save_dir = os.path.expanduser('~/.esim-bridge')
            os.makedirs(save_dir, exist_ok=True)
            root_elem = _ET.Element('microcontroller')
            for ref, data in self._mcu_hex_paths.items():
                hexpath = data['tc'].GetValue().strip()
                if hexpath:
                    child = _ET.SubElement(root_elem, 'mcu')
                    child.set('ref', ref)
                    child.set('value', data.get('value', ''))
                    child.set('instance_id', data.get('instance_id', '0'))
                    child.set('hexpath', hexpath)
            tree = _ET.ElementTree(root_elem)
            tree.write(os.path.expanduser('~/.esim-bridge/mcu_previous_values.xml'))
        except Exception as e:
            print(f"Could not save MCU previous values: {e}")


    def _make_dc_group(self, parent):
        box   = wx.StaticBox(parent, label="DC Analysis")
        bsz   = wx.StaticBoxSizer(box, wx.VERTICAL)
        UNITS = ["Volts or Amperes", "mV or mA",
                 "uV or uA", "nV or nA", "pV or pA"]

        def _row(lbl, default, units=None):
            rs = wx.BoxSizer(wx.HORIZONTAL)
            rs.Add(wx.StaticText(parent, label=lbl, size=(130, -1)),
                   0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
            tc = wx.TextCtrl(parent, value=default, size=(100, -1))
            rs.Add(tc, 0)
            ch = None
            if units:
                ch = wx.Choice(parent, choices=units)
                ch.SetSelection(0)
                rs.Add(ch, 0, wx.LEFT, 6)
            return rs, tc, ch

        bsz.Add(wx.StaticText(parent, label="Source 1"), 0, wx.ALL, 4)
        r, self._dc_src1,   _ = _row("Enter Source 1", "V1")
        bsz.Add(r, 0, wx.ALL, 3)
        r, self._dc_start1, self._dc_start1_u = _row("Start",     "0",   UNITS)
        bsz.Add(r, 0, wx.ALL, 3)
        r, self._dc_inc1,   self._dc_inc1_u   = _row("Increment", "0.1", UNITS)
        bsz.Add(r, 0, wx.ALL, 3)
        r, self._dc_stop1,  self._dc_stop1_u  = _row("Stop",      "5",   UNITS)
        bsz.Add(r, 0, wx.ALL, 3)

        bsz.Add(wx.StaticLine(parent), 0, wx.EXPAND | wx.ALL, 4)
        bsz.Add(wx.StaticText(parent, label="Source 2 (optional)"), 0, wx.ALL, 4)
        r, self._dc_src2,   _ = _row("Enter Source 2", "")
        bsz.Add(r, 0, wx.ALL, 3)
        r, self._dc_start2, self._dc_start2_u = _row("Start",     "0",   UNITS)
        bsz.Add(r, 0, wx.ALL, 3)
        r, self._dc_inc2,   self._dc_inc2_u   = _row("Increment", "0.1", UNITS)
        bsz.Add(r, 0, wx.ALL, 3)
        r, self._dc_stop2,  self._dc_stop2_u  = _row("Stop",      "5",   UNITS)
        bsz.Add(r, 0, wx.ALL, 3)

        self._dc_op_check = wx.CheckBox(
            parent, label="Operating Point Analysis")
        bsz.Add(self._dc_op_check, 0, wx.ALL, 6)
        return bsz
    
    def _pick_hex_file(self, ref):
        dlg = wx.FileDialog(
            self, f"Select .hex file for {ref}",
            wildcard="HEX files (*.hex)|*.hex|Text files (*.txt)|*.txt",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self._mcu_hex_paths[ref]['tc'].SetValue(path)
        dlg.Destroy()

    def _make_tran_group(self, parent):
        box  = wx.StaticBox(parent, label="Transient Analysis")
        bsz  = wx.StaticBoxSizer(box, wx.VERTICAL)
        grid = wx.FlexGridSizer(rows=0, cols=3, vgap=6, hgap=10)
        grid.AddGrowableCol(1)
        UNITS = ["sec", "ms", "us", "ns", "ps"]

        def _trow(lbl, val, unit_idx):
            grid.Add(wx.StaticText(parent, label=lbl),
                     0, wx.ALIGN_CENTER_VERTICAL)
            tc = wx.TextCtrl(parent, value=val)
            grid.Add(tc, 1, wx.EXPAND)
            ch = wx.Choice(parent, choices=UNITS)
            ch.SetSelection(unit_idx)
            grid.Add(ch, 0)
            return tc, ch

        self._tran_start, self._tran_start_u = _trow("Start Time", "0",   1)
        self._tran_step,  self._tran_step_u  = _trow("Step Time",  "0.1", 1)
        self._tran_stop,  self._tran_stop_u  = _trow("Stop Time",  "10",  1)
        bsz.Add(grid, 0, wx.EXPAND | wx.ALL, 6)
        return bsz
    

    def _make_noise_group(self, parent):
        box  = wx.StaticBox(parent, label="Noise Analysis")
        bsz  = wx.StaticBoxSizer(box, wx.VERTICAL)
        grid = wx.FlexGridSizer(rows=0, cols=3, vgap=6, hgap=10)
        grid.AddGrowableCol(1)
        UNITS = ["Hz", "KHz", "Meg", "GHz"]

        grid.Add(wx.StaticText(parent, label="Output Node"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._noise_output = wx.TextCtrl(parent, value="out")
        grid.Add(self._noise_output, 1, wx.EXPAND)
        grid.Add(wx.StaticText(parent, label="e.g. out, net_r1"), 0)

        grid.Add(wx.StaticText(parent, label="Input Source"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._noise_source = wx.TextCtrl(parent, value="V1")
        grid.Add(self._noise_source, 1, wx.EXPAND)
        grid.Add(wx.StaticText(parent, label="e.g. V1, V2"), 0)

        grid.Add(wx.StaticText(parent, label="Start Frequency"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._noise_fstart = wx.TextCtrl(parent, value="1")
        grid.Add(self._noise_fstart, 1, wx.EXPAND)
        self._noise_fstart_unit = wx.Choice(parent, choices=UNITS)
        self._noise_fstart_unit.SetSelection(0)
        grid.Add(self._noise_fstart_unit, 0)

        grid.Add(wx.StaticText(parent, label="Stop Frequency"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._noise_fstop = wx.TextCtrl(parent, value="1")
        grid.Add(self._noise_fstop, 1, wx.EXPAND)
        self._noise_fstop_unit = wx.Choice(parent, choices=UNITS)
        self._noise_fstop_unit.SetSelection(2)
        grid.Add(self._noise_fstop_unit, 0)

        grid.Add(wx.StaticText(parent, label="No. of Points"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._noise_points = wx.TextCtrl(parent, value="100")
        grid.Add(self._noise_points, 1, wx.EXPAND)
        grid.Add(wx.StaticText(parent, label=""), 0)

        bsz.Add(grid, 0, wx.EXPAND | wx.ALL, 6)
        return bsz
    


    def _make_tf_group(self, parent):
        box  = wx.StaticBox(parent, label="Transfer Function Analysis")
        bsz  = wx.StaticBoxSizer(box, wx.VERTICAL)
        grid = wx.FlexGridSizer(rows=0, cols=2, vgap=6, hgap=10)
        grid.AddGrowableCol(1)

        grid.Add(wx.StaticText(parent, label="Output Node (e.g. out)"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._tf_output = wx.TextCtrl(parent, value="out")
        grid.Add(self._tf_output, 1, wx.EXPAND)

        grid.Add(wx.StaticText(parent, label="Input Source (e.g. V1)"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._tf_source = wx.TextCtrl(parent, value="V1")
        grid.Add(self._tf_source, 1, wx.EXPAND)

        bsz.Add(grid, 0, wx.EXPAND | wx.ALL, 6)

        info = wx.StaticText(parent,
            label="Transfer Function gives: gain, input impedance, output impedance.\n"
                  "Example: output=out, source=V1 → tf v(out) V1")
        info.SetForegroundColour(wx.Colour(80, 80, 80))
        bsz.Add(info, 0, wx.ALL, 6)
        return bsz
    

    def _make_sens_group(self, parent):
        box  = wx.StaticBox(parent, label="Sensitivity Analysis")
        bsz  = wx.StaticBoxSizer(box, wx.VERTICAL)
        grid = wx.FlexGridSizer(rows=0, cols=2, vgap=6, hgap=10)
        grid.AddGrowableCol(1)

        grid.Add(wx.StaticText(parent, label="Output Variable (e.g. v(out))"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._sens_output = wx.TextCtrl(parent, value="v(out)")
        grid.Add(self._sens_output, 1, wx.EXPAND)

        bsz.Add(grid, 0, wx.EXPAND | wx.ALL, 6)

        info = wx.StaticText(parent,
            label="Sensitivity shows how much each component affects the output.\n"
                  "Example: output=v(net_r1_pad2) → sens v(net_r1_pad2)\n"
                  "Results show: which resistor/capacitor has the most impact.")
        info.SetForegroundColour(wx.Colour(80, 80, 80))
        bsz.Add(info, 0, wx.ALL, 6)
        return bsz

    def _on_analysis_checkbox(self, event):
        clicked = event.GetEventObject()
        for cb in (self._cb_ac, self._cb_dc, self._cb_tran, self._cb_noise, self._cb_tf, self._cb_sens):
            if cb is not clicked:
                cb.SetValue(False)
        clicked.SetValue(True)
        self._ac_panel.Show(clicked is self._cb_ac)
        self._dc_panel.Show(clicked is self._cb_dc)
        self._tran_panel.Show(clicked is self._cb_tran)
        self._noise_panel.Show(clicked is self._cb_noise)
        self._tf_panel.Show(clicked is self._cb_tf)
        self._sens_panel.Show(clicked is self._cb_sens)
        self._analysis_panel.Layout()
        self._analysis_panel.FitInside()

    # ══════════════════════════════════════════════════════════════
    # TAB 2 - SOURCE DETAILS
    # ══════════════════════════════════════════════════════════════

    def _build_source_tab(self):
        panel = wx.ScrolledWindow(self.nb)
        panel.SetScrollRate(0, 10)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sources = {ref: cd for ref, cd in self.components.items()
                   if ref[0].upper() in ('V', 'I')}

        if not sources:
            sizer.Add(wx.StaticText(panel,
                label="No voltage/current sources found in schematic."),
                0, wx.ALL, 15)
        else:
            for ref, cd in sorted(sources.items()):
                sizer.Add(self._make_source_group(panel, ref, cd),
                          0, wx.EXPAND | wx.ALL, 8)

        panel.SetSizer(sizer)
        self.nb.AddPage(panel, "Source Details")

    def _make_source_group(self, parent, ref, comp_data):
        value    = comp_data.get('value', '')
        sim_type = comp_data.get('sim_type', '').lower()
        stype    = self._detect_source_type(sim_type, value)
        self._source_types[ref] = stype

        box = wx.StaticBox(parent, label=f"{ref}  ({value})")
        bsz = wx.StaticBoxSizer(box, wx.VERTICAL)

        hdr = wx.BoxSizer(wx.HORIZONTAL)
        hdr.Add(wx.StaticText(parent, label="Source type:"),
                0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        type_choice = wx.Choice(
            parent, choices=["dc", "ac", "sine", "pulse", "pwl", "exp"])
        type_choice.SetStringSelection(stype)
        hdr.Add(type_choice, 0)
        bsz.Add(hdr, 0, wx.ALL, 6)

        param_panel = wx.Panel(parent)
        param_sizer = wx.BoxSizer(wx.VERTICAL)
        param_panel.SetSizer(param_sizer)
        bsz.Add(param_panel, 0, wx.EXPAND | wx.ALL, 4)

        self._build_source_params(param_panel, param_sizer, ref, stype, comp_data)

        def on_type_change(evt, pp=param_panel, ps=param_sizer,
                           r=ref, cd=comp_data):
            new_type = type_choice.GetStringSelection()
            self._source_types[r] = new_type
            self._build_source_params(pp, ps, r, new_type, cd)
            pp.Layout()
            parent.Layout()

        type_choice.Bind(wx.EVT_CHOICE, on_type_change)
        return bsz

    def _detect_source_type(self, sim_type, value):
        for t in ('sine', 'pulse', 'pwl', 'exp', 'ac', 'dc'):
            if t in sim_type or t in value.lower():
                return t
        return 'dc'

    def _build_source_params(self, panel, sizer, ref, stype, comp_data):
        sizer.Clear(True)
        self._source_widgets[ref] = {}
        kw = {}
        for p in comp_data.get('sim_params', '').split():
            if '=' in p:
                k, v = p.split('=', 1)
                kw[k.lower()] = v

        def _field(lbl, key, default):
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(wx.StaticText(panel, label=lbl, size=(210, -1)),
                    0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
            tc = wx.TextCtrl(panel, value=kw.get(key, default), size=(150, -1))
            row.Add(tc, 0)
            sizer.Add(row, 0, wx.ALL, 3)
            self._source_widgets[ref][key] = tc

        if stype == 'dc':
            _field("Value (Volts/Amps):",            'dc',    '0')
        elif stype == 'ac':
            _field("Amplitude (Volts/Amps):",        'ampl',  '1')
            _field("Phase Shift (degrees):",         'phase', '0')
        elif stype == 'sine':
            _field("Offset (Volts/Amps):",           'dc',    '0')
            _field("Amplitude (Volts/Amps):",        'ampl',  '1')
            _field("Frequency (Hz):",                'f',     '1k')
            _field("Delay Time (s):",                'td',    '0')
            _field("Damping Factor (1/s):",          'theta', '0')
        elif stype == 'pulse':
            _field("Initial Value (V/A):",           'v1',    '0')
            _field("Pulsed Value (V/A):",            'v2',    '5')
            _field("Delay Time (s):",                'td',    '0')
            _field("Rise Time (s):",                 'tr',    '1n')
            _field("Fall Time (s):",                 'tf',    '1n')
            _field("Pulse Width (s):",               'pw',    '5m')
            _field("Period (s):",                    'per',   '10m')
        elif stype == 'pwl':
            _field("PWL values (t1 v1 t2 v2 ...):", 'pwl',   '0 0 1m 1 2m 0')
        elif stype == 'exp':
            _field("Initial Value (V/A):",           'v1',    '0')
            _field("Pulsed Value (V/A):",            'v2',    '1')
            _field("Rise Delay Time (s):",           'td1',   '0')
            _field("Rise Time Constant (s):",        'tau1',  '1m')
            _field("Fall Delay Time (s):",           'td2',   '5m')
            _field("Fall Time Constant (s):",        'tau2',  '1m')
        panel.Layout()

    # ══════════════════════════════════════════════════════════════
    # TAB 3 - NGSPICE MODEL  (mirrors eSim's Model.py exactly)
    # ══════════════════════════════════════════════════════════════

    def _build_ngmodel_tab(self):
        panel = wx.ScrolledWindow(self.nb)
        panel.SetScrollRate(0, 10)
        sizer = wx.BoxSizer(wx.VERTICAL)

        u_comps = {ref: cd for ref, cd in self.components.items()
                   if ref[0].upper() == 'U'}

        if not u_comps:
            sizer.Add(wx.StaticText(panel,
                label="No Ngspice model components (U-prefix) found.\n"
                      "This tab is needed for analog/digital behavioral\n"
                      "models such as gain, comparator, adder, etc."),
                0, wx.ALL, 15)
        else:
            info = wx.StaticText(panel,
                label="Set parameters for each Ngspice behavioral model.\n"
                      "Values correspond to eSim's modelParamXML definitions.")
            info.SetForegroundColour(wx.Colour(80, 80, 80))
            sizer.Add(info, 0, wx.ALL, 8)

            for ref, cd in sorted(u_comps.items()):
                grp = self._make_ngmodel_group(panel, ref, cd)
                if grp:
                    sizer.Add(grp, 0, wx.EXPAND | wx.ALL, 6)

        panel.SetSizer(sizer)
        self.nb.AddPage(panel, "Ngspice Model")

    def _find_model_xml(self, model_type):
        """Search eSim modelParamXML subdirs for <model_type>.xml."""
        if not os.path.exists(self.MODEL_XML_DIR):
            return None, None
        for subdir in ('Analog', 'Digital', 'Hybrid', 'Nghdl', 'Ngveri'):
            xml_path = os.path.join(
                self.MODEL_XML_DIR, subdir, model_type + '.xml')
            if os.path.exists(xml_path):
                try:
                    return xml_path, _ET.parse(xml_path)
                except Exception:
                    return None, None
        return None, None

    def _parse_model_xml(self, tree):
        """
        Parse modelParamXML tree into list of param dicts.
        Each dict: {tag, label, default, vector}
        vector=0 means scalar; vector=N means N text fields.
        """
        params = []
        for param_node in tree.findall('param'):
            for item in param_node:
                params.append({
                    'tag':     item.tag,
                    'label':   item.text.strip() if item.text else item.tag,
                    'default': item.attrib.get('default', ''),
                    'vector':  int(item.attrib['vector'])
                               if 'vector' in item.attrib else 0,
                })
        return params

    def _make_ngmodel_group(self, parent, ref, comp_data):
        """Build one group-box per U-prefix component."""
        value = comp_data.get('value', '').lower()
        xml_path, tree = self._find_model_xml(value)

        if tree is None:
            box  = wx.StaticBox(parent,
                label=f"{ref}  ({value})  - model XML not found in eSim library")
            bsz  = wx.StaticBoxSizer(box, wx.VERTICAL)
            note = wx.StaticText(parent,
                label=f"No XML for '{value}' found in modelParamXML.\n"
                      "Component will use built-in/external model lookup.")
            note.SetForegroundColour(wx.Colour(150, 80, 0))
            bsz.Add(note, 0, wx.ALL, 6)
            return bsz

        title_node = tree.find('title')
        title_text = (title_node.text.strip()
                      if title_node is not None
                      else f"Add Parameters for {value} {ref}")

        params = self._parse_model_xml(tree)
        self._ngmodel_parsed[ref]  = {'model_type': value, 'params': params}
        self._ngmodel_widgets[ref] = {}

        box  = wx.StaticBox(parent, label=f"{title_text}  -  {ref}")
        bsz  = wx.StaticBoxSizer(box, wx.VERTICAL)
        grid = wx.FlexGridSizer(rows=0, cols=2, vgap=5, hgap=10)
        grid.AddGrowableCol(1)

        for p in params:
            tag, label, default, vector = (
                p['tag'], p['label'], p['default'], p['vector'])

            if vector > 0:
                # Vector param: create `vector` separate text controls
                # labelled "label 1", "label 2", ...
                for vi in range(1, vector + 1):
                    grid.Add(wx.StaticText(parent, label=f"{label} {vi}"),
                             0, wx.ALIGN_CENTER_VERTICAL)
                    tc = wx.TextCtrl(parent, value=default, size=(150, -1))
                    grid.Add(tc, 1, wx.EXPAND)
                    self._ngmodel_widgets[ref][f"{tag}_{vi}"] = tc
            else:
                grid.Add(wx.StaticText(parent, label=label),
                         0, wx.ALIGN_CENTER_VERTICAL)
                tc = wx.TextCtrl(parent, value=default, size=(150, -1))
                grid.Add(tc, 1, wx.EXPAND)
                self._ngmodel_widgets[ref][tag] = tc

        bsz.Add(grid, 0, wx.EXPAND | wx.ALL, 6)
        return bsz

    # ══════════════════════════════════════════════════════════════
    # TAB 4 - DEVICE MODELING
    # ══════════════════════════════════════════════════════════════

    def _build_device_tab(self):
        panel = wx.ScrolledWindow(self.nb)
        panel.SetScrollRate(0, 10)
        sizer = wx.BoxSizer(wx.VERTICAL)

        devices = {ref: cd for ref, cd in self.components.items()
                   if ref[0].upper() in ('Q', 'D', 'J', 'M', 'S')}

        if not devices:
            sizer.Add(wx.StaticText(panel,
                label="No active devices (Q/D/J/M/S) found in schematic.\n"
                      "Device Modeling tab is not needed."),
                0, wx.ALL, 15)
        else:
            info = wx.StaticText(panel,
                label="Select a .lib file for each active device.\n"
                      "Leave blank to use the built-in model library.")
            info.SetForegroundColour(wx.Colour(80, 80, 80))
            sizer.Add(info, 0, wx.ALL, 8)
            for ref, cd in sorted(devices.items()):
                sizer.Add(self._make_device_group(panel, ref, cd),
                          0, wx.EXPAND | wx.ALL, 6)

        panel.SetSizer(sizer)
        self.nb.AddPage(panel, "Device Modeling")

    def _make_device_group(self, parent, ref, comp_data):
        prefix = ref[0].upper()
        value  = comp_data.get('value', '')
        labels = {'Q': 'Transistor', 'D': 'Diode',
                  'J': 'JFET', 'M': 'MOSFET', 'S': 'Switch'}

        box = wx.StaticBox(
            parent,
            label=f"Add library for {labels.get(prefix,'Device')}  {ref} : {value}")
        bsz = wx.StaticBoxSizer(box, wx.VERTICAL)
        row = wx.BoxSizer(wx.HORIZONTAL)

        tc = wx.TextCtrl(parent, value="", style=wx.TE_READONLY, size=(360, -1))
        self._device_entry[ref] = tc
        row.Add(tc, 1, wx.EXPAND | wx.RIGHT, 6)
        add_btn = wx.Button(parent, label="Add")
        add_btn.Bind(wx.EVT_BUTTON, lambda evt, r=ref: self._pick_device_lib(r))
        row.Add(add_btn, 0)
        bsz.Add(row, 0, wx.EXPAND | wx.ALL, 6)

        # MOSFET dimension fields (mirrors eSim DeviceModel.py)
        if prefix == 'M':
            grid = wx.FlexGridSizer(rows=0, cols=2, vgap=4, hgap=8)
            grid.AddGrowableCol(1)
            for suffix, lbl, default in [
                ('_W', f"Width of MOSFET {ref} (default=100u):",     "100u"),
                ('_L', f"Length of MOSFET {ref} (default=100u):",    "100u"),
                ('_M', f"Mult. factor of MOSFET {ref} (default=1):", "1"),
            ]:
                grid.Add(wx.StaticText(parent, label=lbl),
                         0, wx.ALIGN_CENTER_VERTICAL)
                dim_tc = wx.TextCtrl(parent, value=default, size=(100, -1))
                self._device_entry[ref + suffix] = dim_tc
                grid.Add(dim_tc, 0)
            bsz.Add(grid, 0, wx.EXPAND | wx.ALL, 6)

        return bsz

    def _pick_device_lib(self, ref):
        dlg = wx.FileDialog(
            self, f"Select .lib file for {ref}",
            wildcard="SPICE Library (*.lib)|*.lib|All files|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self._device_entry[ref].SetValue(path)
            self._device_lib_paths[ref] = path
        dlg.Destroy()

    # ══════════════════════════════════════════════════════════════
    # TAB 5 - SUBCIRCUITS
    # ══════════════════════════════════════════════════════════════

    def _build_subcircuit_tab(self):
        panel = wx.ScrolledWindow(self.nb)
        panel.SetScrollRate(0, 10)
        sizer = wx.BoxSizer(wx.VERTICAL)

        subcircuits = {ref: cd for ref, cd in self.components.items()
                       if ref[0].upper() == 'X'}

        if not subcircuits:
            sizer.Add(wx.StaticText(panel,
                label="No subcircuit components (X-prefix) found.\n"
                      "Subcircuits tab is not needed."),
                0, wx.ALL, 15)
        else:
            info = wx.StaticText(panel,
                label="Select the subcircuit directory for each X-prefix "
                      "component.\nThe directory must contain a .sub file.")
            info.SetForegroundColour(wx.Colour(80, 80, 80))
            sizer.Add(info, 0, wx.ALL, 8)
            for ref, cd in sorted(subcircuits.items()):
                sizer.Add(self._make_subcircuit_group(panel, ref, cd),
                          0, wx.EXPAND | wx.ALL, 6)

        panel.SetSizer(sizer)
        self.nb.AddPage(panel, "Subcircuits")

    def _make_subcircuit_group(self, parent, ref, comp_data):
        value = comp_data.get('value', '')
        box   = wx.StaticBox(parent, label=f"Add subcircuit for  {ref} : {value}")
        bsz   = wx.StaticBoxSizer(box, wx.VERTICAL)
        row   = wx.BoxSizer(wx.HORIZONTAL)

        tc = wx.TextCtrl(parent, value="", style=wx.TE_READONLY, size=(360, -1))
        self._subckt_entry[ref] = tc
        row.Add(tc, 1, wx.EXPAND | wx.RIGHT, 6)
        add_btn = wx.Button(parent, label="Add")
        add_btn.Bind(wx.EVT_BUTTON,
                     lambda evt, r=ref: self._pick_subcircuit_dir(r))
        row.Add(add_btn, 0)
        bsz.Add(row, 0, wx.EXPAND | wx.ALL, 6)
        return bsz

    def _pick_subcircuit_dir(self, ref):
        dlg = wx.DirDialog(self, f"Select subcircuit directory for {ref}",
                           style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            sub_files = [f for f in os.listdir(path) if f.endswith('.sub')]
            if not sub_files:
                wx.MessageBox(
                    f"No .sub file found in:\n{path}\n\n"
                    "Please select a directory containing a .sub file.",
                    "Invalid Subcircuit Directory", wx.OK | wx.ICON_ERROR)
            else:
                self._subckt_entry[ref].SetValue(path)
                self._subcircuit_paths[ref] = path
        dlg.Destroy()

    # ══════════════════════════════════════════════════════════════
    # OK HANDLER
    # ══════════════════════════════════════════════════════════════

    def _on_ok(self, event):
        self._collect_analysis()
        self._collect_source_overrides()
        self._collect_ngmodel_lines()
        self._collect_device_libs()
        self._save_mcu_previous_values()   # ← ADD THIS LINE
        event.Skip()

    def _collect_analysis(self):
        if self._cb_ac.GetValue():
            self._analysis_type = 'ac'
            scale = ('dec' if self._ac_dec.GetValue() else
                     'lin' if self._ac_lin.GetValue() else 'oct')
            um = {'Hz': '', 'KHz': 'k', 'Meg': 'Meg', 'GHz': 'G', 'THz': 'T'}
            self._analysis_params = {
                'scale':  scale,
                'fstart': self._ac_fstart.GetValue() +
                          um.get(self._ac_fstart_unit.GetStringSelection(), ''),
                'fstop':  self._ac_fstop.GetValue() +
                          um.get(self._ac_fstop_unit.GetStringSelection(), ''),
                'points': self._ac_points.GetValue(),
            }
        elif self._cb_dc.GetValue():
            if self._dc_op_check.GetValue():
                self._analysis_type   = 'op'
                self._analysis_params = {}
            else:
                self._analysis_type = 'dc'
                um2 = {'Volts or Amperes': '', 'mV or mA': 'm',
                       'uV or uA': 'u',        'nV or nA': 'n',
                       'pV or pA': 'p'}
                def _u(ch): return um2.get(ch.GetStringSelection(), '')
                self._analysis_params = {
                    'source': self._dc_src1.GetValue() or 'V1',
                    'start':  self._dc_start1.GetValue() + _u(self._dc_start1_u),
                    'stop':   self._dc_stop1.GetValue()  + _u(self._dc_stop1_u),
                    'step':   self._dc_inc1.GetValue()   + _u(self._dc_inc1_u),
                }
                if self._dc_src2.GetValue().strip():
                    self._analysis_params.update({
                        'source2': self._dc_src2.GetValue(),
                        'start2':  self._dc_start2.GetValue() + _u(self._dc_start2_u),
                        'stop2':   self._dc_stop2.GetValue()  + _u(self._dc_stop2_u),
                        'step2':   self._dc_inc2.GetValue()   + _u(self._dc_inc2_u),
                    })



        elif self._cb_tf.GetValue():
            self._analysis_type = 'tf'
            self._analysis_params = {
                'output': self._tf_output.GetValue().strip() or 'out',
                'source': self._tf_source.GetValue().strip() or 'V1',
            }

        elif self._cb_sens.GetValue():
            self._analysis_type = 'sens'
            self._analysis_params = {
                'output': self._sens_output.GetValue().strip() or 'v(out)',
            }

        elif self._cb_noise.GetValue():
            self._analysis_type = 'noise'
            um = {'Hz': '', 'KHz': 'k', 'Meg': 'Meg', 'GHz': 'G'}
            self._analysis_params = {
                'output':  self._noise_output.GetValue().strip() or 'out',
                'source':  self._noise_source.GetValue().strip() or 'V1',
                'fstart':  self._noise_fstart.GetValue() +
                           um.get(self._noise_fstart_unit.GetStringSelection(), ''),
                'fstop':   self._noise_fstop.GetValue() +
                           um.get(self._noise_fstop_unit.GetStringSelection(), ''),
                'points':  self._noise_points.GetValue(),
            }

        else:  # TRAN default
            self._analysis_type = 'tran'
            um3 = {'sec': '', 'ms': 'm', 'us': 'u', 'ns': 'n', 'ps': 'p'}
            def _tu(ch): return um3.get(ch.GetStringSelection(), '')
            self._analysis_params = {
                'start': self._tran_start.GetValue() + _tu(self._tran_start_u),
                'step':  self._tran_step.GetValue()  + _tu(self._tran_step_u),
                'stop':  self._tran_stop.GetValue()  + _tu(self._tran_stop_u),
            }

    def _collect_source_overrides(self):
        for ref, widgets in self._source_widgets.items():
            stype = self._source_types.get(ref, 'dc')
            pins  = self.components[ref].get('pins', {})
            sp    = sorted(pins.keys(),
                           key=lambda x: int(x) if x.isdigit() else 0)
            nodes = [pins[p] for p in sp]
            while len(nodes) < 2:
                nodes.append('0')
            n0, n1 = nodes[0], nodes[1]

            def g(key, default='0'):
                tc = widgets.get(key)
                v  = tc.GetValue().strip() if tc else ''
                return v if v else default

            if stype == 'dc':
                line = f"{ref} {n0} {n1} DC {g('dc','0')}"
            elif stype == 'ac':
                line = f"{ref} {n0} {n1} AC {g('ampl','1')} {g('phase','0')}"
            elif stype == 'sine':
                line = (f"{ref} {n0} {n1} AC {g('ampl','1')} "
                        f"SIN({g('dc','0')} {g('ampl','1')} {g('f','1k')} "
                        f"{g('td','0')} {g('theta','0')})")
            elif stype == 'pulse':
                line = (f"{ref} {n0} {n1} "
                        f"PULSE({g('v1','0')} {g('v2','5')} {g('td','0')} "
                        f"{g('tr','1n')} {g('tf','1n')} "
                        f"{g('pw','5m')} {g('per','10m')})")
            elif stype == 'pwl':
                line = f"{ref} {n0} {n1} PWL({g('pwl','0 0')})"
            elif stype == 'exp':
                line = (f"{ref} {n0} {n1} "
                        f"EXP({g('v1','0')} {g('v2','1')} {g('td1','0')} "
                        f"{g('tau1','1m')} {g('td2','5m')} {g('tau2','1m')})")
            else:
                line = f"{ref} {n0} {n1} DC 0"
            self._source_overrides[ref] = line

    def _collect_ngmodel_lines(self):
        """
        Build .model lines from Ngspice Model tab widgets.
        Mirrors eSim's Convert.addModelParameter() logic exactly.
        """
        self._ngmodel_lines = []
        for ref, info in self._ngmodel_parsed.items():
            model_type = info['model_type']
            params     = info['params']
            widgets    = self._ngmodel_widgets.get(ref, {})

            model_line = f".model {ref} {model_type}("

            for p in params:
                tag, default, vector = p['tag'], p['default'], p['vector']
                if vector > 0:
                    model_line += f"{tag}=["
                    for vi in range(1, vector + 1):
                        tc  = widgets.get(f"{tag}_{vi}")
                        val = tc.GetValue().strip() if tc else ''
                        model_line += (val if val else default) + " "
                    model_line += "] "
                else:
                    tc  = widgets.get(tag)
                    val = tc.GetValue().strip() if tc else ''
                    model_line += f"{tag}={(val if val else default)} "

            model_line += ")"
            self._ngmodel_lines.append(
                f"* Schematic Name: {model_type}, Ngspice Name: {ref}")
            self._ngmodel_lines.append(model_line)

    def _collect_device_libs(self):
        for ref, tc in self._device_entry.items():
            if any(ref.endswith(s) for s in ('_W', '_L', '_M')):
                continue
            path = tc.GetValue().strip()
            if path:
                self._device_lib_paths[ref] = path

    # ══════════════════════════════════════════════════════════════
    # PUBLIC GETTERS
    # ══════════════════════════════════════════════════════════════

    def get_analysis_type(self):    return self._analysis_type
    def get_analysis_params(self):  return self._analysis_params
    def get_source_overrides(self): return self._source_overrides
    def get_ngmodel_lines(self):    return self._ngmodel_lines
    def get_device_lib_paths(self): return self._device_lib_paths
    def get_subcircuit_paths(self): return self._subcircuit_paths

    def get_mosfet_dimensions(self, ref):
        """Returns (width, length, multifactor) strings for a MOSFET ref."""
        w = self._device_entry.get(ref + '_W')
        l = self._device_entry.get(ref + '_L')
        m = self._device_entry.get(ref + '_M')
        return (
            w.GetValue() if w else '100u',
            l.GetValue() if l else '100u',
            m.GetValue() if m else '1',
        )


# ══════════════════════════════════════════════════════════════════════
# NEW RUN FLOW  -  paste into Run() replacing old Steps 1 & 2
# ══════════════════════════════════════════════════════════════════════
#
# DELETE this old block from Run():
#   dialog = AnalysisConfigDialog(None)
#   if dialog.ShowModal() != wx.ID_OK: ...
#   analysis_type   = dialog.get_analysis_type()
#   analysis_params = dialog.get_analysis_params()
#   dialog.Destroy()
#   schematic_path = self.get_schematic_path()   <- also delete this
#
# REPLACE WITH:
#
#   # Step 1: Get schematic path
#   schematic_path = self.get_schematic_path()
#   if not schematic_path:
#       wx.MessageBox("No schematic found.\nPlease open a schematic first.",
#                     "eSim Bridge", wx.OK | wx.ICON_ERROR)
#       return
#
#   # Step 2: Export netlist silently
#   netlist_xml_path = "/tmp/esim_bridge_netlist.net"
#   if not self.export_netlist(schematic_path, netlist_xml_path):
#       wx.MessageBox("Failed to export netlist.\n"
#                     "Make sure kicad-cli is available.",
#                     "eSim Bridge Error", wx.OK | wx.ICON_ERROR)
#       return
#
#   # Step 3: Parse netlist to populate dialog tabs
#   converter = SPICEConverter()
#   components_pre, _ = converter.parse_full_netlist(netlist_xml_path)
#
#   # Step 4: Show the tabbed KicadToNgspice dialog
#   ktn_dlg = KicadToNgspiceDialog(None, components_pre)
#   if ktn_dlg.ShowModal() != wx.ID_OK:
#       ktn_dlg.Destroy()
#       return
#
#   analysis_type    = ktn_dlg.get_analysis_type()
#   analysis_params  = ktn_dlg.get_analysis_params()
#   source_overrides = ktn_dlg.get_source_overrides()
#   ngmodel_lines    = ktn_dlg.get_ngmodel_lines()
#   device_lib_paths = ktn_dlg.get_device_lib_paths()
#   subcircuit_paths = ktn_dlg.get_subcircuit_paths()
#   ktn_dlg.Destroy()
#
#   # Step 5: Run preflight checks (keep existing code from here)
#   # Also inject ngmodel_lines into SPICE file after conversion:
#   #   if ngmodel_lines:
#   #       with open(spice_output_path, 'r') as f: content = f.read()
#   #       inject = '\n* -- Ngspice Model Tab --\n' + '\n'.join(ngmodel_lines)
#   #       content = content.replace('\n.end', inject + '\n.end')
#   #       with open(spice_output_path, 'w') as f: f.write(content)


# ══════════════════════════════════════════════════════════════════════
# ESIM LAUNCHER
# ══════════════════════════════════════════════════════════════════════

class ESimLauncher:
    """Finds and launches eSim with a pre-loaded netlist."""
    
    ESIM_SCRIPT = os.path.expanduser(
        '~/Downloads/eSim-2.5/src/frontEnd/Application.py')
    ESIM_PYTHON = os.path.expanduser('~/.esim/env/bin/python3')
    ESIM_SRC    = os.path.expanduser('~/Downloads/eSim-2.5/src')
    ESIM_DIR    = os.path.expanduser('~/Downloads/eSim-2.5/src/frontEnd')

    def find_esim(self):
        return (
            os.path.exists(self.ESIM_SCRIPT) and
            os.path.exists(self.ESIM_PYTHON)
        )

    def launch(self, netlist_path):
        import time

        if not self.find_esim():
            return False, (
                "eSim not found.\n\n"
                "Expected at:\n"
                f"{self.ESIM_SCRIPT}\n\n"
                "Please install eSim 2.5 from:\n"
                "https://static.fossee.in/esim/installation-files/eSim-2.5.zip\n\n"
                f"Your SPICE file has been saved to:\n{netlist_path}\n"
                "You can open it manually once eSim is installed."
            )

        home_netlist = os.path.expanduser('~/esim_bridge_simulation.cir')
        try:
            shutil.copy2(netlist_path, home_netlist)
        except Exception:
            home_netlist = netlist_path

        try:
            env = os.environ.copy()
            env['PYTHONPATH'] = self.ESIM_SRC

            cmd = [self.ESIM_PYTHON, 'Application.py']
            process = subprocess.Popen(
                cmd, cwd=self.ESIM_DIR, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )

            time.sleep(3)

            if process.poll() is None:
                return True, (
                    f"eSim launched successfully!\n"
                    f"PID: {process.pid}\n\n"
                    f"Your SPICE file is at:\n{home_netlist}"
                )
            else:
                stdout, stderr = process.communicate()
                return False, f"eSim failed to start.\n\nError:\n{stderr.decode()[:500]}"

        except FileNotFoundError:
            return False, f"Could not find Python:\n{self.ESIM_PYTHON}"
        except Exception as e:
            return False, f"Unexpected error:\n{str(e)}"


# ══════════════════════════════════════════════════════════════════════
# PREFLIGHT CHECKER
# ══════════════════════════════════════════════════════════════════════

class PreflightChecker:
    """Checks everything is ready before attempting simulation."""
    
    def run_all_checks(self, schematic_path):
        results = []
        
        if not os.path.exists(schematic_path):
            results.append(('error', 
                f"Schematic file not found:\n{schematic_path}"))
            return results
        
        results.append(('ok', f"Schematic found: {schematic_path}"))
        
        try:
            result = subprocess.run(
                ['kicad-cli', '--version'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                results.append(('ok', 
                    f"kicad-cli available: {result.stdout.strip()}"))
            else:
                results.append(('error', "kicad-cli not working correctly"))
        except FileNotFoundError:
            results.append(('error', 
                "kicad-cli not found. Is KiCad installed correctly?"))
        
        launcher = ESimLauncher()
        esim_path = launcher.find_esim()
        if esim_path:
            results.append(('ok', f"eSim found: {esim_path}"))
        else:
            results.append(('warning', 
                "eSim not found. SPICE file will be saved but eSim "
                "won't auto-launch."))
        
        try:
            test_file = '/tmp/esim_bridge_test.tmp'
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            results.append(('ok', "Write access to /tmp confirmed"))
        except:
            results.append(('error', "Cannot write to /tmp directory."))
        

        # ── .spiceinit auto-writer ──
        spiceinit_path = os.path.expanduser('~/.spiceinit')
        spiceinit_needed_line = 'set ngbehavior=ps'
        
        try:
            if os.path.exists(spiceinit_path):
                with open(spiceinit_path, 'r') as f:
                    content = f.read()
                if spiceinit_needed_line in content:
                    results.append(('ok', ".spiceinit already configured for PSPICE compatibility"))
                else:
                    with open(spiceinit_path, 'a') as f:
                        f.write(f'\n* Added by eSim-BRIDGE\n{spiceinit_needed_line}\n')
                    results.append(('ok', ".spiceinit updated: added ngbehavior=ps for PSPICE model compatibility"))
            else:
                with open(spiceinit_path, 'w') as f:
                    f.write(f'* eSim-BRIDGE auto-generated spiceinit\n{spiceinit_needed_line}\n')
                results.append(('ok', ".spiceinit created with ngbehavior=ps for PSPICE model compatibility"))
        except Exception as e:
            results.append(('warning', f"Could not write .spiceinit: {e}"))
        
        return results

    def run_netlist_checks(self, components, nets):
        """Wrapper that formats netlist check results same as run_all_checks."""
        return self.check_netlist(components, nets)
    




    def check_netlist(self, components, nets):
        """
        Check parsed netlist for common simulation-killing problems.
        Returns list of (severity, message) tuples.
        """
        issues = []

        # ── Check 1: Ground node exists ──
        has_ground = any(
            data['spice_name'] == '0'
            for data in nets.values()
        )
        if not has_ground:
            issues.append(('error',
                "No GND node found. Every circuit needs a ground reference (GND/0). "
                "Add a PWR_FLAG or GND symbol connected to your ground net."))
        else:
            issues.append(('ok', "Ground node (GND/0) present"))

        # ── Check 2: Build connection count per SPICE net ──
        # Count how many component pins connect to each net
        net_pin_count = {}   # {spice_net_name: count}
        net_pin_refs  = {}   # {spice_net_name: [ref, ...]} for error messages

        for net_name, net_data in nets.items():
            spice_name = net_data['spice_name']
            nodes      = net_data.get('nodes', [])
            net_pin_count[spice_name] = net_pin_count.get(spice_name, 0) + len(nodes)
            if spice_name not in net_pin_refs:
                net_pin_refs[spice_name] = []
            for ref, pin in nodes:
                net_pin_refs[spice_name].append(f"{ref}.{pin}")

        # ── Check 3: Floating nodes (connected to only 1 pin) ──
        floating = []
        for spice_net, count in net_pin_count.items():
            if spice_net == '0':
                continue   # GND is always fine
            if count == 1:
                refs = ', '.join(net_pin_refs[spice_net][:3])
                floating.append(f"  Net '{spice_net}' → only pin: {refs}")

        if floating:
            issues.append(('error',
                "Floating node(s) detected — ngspice will fail with 'singular matrix':\n"
                + '\n'.join(floating)
                + "\n  Fix: connect these pins to another component or add a large pull-down resistor."))
        else:
            issues.append(('ok', "No floating nodes detected"))

        # ── Check 4: Voltage source short circuit ──
        # Two voltage sources sharing both nodes = dead short
        vsource_nodes = {}  # {frozenset(node_a, node_b): ref}
        for ref, comp_data in components.items():
            if ref[0].upper() != 'V' and not ref.upper().startswith('BT'):
                continue
            pins = comp_data.get('pins', {})
            sorted_pins = sorted(pins.keys(),
                                key=lambda x: int(x) if x.isdigit() else 0)
            node_list = [pins[p] for p in sorted_pins]
            if len(node_list) >= 2:
                pair = frozenset([node_list[0], node_list[1]])
                if pair in vsource_nodes:
                    other_ref = vsource_nodes[pair]
                    issues.append(('error',
                        f"Voltage source short: {ref} and {other_ref} share "
                        f"both terminals ({node_list[0]}, {node_list[1]}). "
                        "ngspice cannot solve this — remove one or add a series resistor."))
                else:
                    vsource_nodes[pair] = ref

        if not any(s == 'error' and 'Voltage source short' in m
                for s, m in issues):
            issues.append(('ok', "No voltage source conflicts detected"))

        # ── Check 5: Components with no connections at all ──
        orphans = []
        for ref, comp_data in components.items():
            prefix = ref[0].upper()
            if prefix in ('R', 'C', 'L', 'V', 'I', 'D', 'Q', 'M', 'J', 'U', 'X'):
                pins = comp_data.get('pins', {})
                if not pins:
                    orphans.append(ref)

    
        if orphans:
            issues.append(('warning',
                f"Components with no net connections: {', '.join(orphans)}. "
                "These will be ignored by ngspice but may indicate a wiring error."))
        else:
            issues.append(('ok', "All components have at least one connection"))

        # ── Check 6: DC path violations (capacitor-only paths) ──
        cap_only_nets = []
        for net_name, net_data in nets.items():
            spice_name = net_data['spice_name']
            if spice_name == '0':
                continue
            nodes = net_data.get('nodes', [])
            refs_on_net = [ref for ref, pin in nodes]
            if len(refs_on_net) < 2:
                continue
            all_caps = all(
                ref[0].upper() == 'C'
                for ref in refs_on_net
            )
            if all_caps:
                cap_only_nets.append(spice_name)

        if cap_only_nets:
            issues.append(('warning',
                f"DC path violation — net(s) connected only through capacitors: "
                f"{', '.join(cap_only_nets)}. "
                "Add a resistor to ground or ngspice may fail with singular matrix."))
        else:
            issues.append(('ok', "No DC path violations detected"))

        return issues
    
    def show_results_dialog(self, results):
        errors = [r for r in results if r[0] == 'error']
        warnings = [r for r in results if r[0] == 'warning']
        oks = [r for r in results if r[0] == 'ok']
        
        if not errors and not warnings:
            return True
        
        message = ""
        
        if errors:
            message += "ERRORS (must fix before simulating):\n"
            for _, msg in errors:
                message += f"  ✗ {msg}\n"
            message += "\n"
        
        if warnings:
            message += "WARNINGS (simulation may still work):\n"
            for _, msg in warnings:
                message += f"  ⚠ {msg}\n"
            message += "\n"
        
        if oks:
            message += "OK:\n"
            for _, msg in oks:
                message += f"  ✓ {msg}\n"
        
        if errors:
            wx.MessageBox(message, "eSim Bridge - Preflight Check Failed",
                wx.OK | wx.ICON_ERROR)
            return False
        else:
            result = wx.MessageBox(
                message + "\nContinue anyway?",
                "eSim Bridge - Preflight Warnings",
                wx.YES_NO | wx.ICON_WARNING)
            return result == wx.YES








# ══════════════════════════════════════════════════════════════════════
# NGSPICE WAVEFORM VIEWER
# Drop-in replacement for the text-only ngspice output dialog.
#
# HOW TO INTEGRATE INTO esim_bridge.py:
#   1. Paste this entire block ABOVE the SimulationReadyDialog class
#   2. Replace the _on_run_ngspice method inside SimulationReadyDialog
#      with the NEW version at the bottom of this file
#   3. Add   import struct   near the top imports of esim_bridge.py
# ══════════════════════════════════════════════════════════════════════


# ── Raw file parser ────────────────────────────────────────────────────

class NgspiceRawParser:
    """
    Parses ngspice .raw files (both ASCII and binary real/complex).
    Returns a dict:
      {
        'title':    str,
        'type':     str,   # 'transient', 'ac', etc.
        'vars':     [{'name': str, 'unit': str}],
        'data':     {var_name: [float, ...]},   # real part only for AC
      }
    """

    def parse(self, raw_path):
        with open(raw_path, 'rb') as f:
            raw_bytes = f.read()

        # Try to detect ASCII vs binary
        # ngspice binary files have 'Binary:' header
        try:
            header_text = raw_bytes[:4096].decode('utf-8', errors='replace')
        except Exception:
            header_text = ''

        if 'Binary:' in header_text:
            return self._parse_binary(raw_bytes, header_text)
        else:
            return self._parse_ascii(raw_bytes.decode('utf-8', errors='replace'))

    # ── ASCII parser ───────────────────────────────────────────────

    def _parse_ascii(self, text):
        result = {'title': '', 'type': '', 'vars': [], 'data': {}}
        lines = text.splitlines()
        i = 0
        num_vars = 0
        num_points = 0

        while i < len(lines):
            line = lines[i]

            if line.startswith('Title:'):
                result['title'] = line[6:].strip()
            elif line.startswith('Plotname:'):
                result['type'] = line[9:].strip().lower()
            elif line.startswith('No. Variables:'):
                num_vars = int(line.split(':')[1].strip())
            elif line.startswith('No. Points:'):
                num_points = int(line.split(':')[1].strip())
            elif line.startswith('Variables:'):
                i += 1
                for _ in range(num_vars):
                    if i < len(lines):
                        parts = lines[i].split()
                        if len(parts) >= 3:
                            result['vars'].append({
                                'name': parts[1],
                                'unit': parts[2]
                            })
                            result['data'][parts[1]] = []
                        i += 1
                continue
            elif line.startswith('Values:'):
                i += 1
                # Each data point block: index\tval0\n\t\tval1\n ...
                var_idx = 0
                point_idx = 0
                while i < len(lines) and point_idx < num_points:
                    line = lines[i]
                    stripped = line.strip()
                    if not stripped:
                        i += 1
                        continue
                    parts = stripped.split()
                    # First line of a point has the index prepended
                    if len(parts) == 2 and var_idx == 0:
                        val_str = parts[1]
                    elif len(parts) == 1:
                        val_str = parts[0]
                    else:
                        val_str = parts[-1]
                    try:
                        val = float(val_str.replace(',', '.'))
                        var_name = result['vars'][var_idx]['name']
                        result['data'][var_name].append(val)
                    except (ValueError, IndexError):
                        pass
                    var_idx += 1
                    if var_idx >= num_vars:
                        var_idx = 0
                        point_idx += 1
                    i += 1
                continue
            i += 1

        return result

    # ── Binary parser ──────────────────────────────────────────────

    def _parse_binary(self, raw_bytes, header_text):
        result = {'title': '', 'type': '', 'vars': [], 'data': {}}

        # Parse text header
        lines = header_text.splitlines()
        num_vars = 0
        num_points = 0
        binary_start = 0

        for idx, line in enumerate(lines):
            if line.startswith('Title:'):
                result['title'] = line[6:].strip()
            elif line.startswith('Plotname:'):
                result['type'] = line[9:].strip().lower()
            elif line.startswith('No. Variables:'):
                num_vars = int(line.split(':')[1].strip())
            elif line.startswith('No. Points:'):
                num_points = int(line.split(':')[1].strip())
            elif line.startswith('Variables:'):
                for j in range(1, num_vars + 1):
                    if idx + j < len(lines):
                        parts = lines[idx + j].split()
                        if len(parts) >= 3:
                            result['vars'].append({
                                'name': parts[1],
                                'unit': parts[2]
                            })
                            result['data'][parts[1]] = []
            elif line.startswith('Binary:'):
                # Find byte offset of 'Binary:\n' in raw_bytes
                binary_tag = b'Binary:\n'
                offset = raw_bytes.find(binary_tag)
                if offset != -1:
                    binary_start = offset + len(binary_tag)
                break

        if not result['vars'] or binary_start == 0:
            return result

        data_bytes = raw_bytes[binary_start:]

        # ngspice stores doubles (8 bytes each), row-major:
        # for each point: var0_val, var1_val, ..., varN-1_val
        bytes_per_point = num_vars * 8
        is_complex = 'ac' in result['type']

        for pt in range(num_points):
            offset = pt * bytes_per_point * (2 if is_complex else 1)
            for vi, var in enumerate(result['vars']):
                byte_off = offset + vi * 8 * (2 if is_complex else 1)
                chunk = data_bytes[byte_off: byte_off + 8]
                if len(chunk) < 8:
                    break
                val = struct.unpack('d', chunk)[0]
                result['data'][var['name']].append(val)

        return result


# ── Waveform viewer dialog ──────────────────────────────────────────────

class NgspiceWaveformViewer(wx.Dialog):
    """
    Embeds a matplotlib figure inside a wx.Dialog.
    Displays all voltage/current waveforms from an ngspice .raw file.
    Matches the oscilloscope-style look: dark background, coloured traces,
    grid, legend — just like the ngspice standalone plotter.
    """

    # Dark oscilloscope colour palette (cycles through traces)
    TRACE_COLOURS = [
        '#FF4444',  # red
        '#4488FF',  # blue
        '#44FF88',  # green
        '#FFD700',  # gold
        '#FF88FF',  # magenta
        '#44FFFF',  # cyan
        '#FF8844',  # orange
        '#AAAAFF',  # lavender
    ]

    def __init__(self, parent, raw_path, analysis_type='tran', cir_path='', ngspice_output=''):
        self._ngspice_output = ngspice_output
        super().__init__(
            parent,
            title="ngspice Waveform Viewer  –  eSim Bridge",
            size=(900, 600),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX
        )
        self._raw_path     = raw_path
        self._analysis_type = analysis_type
        self._cir_path     = cir_path
        self._parsed       = None
        self._hidden_vars  = set()   # names toggled off

        self._build_ui()
        self._load_and_plot()
        if ngspice_output:
            self.set_stats_text(self._build_stats_text(ngspice_output))
        self.Centre()

    # ── UI skeleton ────────────────────────────────────────────────

    def _build_ui(self):
        from matplotlib.figure import Figure
        try:
            from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas
            from matplotlib.backends.backend_wxagg import NavigationToolbar2WxAgg as NavToolbar
        except ImportError:
            from matplotlib.backends.backend_wx import FigureCanvasWx as FigureCanvas
            from matplotlib.backends.backend_wx import NavigationToolbar2Wx as NavToolbar

        main = wx.BoxSizer(wx.VERTICAL)

        # ── Top info bar ──
        info_row = wx.BoxSizer(wx.HORIZONTAL)
        self._lbl_info = wx.StaticText(self, label="Loading…")
        self._lbl_info.SetFont(wx.Font(9, wx.FONTFAMILY_TELETYPE,
                                       wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        info_row.Add(self._lbl_info, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)

        refresh_btn = wx.Button(self, label="⟳ Refresh", size=(80, -1))
        refresh_btn.Bind(wx.EVT_BUTTON, lambda e: self._load_and_plot())
        info_row.Add(refresh_btn, 0, wx.RIGHT | wx.TOP | wx.BOTTOM, 4)

        save_btn = wx.Button(self, label="💾 Save PNG", size=(90, -1))
        save_btn.Bind(wx.EVT_BUTTON, self._on_save_png)
        info_row.Add(save_btn, 0, wx.RIGHT | wx.TOP | wx.BOTTOM, 4)

        self._fft_btn = wx.Button(self, label="📊 Show FFT", size=(150, -1))
        self._fft_btn.Bind(wx.EVT_BUTTON, self._on_show_fft)
        # Only show FFT button for transient analysis
        self._fft_btn.Show(self._analysis_type == 'tran')
        info_row.Add(self._fft_btn, 0, wx.RIGHT | wx.TOP | wx.BOTTOM, 4)

        self._meas_btn = wx.Button(self, label="📏 Measure", size=(100, -1))
        self._meas_btn.Bind(wx.EVT_BUTTON, self._on_measure)
        self._meas_btn.Show(self._analysis_type == 'tran')
        info_row.Add(self._meas_btn, 0, wx.RIGHT | wx.TOP | wx.BOTTOM, 4)

        self._bode_btn = wx.Button(self, label="📈 Bode Plot", size=(110, -1))
        self._bode_btn.Bind(wx.EVT_BUTTON, self._on_show_bode)
        self._bode_btn.Show(self._analysis_type == 'ac')
        info_row.Add(self._bode_btn, 0, wx.RIGHT | wx.TOP | wx.BOTTOM, 4)

        self._cursor_btn = wx.Button(self, label="🖱 Cursor", size=(90, -1))
        self._cursor_btn.Bind(wx.EVT_BUTTON, self._on_toggle_cursor)
        self._cursor_active = False
        self._cursor_annotation = None
        self._cursor_cid = None
        info_row.Add(self._cursor_btn, 0, wx.RIGHT | wx.TOP | wx.BOTTOM, 4)

        self._sweep_btn = wx.Button(self, label="🔁 Sweep", size=(90, -1))
        self._sweep_btn.Bind(wx.EVT_BUTTON, self._on_param_sweep)
        self._sweep_btn.Show(self._analysis_type == 'tran')
        info_row.Add(self._sweep_btn, 0, wx.RIGHT | wx.TOP | wx.BOTTOM, 4)

        main.Add(info_row, 0, wx.EXPAND)

        # ── Splitter: canvas left, trace toggles right ──
        splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)

        # Left: matplotlib canvas
        canvas_panel = wx.Panel(splitter)
        canvas_sizer = wx.BoxSizer(wx.VERTICAL)

        self._fig = Figure(facecolor='#1a1a2e')
        self._ax  = self._fig.add_subplot(111)
        self._canvas = FigureCanvas(canvas_panel, -1, self._fig)
        self._toolbar = NavToolbar(self._canvas)
        self._toolbar.DeleteToolByPos(6)
        self._toolbar.Realize()

        canvas_sizer.Add(self._toolbar, 0, wx.EXPAND)
        canvas_sizer.Add(self._canvas, 1, wx.EXPAND)
        canvas_panel.SetSizer(canvas_sizer)

        # Right: trace checkboxes
        toggle_panel = wx.ScrolledWindow(splitter)
        toggle_panel.SetScrollRate(0, 10)
        self._toggle_sizer = wx.BoxSizer(wx.VERTICAL)
        self._toggle_sizer.Add(
            wx.StaticText(toggle_panel, label="Traces"), 0, wx.ALL, 6)
        toggle_panel.SetSizer(self._toggle_sizer)
        self._toggle_panel = toggle_panel

        splitter.SplitVertically(canvas_panel, toggle_panel, sashPosition=-160)
        splitter.SetMinimumPaneSize(100)
        main.Add(splitter, 1, wx.EXPAND | wx.ALL, 4)



        # ── Stats text panel ──
        self._stats_ctrl = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
            size=(-1, 160))
        self._stats_ctrl.SetFont(wx.Font(10, wx.FONTFAMILY_TELETYPE,
                                          wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self._stats_ctrl.SetBackgroundColour(wx.Colour(15, 15, 30))
        self._stats_ctrl.SetForegroundColour(wx.Colour(180, 220, 180))
        main.Add(self._stats_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        # ── Bottom buttons ──
        btn_row = wx.StdDialogButtonSizer()
        close_btn = wx.Button(self, wx.ID_OK, "Close")
        close_btn.SetDefault()
        btn_row.AddButton(close_btn)
        btn_row.Realize()
        main.Add(btn_row, 0, wx.ALL | wx.ALIGN_RIGHT, 6)

        self.SetSizer(main)

    # ── Data loading & plotting ────────────────────────────────────

    def _load_and_plot(self):
        if not os.path.exists(self._raw_path):
            self._lbl_info.SetLabel(f"Raw file not found: {self._raw_path}")
            return

        try:
            parser = NgspiceRawParser()
            self._parsed = parser.parse(self._raw_path)
        except Exception as e:
            self._lbl_info.SetLabel(f"Parse error: {e}")
            return

        vars_list = self._parsed.get('vars', [])
        if not vars_list:
            self._lbl_info.SetLabel("No variables found in .raw file.")
            return

        # Rebuild trace toggles
        self._rebuild_toggles(vars_list)
        self._draw_plot()

    def _rebuild_toggles(self, vars_list):
        # Clear old checkboxes
        self._toggle_sizer.Clear(True)
        self._toggle_sizer.Add(
            wx.StaticText(self._toggle_panel, label="Traces"), 0, wx.ALL, 6)

        self._trace_checks = {}
        for i, var in enumerate(vars_list):
            name = var['name']
            if name.lower() in ('time', 'frequency'):
                continue
            colour = self.TRACE_COLOURS[i % len(self.TRACE_COLOURS)]
            cb = wx.CheckBox(self._toggle_panel, label=name)
            cb.SetValue(name not in self._hidden_vars)
            cb.SetForegroundColour(wx.Colour(
                int(colour[1:3], 16),
                int(colour[3:5], 16),
                int(colour[5:7], 16)
            ))
            cb.Bind(wx.EVT_CHECKBOX,
                    lambda evt, n=name: self._on_toggle(n, evt))
            self._toggle_sizer.Add(cb, 0, wx.LEFT | wx.BOTTOM, 6)
            self._trace_checks[name] = cb

        self._toggle_panel.Layout()
        self._toggle_panel.FitInside()

    def _on_toggle(self, name, evt):
        if evt.IsChecked():
            self._hidden_vars.discard(name)
        else:
            self._hidden_vars.add(name)
        self._draw_plot()

    def _draw_plot(self):
        if not self._parsed:
            return

        ax  = self._ax
        ax.clear()

        # Dark oscilloscope style
        ax.set_facecolor('#0d0d1a')
        self._fig.patch.set_facecolor('#1a1a2e')
        ax.tick_params(colors='white', labelsize=8)
        ax.spines[:].set_color('#444466')
        ax.grid(True, color='white', linestyle='dotted', linewidth=0.6, alpha=0.4)
        ax.yaxis.label.set_color('white')
        ax.xaxis.label.set_color('white')
        ax.title.set_color('white')

        data    = self._parsed['data']
        vars_   = self._parsed['vars']
        title   = self._parsed.get('title', '')
        ptype   = self._parsed.get('type', self._analysis_type)

        # X axis variable
        x_var = None
        if 'time' in data:
            x_var = 'time'
            x_label = 'Time (s)'
        elif 'frequency' in data:
            x_var = 'frequency'
            x_label = 'Frequency (Hz)'
        else:
            x_label = 'Sample'

        x_data = data.get(x_var, []) if x_var else []

        trace_count = 0
        for i, var in enumerate(vars_):
            name = var['name']
            if name == x_var:
                continue
            if name in self._hidden_vars:
                continue

            y_data = data.get(name, [])
            if not y_data:
                continue

            colour = self.TRACE_COLOURS[i % len(self.TRACE_COLOURS)]

            if x_data and len(x_data) == len(y_data):
                ax.plot(x_data, y_data, color=colour,
                        linewidth=1.4, label=f"v({name})" if 'v' not in name.lower() else name)
            else:
                ax.plot(y_data, color=colour,
                        linewidth=1.4, label=name)
            trace_count += 1
        

        ax.set_xlabel(x_label, color='white', fontsize=9)
        ax.set_ylabel('Voltage (V) / Current (A)', color='white', fontsize=9)
        ax.set_title(
            title or f"ngspice – {ptype.upper()} Analysis",
            color='white', fontsize=10, pad=8)

        if trace_count > 0:
            legend = ax.legend(
                loc='upper right', fontsize=8,
                facecolor='#1a1a2e', edgecolor='#444466',
                labelcolor='#ccccff', framealpha=0.8)

        if trace_count == 0:
            ax.text(0.5, 0.5, 'No traces selected',
                    transform=ax.transAxes,
                    ha='center', va='center',
                    color='#888899', fontsize=12)

        self._fig.subplots_adjust(left=0.12, bottom=0.12, right=0.97, top=0.92)
        self._canvas.draw()

        # Update info label
        pts = len(list(data.values())[0]) if data else 0
        n_traces = sum(1 for v in vars_ if v['name'] not in (x_var,))
        self._lbl_info.SetLabel(
            f"Raw: {os.path.basename(self._raw_path)}   "
            f"| {n_traces} traces | {pts} points | "
            f"{ptype.upper()}"
        )

    def _on_save_png(self, event):
        dlg = wx.FileDialog(
            self, "Save waveform as PNG",
            wildcard="PNG Image (*.png)|*.png",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            defaultFile="ngspice_waveform.png"
        )
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self._fig.savefig(path, dpi=150, bbox_inches='tight',
                              facecolor=self._fig.get_facecolor())
            wx.MessageBox(f"Saved to:\n{path}", "Saved", wx.OK | wx.ICON_INFORMATION)
        dlg.Destroy()


    def _on_show_fft(self, event):
        """Compute and display FFT of visible transient traces."""
        import numpy as np

        if not self._parsed or not self._parsed.get('data'):
            wx.MessageBox("No data to compute FFT.", "FFT", wx.OK | wx.ICON_WARNING)
            return

        data  = self._parsed['data']
        vars_ = self._parsed['vars']

        time_data = data.get('time', [])
        if not time_data or len(time_data) < 4:
            wx.MessageBox("Not enough time-domain data for FFT.\nRun a transient simulation first.",
                          "FFT", wx.OK | wx.ICON_WARNING)
            return

        # Compute sample rate from time vector
        dt = (time_data[-1] - time_data[0]) / (len(time_data) - 1)
        fs = 1.0 / dt
        freqs = np.fft.rfftfreq(len(time_data), d=dt)

        # Switch axes to FFT mode
        ax = self._ax
        ax.clear()
        ax.set_facecolor('#0d0d1a')
        self._fig.patch.set_facecolor('#1a1a2e')
        ax.tick_params(colors='white', labelsize=8)
        ax.spines[:].set_color('#444466')
        ax.grid(True, color='white', linestyle='dotted', linewidth=0.6, alpha=0.4)
        ax.yaxis.label.set_color('white')
        ax.xaxis.label.set_color('white')
        ax.title.set_color('white')

        trace_count = 0
        for i, var in enumerate(vars_):
            name = var['name']
            if name == 'time':
                continue
            if name in self._hidden_vars:
                continue
            y_data = data.get(name, [])
            if not y_data or len(y_data) != len(time_data):
                continue

            y_arr = np.array(y_data)
            fft_mag = np.abs(np.fft.rfft(y_arr)) * 2 / len(y_arr)

            colour = self.TRACE_COLOURS[i % len(self.TRACE_COLOURS)]
            ax.plot(freqs, fft_mag, color=colour, linewidth=1.2, label=name)
            trace_count += 1

        ax.set_xlabel('Frequency (Hz)', color='white', fontsize=9)
        ax.set_ylabel('Magnitude (V)', color='white', fontsize=9)
        ax.set_title('FFT Spectrum  –  eSim Bridge', color='white', fontsize=10, pad=8)

        if trace_count > 0:
            ax.legend(loc='upper right', fontsize=8,
                      facecolor='#1a1a2e', edgecolor='#444466',
                      labelcolor='#ccccff', framealpha=0.8)
        else:
            ax.text(0.5, 0.5, 'No traces selected',
                    transform=ax.transAxes, ha='center', va='center',
                    color='#888899', fontsize=12)
            


        self._fig.subplots_adjust(left=0.12, bottom=0.12, right=0.97, top=0.92)
        self._canvas.draw()
        self._lbl_info.SetLabel(
            f"FFT | {trace_count} traces | {len(freqs)} freq points | "
            f"fs={fs:.0f} Hz | max={freqs[-1]:.0f} Hz"
        )

        # Change button to go back to waveform view
        self._fft_btn.SetLabel("📈 Show Waveform")
        self._fft_btn.SetSize((160, -1))
        self._fft_btn.Unbind(wx.EVT_BUTTON)
        self._fft_btn.Bind(wx.EVT_BUTTON, self._on_back_to_waveform)

    def _on_back_to_waveform(self, event):
        """Switch back from FFT to time-domain waveform view."""
        self._draw_plot()
        self._fft_btn.SetLabel("📊 Show FFT")
        self._fft_btn.Unbind(wx.EVT_BUTTON)
        self._fft_btn.Bind(wx.EVT_BUTTON, self._on_show_fft)
    

    def _on_show_bode(self, event):
        """Display dual-pane Bode plot (gain dB + phase degrees) for AC analysis."""
        import numpy as np

        if not self._parsed or not self._parsed.get('data'):
            wx.MessageBox("No data to plot. Run an AC simulation first.",
                          "Bode Plot", wx.OK | wx.ICON_WARNING)
            return

        data  = self._parsed['data']
        vars_ = self._parsed['vars']

        freq_data = data.get('frequency', [])
        if not freq_data or len(freq_data) < 2:
            wx.MessageBox("No frequency data found.\nRun an AC simulation first.",
                          "Bode Plot", wx.OK | wx.ICON_WARNING)
            return

        freq_arr = np.array(freq_data)

        # Clear single axes and replace with two subplots
        self._fig.clear()
        ax_gain  = self._fig.add_subplot(211)  # top: gain in dB
        ax_phase = self._fig.add_subplot(212)  # bottom: phase in degrees

        dark_style = dict(facecolor='#0d0d1a')
        for ax in (ax_gain, ax_phase):
            ax.set_facecolor('#0d0d1a')
            ax.tick_params(colors='white', labelsize=8)
            ax.spines[:].set_color('#444466')
            ax.grid(True, color='white', linestyle='dotted',
                    linewidth=0.6, alpha=0.4)
            ax.yaxis.label.set_color('white')
            ax.xaxis.label.set_color('white')
            ax.title.set_color('white')
        self._fig.patch.set_facecolor('#1a1a2e')

        trace_count = 0
        for i, var in enumerate(vars_):
            name = var['name']
            if name == 'frequency':
                continue
            if name in self._hidden_vars:
                continue

            y_data = data.get(name, [])
            if not y_data or len(y_data) != len(freq_arr):
                continue

            y_arr = np.array(y_data)

            # Magnitude in dB
            magnitude = np.abs(y_arr)
            # Avoid log(0)
            magnitude = np.where(magnitude == 0, 1e-12, magnitude)
            gain_db = 20 * np.log10(magnitude)

            # Phase in degrees
            phase_deg = np.angle(y_arr, deg=True) if np.iscomplexobj(y_arr) \
                        else np.zeros_like(y_arr)

            colour = self.TRACE_COLOURS[i % len(self.TRACE_COLOURS)]

            ax_gain.semilogx(freq_arr, gain_db,
                             color=colour, linewidth=1.4, label=name)
            ax_phase.semilogx(freq_arr, phase_deg,
                              color=colour, linewidth=1.4, label=name)
            trace_count += 1

        # Labels
        ax_gain.set_ylabel('Gain (dB)', color='white', fontsize=9)
        ax_gain.set_title('Bode Plot  –  eSim Bridge', color='white',
                          fontsize=10, pad=6)

        ax_phase.set_xlabel('Frequency (Hz)', color='white', fontsize=9)
        ax_phase.set_ylabel('Phase (°)', color='white', fontsize=9)

        if trace_count > 0:
            for ax in (ax_gain, ax_phase):
                ax.legend(loc='upper right', fontsize=8,
                          facecolor='#1a1a2e', edgecolor='#444466',
                          labelcolor='#ccccff', framealpha=0.8)

        self._fig.subplots_adjust(left=0.12, bottom=0.10,
                                  right=0.97, top=0.92, hspace=0.35)
        self._canvas.draw()

        self._lbl_info.SetLabel(
            f"Bode Plot | {trace_count} traces | "
            f"{len(freq_arr)} freq points | "
            f"{freq_arr[0]:.1f} Hz – {freq_arr[-1]:.1f} Hz"
        )

        # Toggle button to go back
        self._bode_btn.SetLabel("📉 Show Waveform")
        self._bode_btn.Unbind(wx.EVT_BUTTON)
        self._bode_btn.Bind(wx.EVT_BUTTON, self._on_back_from_bode)

    def _on_back_from_bode(self, event):
        """Restore single-axes waveform view from Bode plot."""
        self._fig.clear()
        self._ax = self._fig.add_subplot(111)
        self._draw_plot()
        self._bode_btn.SetLabel("📈 Bode Plot")
        self._bode_btn.Unbind(wx.EVT_BUTTON)
        self._bode_btn.Bind(wx.EVT_BUTTON, self._on_show_bode)
    

    def _on_toggle_cursor(self, event):
        """Toggle interactive cursor on/off."""
        if self._cursor_active:
            # Disable cursor
            if self._cursor_cid is not None:
                self._canvas.mpl_disconnect(self._cursor_cid)
                self._cursor_cid = None
            if self._cursor_annotation is not None:
                try:
                    self._cursor_annotation.remove()
                except Exception:
                    pass
                self._cursor_annotation = None
            self._cursor_active = False
            self._cursor_btn.SetLabel("🖱 Cursor")
            self._canvas.draw()
        else:
            # Enable cursor
            self._cursor_active = True
            self._cursor_btn.SetLabel("✖ Cursor OFF")
            self._cursor_cid = self._canvas.mpl_connect(
                'motion_notify_event', self._on_cursor_move)

    def _on_cursor_move(self, event):
        """Show crosshair annotation at mouse position."""
        if not self._cursor_active:
            return
        if event.inaxes is None:
            return

        ax = event.inaxes
        x, y = event.xdata, event.ydata
        if x is None or y is None:
            return

        # Format x label based on analysis type
        if self._analysis_type == 'tran':
            # Auto-scale time
            if abs(x) < 1e-6:
                x_str = f"{x*1e9:.3f} ns"
            elif abs(x) < 1e-3:
                x_str = f"{x*1e6:.3f} µs"
            elif abs(x) < 1:
                x_str = f"{x*1e3:.3f} ms"
            else:
                x_str = f"{x:.4f} s"
            label = f"t={x_str}\nV={y:.4f} V"
        elif self._analysis_type == 'ac':
            if x >= 1e6:
                x_str = f"{x/1e6:.3f} MHz"
            elif x >= 1e3:
                x_str = f"{x/1e3:.3f} kHz"
            else:
                x_str = f"{x:.1f} Hz"
            label = f"f={x_str}\n{y:.4f}"
        else:
            label = f"x={x:.4f}\ny={y:.4f}"

        # Remove old annotation
        if self._cursor_annotation is not None:
            try:
                self._cursor_annotation.remove()
            except Exception:
                pass

        # Draw crosshair lines
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()

        # Add annotation box
        self._cursor_annotation = ax.annotate(
            label,
            xy=(x, y),
            xytext=(15, 15),
            textcoords='offset points',
            fontsize=8,
            color='white',
            bbox=dict(
                boxstyle='round,pad=0.4',
                facecolor='#1a1a2e',
                edgecolor='#FFD700',
                alpha=0.9
            ),
            arrowprops=dict(
                arrowstyle='-',
                color='#FFD700',
                lw=1.2
            )
        )

        # Draw crosshair
        if not hasattr(self, '_cursor_hline'):
            self._cursor_hline = ax.axhline(
                y=y, color='#FFD700', linewidth=0.8,
                linestyle='--', alpha=0.7)
            self._cursor_vline = ax.axvline(
                x=x, color='#FFD700', linewidth=0.8,
                linestyle='--', alpha=0.7)
        else:
            try:
                self._cursor_hline.set_ydata([y, y])
                self._cursor_vline.set_xdata([x, x])
            except Exception:
                self._cursor_hline = ax.axhline(
                    y=y, color='#FFD700', linewidth=0.8,
                    linestyle='--', alpha=0.7)
                self._cursor_vline = ax.axvline(
                    x=x, color='#FFD700', linewidth=0.8,
                    linestyle='--', alpha=0.7)

        self._canvas.draw_idle()



    def _on_param_sweep(self, event):
        """Run parametric sweep — vary one component value, overlay results."""
        import numpy as np

        if not self._cir_path or not os.path.exists(self._cir_path):
            wx.MessageBox("No .cir file found. Run a simulation first.",
                          "Param Sweep", wx.OK | wx.ICON_WARNING)
            return

        # Read the .cir.out file to find component references
        cir_out = self._cir_path.replace('.cir', '.cir.out')
        if not os.path.exists(cir_out):
            cir_out = self._cir_path

        try:
            with open(cir_out, 'r') as f:
                cir_content = f.read()
        except Exception as e:
            wx.MessageBox(f"Could not read circuit file:\n{e}",
                          "Param Sweep", wx.OK | wx.ICON_ERROR)
            return

        # Find all resistors/capacitors/inductors in the file
        comps = re.findall(r'^([RCL]\w+)\s', cir_content, re.MULTILINE)
        if not comps:
            wx.MessageBox("No R/C/L components found in circuit file.",
                          "Param Sweep", wx.OK | wx.ICON_WARNING)
            return

        # Build sweep dialog
        dlg = wx.Dialog(self, title="🔁 Parametric Sweep", size=(420, 320))
        sizer = wx.BoxSizer(wx.VERTICAL)

        grid = wx.FlexGridSizer(rows=0, cols=2, vgap=8, hgap=10)
        grid.AddGrowableCol(1)

        grid.Add(wx.StaticText(dlg, label="Component:"), 0, wx.ALIGN_CENTER_VERTICAL)
        comp_choice = wx.Choice(dlg, choices=comps)
        comp_choice.SetSelection(0)
        grid.Add(comp_choice, 1, wx.EXPAND)

        grid.Add(wx.StaticText(dlg, label="Start value (e.g. 1k):"), 0, wx.ALIGN_CENTER_VERTICAL)
        start_tc = wx.TextCtrl(dlg, value="1k")
        grid.Add(start_tc, 1, wx.EXPAND)

        grid.Add(wx.StaticText(dlg, label="Stop value (e.g. 100k):"), 0, wx.ALIGN_CENTER_VERTICAL)
        stop_tc = wx.TextCtrl(dlg, value="100k")
        grid.Add(stop_tc, 1, wx.EXPAND)

        grid.Add(wx.StaticText(dlg, label="Steps (2–8):"), 0, wx.ALIGN_CENTER_VERTICAL)
        steps_tc = wx.TextCtrl(dlg, value="5")
        grid.Add(steps_tc, 1, wx.EXPAND)

        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 12)

        info = wx.StaticText(dlg,
            label="Each step reruns the simulation with a different\n"
                  "component value. Results are overlaid on one plot.")
        info.SetForegroundColour(wx.Colour(80, 80, 80))
        sizer.Add(info, 0, wx.LEFT | wx.BOTTOM, 12)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(dlg, wx.ID_OK, "Run Sweep")
        ok_btn.SetDefault()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(dlg, wx.ID_CANCEL, "Cancel"))
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        dlg.SetSizer(sizer)

        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return

        comp    = comp_choice.GetStringSelection()
        start_s = start_tc.GetValue().strip()
        stop_s  = stop_tc.GetValue().strip()
        try:
            n_steps = max(2, min(8, int(steps_tc.GetValue().strip())))
        except ValueError:
            n_steps = 5
        dlg.Destroy()

        def parse_val(s):
            """Convert SPICE value string to float."""
            s = s.strip().lower()
            mul = {'k': 1e3, 'm': 1e-3, 'u': 1e-6, 'n': 1e-9,
                   'p': 1e-12, 'meg': 1e6, 'g': 1e9}
            for suffix, factor in sorted(mul.items(), key=lambda x: -len(x[0])):
                if s.endswith(suffix):
                    return float(s[:-len(suffix)]) * factor
            return float(s)

        def fmt_val(v):
            """Format float back to readable SPICE string."""
            if v >= 1e6:   return f"{v/1e6:.3g}Meg"
            if v >= 1e3:   return f"{v/1e3:.3g}k"
            if v >= 1:     return f"{v:.3g}"
            if v >= 1e-3:  return f"{v*1e3:.3g}m"
            if v >= 1e-6:  return f"{v*1e6:.3g}u"
            if v >= 1e-9:  return f"{v*1e9:.3g}n"
            return f"{v:.3g}p"

        try:
            start_v = parse_val(start_s)
            stop_v  = parse_val(stop_s)
        except Exception:
            wx.MessageBox("Invalid start or stop value.\nUse SPICE notation: 1k, 100k, 10u",
                          "Param Sweep", wx.OK | wx.ICON_ERROR)
            return

        # Generate sweep values (log scale if ratio > 10, else linear)
        ratio = stop_v / start_v if start_v > 0 else 1
        if ratio > 10:
            values = np.logspace(np.log10(start_v), np.log10(stop_v), n_steps)
        else:
            values = np.linspace(start_v, stop_v, n_steps)

        # Progress dialog
        progress = wx.ProgressDialog(
            "Parametric Sweep",
            f"Running {n_steps} simulations…",
            maximum=n_steps,
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE | wx.PD_ELAPSED_TIME
        )

        # Run sweep
        sweep_results = []   # [(label, parsed_data)]
        SWEEP_COLOURS = [
            '#FF4444', '#4488FF', '#44FF88', '#FFD700',
            '#FF88FF', '#44FFFF', '#FF8844', '#AAAAFF'
        ]

        for step_i, val in enumerate(values):
            val_str = fmt_val(val)
            progress.Update(step_i, f"Step {step_i+1}/{n_steps}: {comp}={val_str}")

            # Modify circuit: replace component line value
            modified = re.sub(
                rf'^({re.escape(comp)}\s+\S+\s+\S+\s+)\S+',
                rf'\g<1>{val_str}',
                cir_content, count=1, flags=re.MULTILINE
            )

            # Write temp file
            tmp_cir = f'/tmp/esim_sweep_{step_i}.cir.out'
            raw_out = f'/tmp/esim_sweep_{step_i}.raw'

            # Inject binary write
            if '.control' in modified:
                modified = modified.replace(
                    '.control\n', f'.control\nset filetype=binary\n')
                modified = modified.replace(
                    '.endc\n', f'write {raw_out}\n.endc\n')

            with open(tmp_cir, 'w') as f:
                f.write(modified)

            try:
                env = os.environ.copy()
                env['PYTHONPATH'] = os.path.expanduser('~/Downloads/eSim-2.5/src')
                subprocess.run(
                    ['ngspice', '-b', tmp_cir],
                    capture_output=True, text=True, timeout=30,
                    env=env
                )
            except Exception:
                continue

            if os.path.exists(raw_out):
                try:
                    parser = NgspiceRawParser()
                    parsed = parser.parse(raw_out)
                    sweep_results.append((f"{comp}={val_str}", parsed))
                except Exception:
                    pass

        progress.Destroy()

        if not sweep_results:
            wx.MessageBox("Sweep produced no results. Check component name and values.",
                          "Param Sweep", wx.OK | wx.ICON_WARNING)
            return

        # Plot all sweep results overlaid
        ax = self._ax
        ax.clear()
        ax.set_facecolor('#0d0d1a')
        self._fig.patch.set_facecolor('#1a1a2e')
        ax.tick_params(colors='white', labelsize=8)
        ax.spines[:].set_color('#444466')
        ax.grid(True, color='white', linestyle='dotted', linewidth=0.6, alpha=0.4)
        ax.yaxis.label.set_color('white')
        ax.xaxis.label.set_color('white')
        ax.title.set_color('white')

        for idx, (label, parsed) in enumerate(sweep_results):
            data  = parsed.get('data', {})
            vars_ = parsed.get('vars', [])
            x_var = 'time' if 'time' in data else None
            if not x_var:
                continue
            x_data = data[x_var]
            colour = SWEEP_COLOURS[idx % len(SWEEP_COLOURS)]

            plotted = 0
            for var in vars_:
                name = var['name']
                if name == x_var:
                    continue
                if name in self._hidden_vars:
                    continue
                y_data = data.get(name, [])
                if y_data and len(y_data) == len(x_data):
                    plotted += 1
                    if plotted == 1:
                        continue  # skip first node (input/source)
                    ax.plot(x_data, y_data, color=colour,
                            linewidth=1.3, label=label, alpha=0.85)
                    break

        ax.set_xlabel('Time (s)', color='white', fontsize=9)
        ax.set_ylabel('Voltage (V)', color='white', fontsize=9)
        ax.set_title(f'Parametric Sweep  –  {comp}  ({start_s} → {stop_s})',
                     color='white', fontsize=10, pad=8)
        ax.legend(loc='upper right', fontsize=8,
                  facecolor='#1a1a2e', edgecolor='#444466',
                  labelcolor='#ccccff', framealpha=0.8)

        self._fig.subplots_adjust(left=0.12, bottom=0.12, right=0.97, top=0.92)
        self._canvas.draw()
        self._lbl_info.SetLabel(
            f"Param Sweep | {comp} | {len(sweep_results)} steps | "
            f"{start_s} → {stop_s}"
        )


    def _on_measure(self, event):
        """Run .meas analysis on transient data and show results."""
        if not self._parsed or not self._parsed.get('data'):
            wx.MessageBox("No data available. Run a transient simulation first.",
                          "Measure", wx.OK | wx.ICON_WARNING)
            return

        # Get available node names
        data = self._parsed['data']
        nodes = [v['name'] for v in self._parsed.get('vars', [])
                 if v['name'] != 'time']
        if not nodes:
            wx.MessageBox("No nodes found in simulation data.",
                          "Measure", wx.OK | wx.ICON_WARNING)
            return

        # Build dialog
        dlg = wx.Dialog(self, title="📏 Measurements", size=(420, 280))
        sizer = wx.BoxSizer(wx.VERTICAL)

        grid = wx.FlexGridSizer(rows=0, cols=2, vgap=8, hgap=10)
        grid.AddGrowableCol(1)

        grid.Add(wx.StaticText(dlg, label="Node:"), 0, wx.ALIGN_CENTER_VERTICAL)
        node_choice = wx.Choice(dlg, choices=nodes)
        node_choice.SetSelection(0)
        grid.Add(node_choice, 1, wx.EXPAND)

        grid.Add(wx.StaticText(dlg, label="Measurement:"), 0, wx.ALIGN_CENTER_VERTICAL)
        meas_choice = wx.Choice(dlg, choices=[
            "RMS Voltage", "Average Voltage", "Peak Voltage",
            "Min Voltage", "Max Voltage", "Frequency (zero-cross)"
        ])
        meas_choice.SetSelection(0)
        grid.Add(meas_choice, 1, wx.EXPAND)

        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 12)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(dlg, wx.ID_OK, "Measure")
        ok_btn.SetDefault()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(dlg, wx.ID_CANCEL, "Cancel"))
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        dlg.SetSizer(sizer)

        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return

        node = node_choice.GetStringSelection()
        meas = meas_choice.GetStringSelection()
        dlg.Destroy()

        # Compute from parsed data
        import math
        vals = data.get(node, [])
        time_vals = data.get('time', [])
        if not vals:
            wx.MessageBox(f"No data for node {node}.", "Measure", wx.OK | wx.ICON_WARNING)
            return

        if meas == "RMS Voltage":
            result = math.sqrt(sum(v**2 for v in vals) / len(vals))
            label = "RMS Voltage"
            unit = "V (rms)"
        elif meas == "Average Voltage":
            result = sum(vals) / len(vals)
            label = "Average Voltage"
            unit = "V"
        elif meas == "Peak Voltage":
            result = max(abs(v) for v in vals)
            label = "Peak Voltage"
            unit = "V"
        elif meas == "Min Voltage":
            result = min(vals)
            label = "Min Voltage"
            unit = "V"
        elif meas == "Max Voltage":
            result = max(vals)
            label = "Max Voltage"
            unit = "V"
        elif meas == "Frequency (zero-cross)":
            # Count zero crossings (rising)
            crossings = []
            for i in range(1, len(vals)):
                if vals[i-1] <= 0 < vals[i] and time_vals:
                    crossings.append(time_vals[i])
            if len(crossings) >= 2:
                period = (crossings[-1] - crossings[0]) / (len(crossings) - 1)
                result = 1.0 / period if period > 0 else 0
            else:
                result = 0
            label = "Frequency"
            unit = "Hz"
        else:
            result = 0
            label = meas
            unit = ""

        wx.MessageBox(
            f"Measurement Results\n"
            f"{'─'*35}\n"
            f"  Node      : {node}\n"
            f"  Measure   : {label}\n"
            f"  Result    : {result:.6g} {unit}\n",
            "eSim Bridge – Measurements",
            wx.OK | wx.ICON_INFORMATION
        )



    def set_stats_text(self, text):
        """Populate the bottom stats panel."""
        self._stats_ctrl.SetValue(text)


    def _build_stats_text(self, combined):
        """Build numerical summary from ngspice text output."""
        lines_out = []
        analysis = self._analysis_type.upper()
        lines_out.append(f"{'═'*60}")
        lines_out.append(f"  ngspice Simulation Summary  |  Analysis: {analysis}")
        lines_out.append(f"{'═'*60}")

        # ── Node voltage stats from .raw data ──
        if self._parsed and self._parsed.get('data'):
            data = self._parsed['data']
            x_var = 'time' if 'time' in data else ('frequency' if 'frequency' in data else None)
            node_lines = []
            for var in self._parsed.get('vars', []):
                name = var['name']
                if name == x_var:
                    continue
                vals = data.get(name, [])
                if not vals:
                    continue
                vmax  = max(vals)
                vmin  = min(vals)
                vavg  = sum(vals) / len(vals)
                vpeak = max(abs(vmax), abs(vmin))
                node_lines.append(
                    f"  {name:<22}  peak={vpeak:+.4f}V  "
                    f"max={vmax:+.4f}V  min={vmin:+.4f}V  avg={vavg:+.4f}V  "
                    f"pts={len(vals)}"
                )
            if node_lines:
                lines_out.append("")
                lines_out.append("  Node Voltages:")
                lines_out.extend(node_lines)

        # ── Noise analysis results ──
        noise_hits = [l.strip() for l in combined.splitlines()
                      if any(kw in l.lower() for kw in
                             ('inoise', 'onoise', 'noise', 'spectral'))]
        if noise_hits:
            lines_out.append("")
            lines_out.append("  Noise Analysis Results:")
            for nl in noise_hits[:20]:
                lines_out.append(f"    {nl}")
            lines_out.append("  (inoise = input-referred noise, onoise = output noise)")

        # ── Timing / rusage ──
        timing = [l.strip() for l in combined.splitlines()
                  if any(kw in l.lower() for kw in
                         ('total analysis time', 'total elapsed', 'cpu time',
                          'accepted', 'rejected', 'time step'))]
        if timing:
            lines_out.append("")
            lines_out.append("  Simulation Timing / Solver Stats:")
            for tl in timing[:10]:
                lines_out.append(f"    {tl}")

        # ── Warnings / errors ──
        warns = [l.strip() for l in combined.splitlines()
                 if any(kw in l.lower() for kw in ('warning', 'error', 'fatal'))
                 and l.strip()]
        if warns:
            lines_out.append("")
            lines_out.append("  ⚠ Warnings/Errors:")
            for wl in warns[:8]:
                lines_out.append(f"    {wl}")

        lines_out.append(f"{'─'*60}")
        return '\n'.join(lines_out)

# ══════════════════════════════════════════════════════════════════════
# REPLACEMENT _on_run_ngspice METHOD
# Cut out the old _on_run_ngspice from SimulationReadyDialog and
# paste this one in its place (inside the SimulationReadyDialog class).
# ══════════════════════════════════════════════════════════════════════

    def _on_run_ngspice(self, event):
        """Run ngspice directly and show interactive waveform viewer."""
        if not self.cir_out_path or not os.path.exists(self.cir_out_path):
            wx.MessageBox(
                "ngspice input file not found.\nPlease try again.",
                "ngspice Error", wx.OK | wx.ICON_ERROR)
            return

        # Output .raw file alongside the .cir.out
        raw_path = self.cir_out_path.replace('.cir.out', '.raw')
        if not raw_path.endswith('.raw'):
            raw_path = self.cir_out_path + '.raw'

        # Delete stale raw file
        try:
            if os.path.exists(raw_path):
                os.remove(raw_path)
        except Exception:
            pass

        # Inject  -r <raw_path>  into a temporary copy of the .cir.out
        # so ngspice writes binary data we can parse
        import tempfile, shutil
        tmp_cir = raw_path.replace('.raw', '_viewer.cir.out')
        try:
            with open(self.cir_out_path, 'r') as f:
                cir_content = f.read()

            # Insert  set filetype=binary  and  write  inside .control block
            # (ngspice dumps .raw only when told to write)
            if '.control' in cir_content:
                cir_content = cir_content.replace(
                    '.control\n',
                    f'.control\nset filetype=binary\n'
                )
                # Add write command before .endc
                cir_content = cir_content.replace(
                    '.endc\n',
                    f'write {raw_path}\n.endc\n'
                )
            with open(tmp_cir, 'w') as f:
                f.write(cir_content)
        except Exception as e:
            wx.MessageBox(f"Could not prepare ngspice input:\n{e}",
                          "Error", wx.OK | wx.ICON_ERROR)
            return

        # Progress dialog
        progress = wx.ProgressDialog(
            "ngspice Runner",
            "Running simulation…",
            maximum=100,
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
        )
        progress.Pulse()

        try:
            env = os.environ.copy()
            env['PYTHONPATH'] = os.path.expanduser('~/Downloads/eSim-2.5/src')

            result = subprocess.run(
                ['ngspice', '-b', tmp_cir],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=os.path.dirname(self.cir_out_path),
                env=env
            )
            progress.Destroy()

        except subprocess.TimeoutExpired:
            progress.Destroy()
            wx.MessageBox(
                "ngspice timed out after 60 seconds.\n"
                "Circuit may be too complex or have a convergence issue.",
                "ngspice Timeout", wx.OK | wx.ICON_ERROR)
            return
        except FileNotFoundError:
            progress.Destroy()
            wx.MessageBox(
                "ngspice not found.\n"
                "Install it with:  sudo apt install ngspice",
                "ngspice Not Found", wx.OK | wx.ICON_ERROR)
            return
        except Exception as e:
            progress.Destroy()
            wx.MessageBox(f"Unexpected error:\n{e}",
                          "ngspice Error", wx.OK | wx.ICON_ERROR)
            return

        # Check for errors
        combined = (result.stdout or '') + '\n' + (result.stderr or '')
        if result.returncode != 0 and not os.path.exists(raw_path):
            err_lines = [l for l in combined.splitlines()
                         if 'error' in l.lower() or 'fatal' in l.lower()]
            err_text = '\n'.join(err_lines[:15]) or combined[:800]
            wx.MessageBox(
                f"ngspice returned error code {result.returncode}.\n\n"
                f"{err_text}",
                "ngspice Error", wx.OK | wx.ICON_ERROR)
            return


        # Show waveform viewer
        if os.path.exists(raw_path):
            viewer = NgspiceWaveformViewer(
                self,
                raw_path=raw_path,
                analysis_type=self.analysis_type,
                cir_path=self.cir_out_path,
                ngspice_output=combined
            )
            viewer.ShowModal()
            viewer.Destroy()
        else:
            # Fallback: show text summary if no raw file produced
            wx.MessageBox(
                f"Simulation finished but no .raw file was produced.\n\n"
                f"ngspice output (last 20 lines):\n"
                + '\n'.join(combined.splitlines()[-20:]),
                "ngspice – No Waveform Data",
                wx.OK | wx.ICON_WARNING)







# ══════════════════════════════════════════════════════════════════════
# SIMULATION READY DIALOG
# ══════════════════════════════════════════════════════════════════════

class SimulationReadyDialog(wx.Dialog):
    """Shows after successful conversion, before launching eSim."""

    def __init__(self, parent, spice_path, components, analysis_type, params,
                 unsupported_summary=None, cir_out_path=None):
        super().__init__(parent, title="Ready to Simulate", size=(600, 750))
        self.cir_out_path = cir_out_path
        self.analysis_type = analysis_type
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        header = wx.StaticText(self, 
            label="✓ Schematic converted successfully!")
        header.SetForegroundColour(wx.Colour(0, 128, 0))
        font = wx.Font(11, wx.FONTFAMILY_DEFAULT, 
                      wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        header.SetFont(font)
        sizer.Add(header, 0, wx.ALL, 10)
        
        summary = (
            f"Components converted: {len(components)}\n"
            f"Analysis type: {analysis_type.upper()}\n"
            f"SPICE file: {spice_path}\n"
        )
        if params:
            summary += f"Parameters: {params}"
        
        summary_text = wx.StaticText(self, label=summary)
        sizer.Add(summary_text, 0, wx.ALL, 10)
        
        # Show warnings about unsupported components
        if unsupported_summary:
            warn_label = wx.StaticText(self, label="⚠ Conversion Notes:")
            warn_label.SetForegroundColour(wx.Colour(200, 100, 0))
            sizer.Add(warn_label, 0, wx.LEFT | wx.TOP, 10)
            
            warn_text = wx.TextCtrl(
                self, value=unsupported_summary,
                style=wx.TE_MULTILINE | wx.TE_READONLY,
                size=(-1, 120))
            warn_text.SetForegroundColour(wx.Colour(200, 100, 0))
            sizer.Add(warn_text, 0, wx.ALL | wx.EXPAND, 10)
        
        preview_label = wx.StaticText(self, label="Generated SPICE file:")
        sizer.Add(preview_label, 0, wx.LEFT | wx.TOP, 10)
        
        try:
            with open(spice_path, 'r') as f:
                spice_content = f.read()
        except:
            spice_content = "Could not read file"
        
        preview = wx.TextCtrl(
            self, value=spice_content,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
            size=(-1, 300))
        preview.SetFont(wx.Font(9, wx.FONTFAMILY_TELETYPE,
                               wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        sizer.Add(preview, 1, wx.ALL | wx.EXPAND, 10)
        
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        launch_btn = wx.Button(self, wx.ID_OK, "Launch eSim →")
        launch_btn.SetDefault()
        
        open_file_btn = wx.Button(self, wx.ID_ANY, "Open .cir File")
        open_file_btn.Bind(wx.EVT_BUTTON, 
            lambda e: os.system(f'xdg-open {spice_path}'))
        
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Close")
        


        ngspice_btn = wx.Button(self, wx.ID_ANY, "Run with ngspice →")
        ngspice_btn.SetBackgroundColour(wx.Colour(0, 80, 160))
        ngspice_btn.SetForegroundColour(wx.Colour(255, 255, 255))
        ngspice_btn.Bind(wx.EVT_BUTTON, self._on_run_ngspice)
        
        btn_sizer.Add(launch_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(ngspice_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(open_file_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(cancel_btn, 0)
        
        sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        self.SetSizer(sizer)

    






    def _on_run_ngspice(self, event):
        """Run ngspice directly and show interactive waveform viewer."""
        if not self.cir_out_path or not os.path.exists(self.cir_out_path):
            wx.MessageBox(
                "ngspice input file not found.\nPlease try again.",
                "ngspice Error", wx.OK | wx.ICON_ERROR)
            return

        # Output .raw file alongside the .cir.out
        raw_path = self.cir_out_path.replace('.cir.out', '.raw')
        if not raw_path.endswith('.raw'):
            raw_path = self.cir_out_path + '.raw'

        # Delete stale raw file
        try:
            if os.path.exists(raw_path):
                os.remove(raw_path)
        except Exception:
            pass

        # Inject  -r <raw_path>  into a temporary copy of the .cir.out
        # so ngspice writes binary data we can parse
        import tempfile, shutil
        tmp_cir = raw_path.replace('.raw', '_viewer.cir.out')
        try:
            with open(self.cir_out_path, 'r') as f:
                cir_content = f.read()

            # Insert  set filetype=binary  and  write  inside .control block
            # (ngspice dumps .raw only when told to write)
            if '.control' in cir_content:
                cir_content = cir_content.replace(
                    '.control\n',
                    f'.control\nset filetype=binary\n'
                )
                # Add write command before .endc
                cir_content = cir_content.replace(
                    '.endc\n',
                    f'write {raw_path}\n.endc\n'
                )
            with open(tmp_cir, 'w') as f:
                f.write(cir_content)
        except Exception as e:
            wx.MessageBox(f"Could not prepare ngspice input:\n{e}",
                        "Error", wx.OK | wx.ICON_ERROR)
            return

        # Progress dialog
        progress = wx.ProgressDialog(
            "ngspice Runner",
            "Running simulation…",
            maximum=100,
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
        )
        progress.Pulse()

        try:
            env = os.environ.copy()
            env['PYTHONPATH'] = os.path.expanduser('~/Downloads/eSim-2.5/src')

            result = subprocess.run(
                ['ngspice', '-b', tmp_cir],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=os.path.dirname(self.cir_out_path),
                env=env
            )
            progress.Destroy()

        except subprocess.TimeoutExpired:
            progress.Destroy()
            wx.MessageBox(
                "ngspice timed out after 60 seconds.\n"
                "Circuit may be too complex or have a convergence issue.",
                "ngspice Timeout", wx.OK | wx.ICON_ERROR)
            return
        except FileNotFoundError:
            progress.Destroy()
            wx.MessageBox(
                "ngspice not found.\n"
                "Install it with:  sudo apt install ngspice",
                "ngspice Not Found", wx.OK | wx.ICON_ERROR)
            return
        except Exception as e:
            progress.Destroy()
            wx.MessageBox(f"Unexpected error:\n{e}",
                        "ngspice Error", wx.OK | wx.ICON_ERROR)
            return

        # Check for errors
        combined = (result.stdout or '') + '\n' + (result.stderr or '')
        if result.returncode != 0 and not os.path.exists(raw_path):
            err_lines = [l for l in combined.splitlines()
                        if 'error' in l.lower() or 'fatal' in l.lower()]
            err_text = '\n'.join(err_lines[:15]) or combined[:800]
            wx.MessageBox(
                f"ngspice returned error code {result.returncode}.\n\n"
                f"{err_text}",
                "ngspice Error", wx.OK | wx.ICON_ERROR)
            return


        # Show waveform viewer
        if os.path.exists(raw_path):
            viewer = NgspiceWaveformViewer(
                self,
                raw_path=raw_path,
                analysis_type=self.analysis_type,
                cir_path=self.cir_out_path,
                ngspice_output=combined
            )
            viewer.ShowModal()
            viewer.Destroy()
        else:
            # Fallback: show text summary if no raw file produced
            wx.MessageBox(
                f"Simulation finished but no .raw file was produced.\n\n"
                f"ngspice output (last 20 lines):\n"
                + '\n'.join(combined.splitlines()[-20:]),
                "ngspice – No Waveform Data",
                wx.OK | wx.ICON_WARNING)












            


    def _parse_ngspice_output(self, combined, returncode):
        """Parse ngspice raw output into a clean human-readable summary."""
        lines = combined.split('\n')
        
        # Collect data rows per node
        node_data = {}  # {node_name: [float values]}
        current_nodes = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            


            # Detect header line like: Index   time   net_r1_pad1   net_r2_pad1
            if line.startswith('Index') and 'time' in line.lower():
                parts = line.split()
                try:
                    time_idx = next(i for i, p in enumerate(parts) if p.lower() == 'time')
                    raw_nodes = parts[time_idx + 1:]
                    current_nodes = []
                    for node in raw_nodes:
                        # Normalize v(net_r1_pad1) → net_r1_pad1
                        clean = re.sub(r'^v\((.+)\)$', r'\1', node, flags=re.IGNORECASE)
                        # Skip non-node entries like 'alli', 'allv'
                        if clean.lower() in ('alli', 'allv', 'all'):
                            continue
                        current_nodes.append(clean)
                        if clean not in node_data:
                            node_data[clean] = []
                except StopIteration:
                    pass
                continue
            
            # Skip separator lines
            if line.startswith('---'):
                continue
            
            # Try to parse data rows: index  time  val1  val2 ...
            parts = line.split()
            if len(parts) >= 3 and parts[0].isdigit():
                try:
                    values = [float(p) for p in parts[1:]]  # skip index
                    # values[0] = time, values[1:] = node values
                    for i, node in enumerate(current_nodes):
                        if i + 1 < len(values):
                            node_data[node].append(values[i + 1])
                except ValueError:
                    pass
        
        # Build summary
        summary_lines = []
        summary_lines.append("=" * 50)
        summary_lines.append(f"ngspice Simulation Summary")
        summary_lines.append(f"Analysis Type: {self.analysis_type.upper()}")
        summary_lines.append("=" * 50)
        
        if node_data:
            summary_lines.append("")
            summary_lines.append("Node Voltage Summary:")
            summary_lines.append("-" * 50)
            
            for node, values in node_data.items():
                if not values:
                    continue
                vmax = max(values)
                vmin = min(values)
                vavg = sum(values) / len(values)
                vpeak = max(abs(vmax), abs(vmin))
                
                summary_lines.append(f"\nNode: {node}")
                summary_lines.append(f"  Peak voltage  : {vpeak:.4f} V")
                summary_lines.append(f"  Max voltage   : {vmax:.4f} V")
                summary_lines.append(f"  Min voltage   : {vmin:.4f} V")
                summary_lines.append(f"  Avg voltage   : {vavg:.4f} V")
                summary_lines.append(f"  Data points   : {len(values)}")


        else:
            # Check for noise analysis results specifically
            noise_lines = [l.strip() for l in combined.split('\n')
                          if 'inoise' in l.lower() or 'onoise' in l.lower()]
            if noise_lines:
                summary_lines.append("")
                summary_lines.append("Noise Analysis Results:")
                summary_lines.append("-" * 50)
                for nl in noise_lines:
                    summary_lines.append(f"  {nl}")
                summary_lines.append("")
                summary_lines.append("Tip: inoise = input-referred noise, onoise = output noise")
            else:
                summary_lines.append("")
                summary_lines.append("No node data found in output.")
                summary_lines.append("Raw output (last 20 lines):")
                summary_lines.append("-" * 50)
                raw_lines = [l.strip() for l in combined.split('\n') if l.strip()]
                summary_lines.extend(raw_lines[-20:])

        # Add timing info
        timing_found = False
        for tline in combined.split('\n'):
            if 'Total analysis time' in tline or 'Total elapsed time' in tline:
                if not timing_found:
                    summary_lines.append("")
                    summary_lines.append("-" * 50)
                    summary_lines.append("Simulation Timing:")
                    timing_found = True
                summary_lines.append(tline.strip())
        
        if returncode != 0:
            summary_lines.append("")
            summary_lines.append("WARNING: ngspice returned a non-zero exit code.")
            summary_lines.append("Simulation may have encountered errors.")
        
        return '\n'.join(summary_lines)

# ══════════════════════════════════════════════════════════════════════
# MAIN PLUGIN CLASS
# ══════════════════════════════════════════════════════════════════════

class ESimBridgePlugin(pcbnew.ActionPlugin):
    
    def defaults(self):
        self.name = "eSim Simulation Bridge"
        self.category = "eSim Tools"
        self.description = "Launch eSim simulation with one click - supports passive, active & user-provided models"
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(
            os.path.dirname(__file__), 'icon.png'
        )
    
    def Run(self):
        """Main function - called when user clicks the plugin button"""
        
        LOG_FILE = os.path.expanduser("~/.local/share/kicad/esim_bridge.log")
        logging.basicConfig(
            filename=LOG_FILE,
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        logger = logging.getLogger('ESimBridge')
        logger.info("Plugin Run() called - eSim Bridge v2.1.0")
        
        # Delete stale .raw file
        workspace = os.path.expanduser("~/eSim-Workspace")
        project_name = "esim_bridge_project"
        project_folder = os.path.join(workspace, project_name)
        raw_file = os.path.join(project_folder, project_name + ".raw")
        try:
            if os.path.exists(raw_file):
                os.remove(raw_file)
        except Exception:
            pass
        
        

        # ── Step 1: Get schematic path ────────────────────────
        app = wx.App.Get()
        if not app:
            app = wx.App()

        schematic_path = self.get_schematic_path()
        if not schematic_path:
            wx.MessageBox(
                "No schematic found.\nPlease open a schematic first.",
                "eSim Bridge", wx.OK | wx.ICON_ERROR)
            return

        # ── Step 2: Export netlist silently ───────────────────
        netlist_xml_path = "/tmp/esim_bridge_netlist.net"
        if not self.export_netlist(schematic_path, netlist_xml_path):
            wx.MessageBox(
                "Failed to export netlist.\n"
                "Make sure kicad-cli is available.",
                "eSim Bridge Error", wx.OK | wx.ICON_ERROR)
            return

        # ── Step 3: Parse netlist & show tabbed dialog ────────
        converter = SPICEConverter()
        components_pre, nets_pre = converter.parse_full_netlist(netlist_xml_path)

        ktn_dlg = KicadToNgspiceDialog(None, components_pre)
        if ktn_dlg.ShowModal() != wx.ID_OK:
            ktn_dlg.Destroy()
            return

        analysis_type    = ktn_dlg.get_analysis_type()
        analysis_params  = ktn_dlg.get_analysis_params()
        source_overrides = ktn_dlg.get_source_overrides()
        ngmodel_lines    = ktn_dlg.get_ngmodel_lines()
        device_lib_paths = ktn_dlg.get_device_lib_paths()
        subcircuit_paths = ktn_dlg.get_subcircuit_paths()
        ktn_dlg.Destroy()



        # ── Step 3b: Netlist sanity check ────────────────────
        checker = PreflightChecker()
        netlist_issues = checker.run_netlist_checks(components_pre, nets_pre)
        logger.info(f"Netlist check: {len(netlist_issues)} issues found: {netlist_issues}")
        errors   = [m for s, m in netlist_issues if s == 'error']
        warnings = [m for s, m in netlist_issues if s == 'warning']

        if errors:
            error_text = "\n\n".join(errors)
            result = wx.MessageBox(
                f"Netlist Problems Detected:\n\n{error_text}\n\n"
                "These will cause ngspice to fail. Continue anyway?",
                "eSim Bridge - Netlist Check",
                wx.YES_NO | wx.ICON_ERROR)
            if result != wx.YES:
                return
        elif warnings:
            warning_text = "\n\n".join(warnings)
            wx.MessageBox(
                f"Netlist Warnings:\n\n{warning_text}",
                "eSim Bridge - Netlist Check",
                wx.OK | wx.ICON_WARNING)
        
        # ── Step 4: Convert to SPICE format ──────────────────
        progress = wx.ProgressDialog(
            "eSim Bridge",
            "Converting to SPICE format...",
            maximum=3,
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
        )
        
        spice_output_path = "/tmp/esim_bridge_simulation.cir"
        
        converter = SPICEConverter()
        success = converter.convert(
            netlist_path=netlist_xml_path,
            output_path=spice_output_path,
            analysis_type=analysis_type,
            analysis_params=analysis_params
        )
        
        if not success:
            progress.Destroy()
            wx.MessageBox(
                "Failed to convert netlist to SPICE format.",
                "eSim Bridge Error", wx.OK | wx.ICON_ERROR)
            return
        
        # Get unsupported component warnings
        unsupported_summary = converter.get_unsupported_summary()
        # Inject Ngspice Model tab lines into SPICE file
        if ngmodel_lines:
            with open(spice_output_path, 'r') as f:
                content = f.read()
            inject = '\n* -- Ngspice Model Tab --\n' + '\n'.join(ngmodel_lines)
            content = content.replace('\n.end', inject + '\n.end')
            with open(spice_output_path, 'w') as f:
                f.write(content)

        # ── NEW: eSim-SPICE Model Auto-Linker ───────────────────
        try:
            import sys
            plugin_dir = os.path.dirname(__file__)
            if plugin_dir not in sys.path:
                sys.path.insert(0, plugin_dir)
            from esim_spice_linker import SPICEAutoLinker
            linker = SPICEAutoLinker()


            components_raw, nets_raw = converter.parse_full_netlist(netlist_xml_path)
            # Don't re-check components whose models eSim-BRIDGE already resolved
            match_results = linker.check_models(components_raw)
            
            progress.Destroy()  # Close progress before showing report
            
            if not linker.show_report(None, components_raw, match_results):
                return  # User cancelled
            
            esim_models, esim_subcircuits = linker.get_injection_data(match_results)


            # Remove duplicates - eSim-BRIDGE already injected what eSim-SPICE found
            for name in list(esim_subcircuits.keys()):
                if name in converter.required_subcircuits:
                    esim_subcircuits.pop(name)
            for name in list(esim_models.keys()):
                if name in converter.required_models:
                    esim_models.pop(name)



            converter.required_models.update(esim_models)
            converter.required_subcircuits.update(esim_subcircuits)
            
            # Re-write the SPICE file with eSim library models included
            converter._rewrite_with_models(spice_output_path)
        except Exception as e:
            logger.warning(f"eSim-SPICE model linking skipped: {e}")
            try:
                progress.Destroy()
            except Exception:
                pass




        
        # ── Step 6: Prepare eSim project ─────────────────────        
        os.makedirs(project_folder, exist_ok=True)
        # Copy dependency .sub files for any subcircuits that need them
        esim_subckt_dir = os.path.expanduser('~/Downloads/eSim-2.5/library/SubcircuitLibrary')
        for root, dirs, files in os.walk(esim_subckt_dir):
            for filename in files:
                if filename.endswith('.sub') and filename != os.path.basename(spice_output_path):
                    # Check if this .sub is referenced in the .cir file
                    with open(spice_output_path, 'r') as f:
                        cir_content = f.read()
                    if filename.replace('.sub', '') in cir_content or filename in cir_content:
                        shutil.copy(os.path.join(root, filename), project_folder)
        os.makedirs(os.path.join(project_folder, "images"), exist_ok=True)
        
        # Build .cir.out with control block
        with open(spice_output_path, 'r') as f:
            spice_content = f.read()
        

        spice_content = spice_content.replace('.end\n', '').strip() + "\n"
        # Remove existing analysis command to avoid duplicate runs in ngspice
        spice_content = re.sub(r'\.(tran|ac|dc|op|tf)\s+[^\n]*\n', '', spice_content, flags=re.IGNORECASE)
        spice_content += "* Control Statements\n"
        spice_content += ".control\n"

        # Analysis-specific simulation command
        if analysis_type == 'tran':
            step = analysis_params.get('step', '1us')
            stop = analysis_params.get('stop', '10ms')
            start = analysis_params.get('start', '0')
            spice_content += f"tran {step} {stop} {start}\n"
        elif analysis_type == 'ac':
            scale = analysis_params.get('scale', 'dec')
            points = analysis_params.get('points', '100')
            fstart = analysis_params.get('fstart', '1Hz')
            fstop = analysis_params.get('fstop', '1MEGHz')
            spice_content += f"ac {scale} {points} {fstart} {fstop}\n"
        elif analysis_type == 'dc':
            source = analysis_params.get('source', 'V1')
            start = analysis_params.get('start', '0')
            stop = analysis_params.get('stop', '5')
            step = analysis_params.get('step', '0.1')
            spice_content += f"dc {source} {start} {stop} {step}\n"
        elif analysis_type == 'op':
            spice_content += "op\n"

        
        
        elif analysis_type == 'tf':
            output = analysis_params.get('output', 'out')
            source = analysis_params.get('source', 'V1')
            spice_content += f"tf v({output}) {source}\n"
        
        elif analysis_type == 'noise':
            output = analysis_params.get('output', 'out')
            source = analysis_params.get('source', 'V1')
            fstart = analysis_params.get('fstart', '1')
            fstop  = analysis_params.get('fstop', '1Meg')
            points = analysis_params.get('points', '100')
            spice_content += f"noise v({output}) {source} dec {points} {fstart} {fstop}\n"

        
        elif analysis_type == 'sens':
            output = analysis_params.get('output', 'v(out)')
            spice_content += f"op\n"
            spice_content += f"sens {output}\n"

        spice_content += "run\n"
        spice_content += "rusage all\n"
        spice_content += "print allv\n"
        spice_content += "print alli\n"
        spice_content += "print allv > plot_data_v.txt\n"
        spice_content += "print alli > plot_data_i.txt\n"
        spice_content += ".endc\n"
        spice_content += ".end\n"


        
        
        # Delete stale .raw
        raw_file_pre = os.path.join(project_folder, project_name + ".raw")
        try:
            if os.path.exists(raw_file_pre):
                os.remove(raw_file_pre)
        except Exception:
            pass
        
        # Write files
        dest = os.path.join(project_folder, project_name + ".cir.out")
        with open(dest, 'w') as f:
            f.write(spice_content)
        
        cir_dest = os.path.join(project_folder, project_name + ".cir")
        shutil.copy(spice_output_path, cir_dest)
        
        proj_file = os.path.join(project_folder, project_name + ".proj")
        open(proj_file, 'w').close()
        
        # Write analysis file
        analysis_file = os.path.join(project_folder, "analysis")
        if analysis_type == 'ac':
            scale = analysis_params.get('scale', 'dec')
            fstart = analysis_params.get('fstart', '1Hz')
            fstop = analysis_params.get('fstop', '1MEGHz')
            points = analysis_params.get('points', '100')
            analysis_content = f".ac {scale} {points} {fstart} {fstop}"
        elif analysis_type == 'tran':
            start = analysis_params.get('start', '0')
            step = analysis_params.get('step', '1us')
            stop = analysis_params.get('stop', '10ms')
            analysis_content = f".tran {step} {stop} {start}"
        elif analysis_type == 'dc':
            source = analysis_params.get('source', 'V1')
            start = analysis_params.get('start', '0')
            stop = analysis_params.get('stop', '5')
            step = analysis_params.get('step', '0.1')
            analysis_content = f".dc {source} {start} {stop} {step}"
        else:
            analysis_content = ".op"
        
        with open(analysis_file, 'w') as f:
            f.write(analysis_content)
                
        # ── Step 7: Show results / handle OP ─────────────────
        components_temp, _ = converter.parse_full_netlist(netlist_xml_path)
        
        if analysis_type == 'op':
            try:
                env = os.environ.copy()
                env['PYTHONPATH'] = os.path.expanduser(
                    '~/Downloads/eSim-2.5/src')
                result = subprocess.run(
                    ['ngspice', '-b', dest],
                    capture_output=True, text=True, timeout=10,
                    cwd=project_folder, env=env
                )
                output = result.stdout + result.stderr
                lines = [l.strip() for l in output.split('\n') 
                         if '=' in l and ('net_' in l.lower() or 'v(' in l.lower()
                         or any(c.isdigit() for c in l))]
                values = '\n'.join(lines) if lines else output[:500]
            except Exception as e:
                values = f"Could not get values: {e}"
            
            wx.MessageBox(
                f"Operating Point Analysis completed!\n\n"
                f"DC Node Voltages:\n{values}\n\n"
                "Note: OP analysis does not produce a waveform graph.",
                "eSim Bridge - OP Analysis",
                wx.OK | wx.ICON_INFORMATION)
            return
        

        if analysis_type == 'tf':
            try:
                env = os.environ.copy()
                env['PYTHONPATH'] = os.path.expanduser('~/Downloads/eSim-2.5/src')
                result = subprocess.run(
                    ['ngspice', '-b', dest],
                    capture_output=True, text=True, timeout=10,
                    cwd=project_folder, env=env
                )
                output = result.stdout + result.stderr
                output_node = analysis_params.get('output', 'out')
                source = analysis_params.get('source', 'V1')

                tf_val = in_imp = out_imp = None
                for l in output.split('\n'):
                    ll = l.lower()
                    if 'transfer_function' in ll or 'transfer function' in ll:
                        tf_val = l.strip()
                    elif 'input_impedance' in ll or 'input impedance' in ll:
                        in_imp = l.strip()
                    elif 'output_impedance' in ll or 'output impedance' in ll:
                        out_imp = l.strip()

                msg = (
                    f"Transfer Function Analysis\n"
                    f"  Output node : v({output_node})\n"
                    f"  Input source: {source}\n"
                    f"{'─'*40}\n"
                    f"  Gain (v({output_node}) / {source}):\n"
                    f"    {tf_val or 'not found'}\n\n"
                    f"  Input Impedance (seen by {source}):\n"
                    f"    {in_imp or 'not found'}\n\n"
                    f"  Output Impedance (at v({output_node})):\n"
                    f"    {out_imp or 'not found'}\n"
                )
            except Exception as e:
                msg = f"Could not get values: {e}"

            wx.MessageBox(msg, "eSim Bridge - Transfer Function",
                          wx.OK | wx.ICON_INFORMATION)
            return

        if analysis_type == 'sens':
            try:
                env = os.environ.copy()
                env['PYTHONPATH'] = os.path.expanduser('~/Downloads/eSim-2.5/src')
                result = subprocess.run(
                    ['ngspice', '-b', dest],
                    capture_output=True, text=True, timeout=15,
                    cwd=project_folder, env=env
                )
                output = result.stdout + result.stderr
                output_var = analysis_params.get('output', 'v(out)')


                sens_lines = []
                for line in output.split('\n'):
                    line = line.strip()
                    if not line or '=' not in line:
                        continue
                    parts = line.split('=')
                    if len(parts) != 2:
                        continue
                    key = parts[0].strip().lower()
                    val = parts[1].strip()
                    if re.match(r'^[rclvi]\d+$', key):
                        try:
                            float(val)
                            sens_lines.append(line)
                        except ValueError:
                            pass

                if sens_lines:
                    def abs_val(s):
                        try:
                            return abs(float(s.split('=')[1].strip()))
                        except Exception:
                            return 0
                    sens_lines.sort(key=abs_val, reverse=True)
                    table = '\n'.join(f"  {l}" for l in sens_lines[:20])
                else:
                    table = output[:600] or "No sensitivity data found."

                wx.MessageBox(
                    f"Sensitivity Analysis\n"
                    f"  Output : {output_var}\n"
                    f"{'─'*45}\n"
                    f"  Note: Sensitivity requires a DC operating point.\n"
                    f"  If all values are zero, add a DC value to your source\n"
                    f"  (e.g. change V1 from SIN to DC 5).\n\n"
                    f"  Components ranked by impact (highest first):\n\n"
                    f"{table}\n\n"
                    f"  Positive = increasing component increases output\n"
                    f"  Negative = increasing component decreases output",
                    "eSim Bridge – Sensitivity Analysis",
                    wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                wx.MessageBox(f"Sensitivity analysis failed:\n{e}",
                              "eSim Bridge", wx.OK | wx.ICON_ERROR)
            return


        results_dialog = SimulationReadyDialog(
            None, spice_output_path, components_temp,
            analysis_type, analysis_params, unsupported_summary,
            cir_out_path=dest)
        
        if results_dialog.ShowModal() != wx.ID_OK:
            results_dialog.Destroy()
            return
        
        results_dialog.Destroy()
        
        # Delete stale .raw
        try:
            if os.path.exists(raw_file):
                os.remove(raw_file)
        except Exception:
            pass
        
        # Launch eSim
        env = os.environ.copy()
        env['PYTHONPATH'] = os.path.expanduser('~/Downloads/eSim-2.5/src')
        
        subprocess.Popen(
            [os.path.expanduser('~/.esim/env/bin/python3'), 'Application.py'],
            cwd=os.path.expanduser(
                '~/Downloads/eSim-2.5/src/frontEnd'),
            env=env
        )
        
        wx.MessageBox(
            "eSim launched successfully!\n\n"
            "Your project is ready. Inside eSim:\n"
            "1. Double-click 'esim_bridge_project' in the project tree\n"
            "2. Click 'Simulate'\n"
            "3. Click 'Plot' to see the graph",
            "eSim Bridge - Success!",
            wx.OK | wx.ICON_INFORMATION)
    
    def get_schematic_path(self):
        try:
            board = pcbnew.GetBoard()
            if board:
                project_path = board.GetFileName()
                if project_path:
                    sch_path = project_path.replace('.kicad_pcb', '.kicad_sch')
                    if os.path.exists(sch_path):
                        return sch_path
        except:
            pass
        
        dialog = wx.FileDialog(
            None,
            "Select KiCad Schematic File",
            wildcard="KiCad Schematic (*.kicad_sch)|*.kicad_sch",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        )
        
        if dialog.ShowModal() == wx.ID_OK:
            return dialog.GetPath()
        
        return None
    
    def export_netlist(self, schematic_path, output_path):
        try:
            command = [
                'kicad-cli', 'sch', 'export', 'netlist',
                '--output', output_path,
                '--format', 'kicadsexpr',
                schematic_path
            ]
            
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0 and os.path.exists(output_path):
                return True
            else:
                print(f"kicad-cli error: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("Error: kicad-cli timed out")
            return False
        except FileNotFoundError:
            print("Error: kicad-cli not found")
            return False
        except Exception as e:
            print(f"Error: {e}")
            return False


# Register plugin with KiCad
ESimBridgePlugin().register()
