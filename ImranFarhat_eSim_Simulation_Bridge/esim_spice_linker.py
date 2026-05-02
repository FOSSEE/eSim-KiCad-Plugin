# esim_spice_linker.py
# eSim-SPICE v1.0.0 - eSim SPICE Model Auto-Linker
# Automatically finds and links SPICE models from eSim's open-source library
#
# Architecture:
#   ESimLibraryScanner  - Scans eSim's built-in library folders, parses .lib files
#   ModelMatcher        - Matches schematic components to available models
#   ModelStatusReport   - wxPython dialog showing model coverage report
#   TextbookModelGenerator - Generates generic .model cards from textbook parameters
#   SPICEAutoLinker     - Main orchestrator class (called from eSim-BRIDGE)
#
# Search order:
#   1. eSim deviceModelLibrary/ (diodes, BJTs, MOSFETs, JFETs, IGBTs, LEDs)
#   2. eSim SubcircuitLibrary/ (op-amps, 555 timers, voltage regulators, 74-series ICs)
#   3. User's ~/.esim-bridge/models/ (existing ExternalModelLoader)
#   4. eSim-BRIDGE built-in SPICEModelLibrary (hardcoded textbook models)
#   5. TextbookModelGenerator (last-resort generic .model card)
#
# License: GPL-3.0 (same as eSim-BRIDGE)
# Part of: FOSSEE Semester Long Internship, IIT Bombay (Spring 2026)

import os
import re
import json
import logging
import traceback
from datetime import datetime
from difflib import SequenceMatcher

try:
    import wx
except ImportError:
    wx = None  # Allow importing without wx for testing


# ══════════════════════════════════════════════════════════════════════
# LOGGING SETUP
# ══════════════════════════════════════════════════════════════════════

logger = logging.getLogger('eSim-SPICE')


# ══════════════════════════════════════════════════════════════════════
# CLASS 1: ESimLibraryScanner
# Scans eSim's installed library folders and builds a searchable index
# of all available .model and .subckt definitions.
# ══════════════════════════════════════════════════════════════════════

class ESimLibraryScanner:
    """
    Scans eSim 2.5's built-in open-source model libraries:
      - library/deviceModelLibrary/  (basic device .model cards)
      - library/SubcircuitLibrary/   (IC .subckt definitions)
    
    Parses every .lib file and builds an in-memory index for fast lookup.
    All models are open-source and ship with eSim - no proprietary downloads.
    """
    
    # Supported file extensions for model files
    SUPPORTED_EXTENSIONS = ('.lib', '.mod', '.sub', '.spice', '.model')
    
    def __init__(self, esim_home=None):
        """
        Args:
            esim_home: Root path of eSim installation.
                       Defaults to ~/Downloads/eSim-2.5
        """
        # Auto-detect eSim installation path
        self.esim_home = esim_home or self._detect_esim_home()
        
        # Paths to the two main library directories
        self.device_model_dir = os.path.join(
            self.esim_home, 'library', 'deviceModelLibrary') if self.esim_home else None
        self.subcircuit_dir = os.path.join(
            self.esim_home, 'library', 'SubcircuitLibrary') if self.esim_home else None
        
        # ── Index structures ──
        # Device models: {clean_key: {name, type, definition, file_path, category, source}}
        self.device_models = {}
        
        # Subcircuits: {clean_key: {name, definition, file_path, folder_name, source}}
        self.subcircuits = {}
        
        # Category index for browsing: {category: [list of model keys]}
        self.categories = {}
        
        # File path index: {file_path: [list of model/subckt names parsed from it]}
        self.file_index = {}
        
        # Scan status
        self.scan_complete = False
        self.scan_errors = []
        self.total_files_scanned = 0
        
        # Run the scan
        self._scan_all()
    
    def _detect_esim_home(self):
        """
        Auto-detect eSim installation directory.
        Checks common locations on Linux/WSL.
        """
        candidates = [
            os.path.expanduser('~/Downloads/eSim-2.5'),
            os.path.expanduser('~/eSim-2.5'),
            '/usr/share/esim',
            '/opt/eSim-2.5',
            os.path.expanduser('~/Desktop/eSim-2.5'),
        ]
        
        for path in candidates:
            lib_path = os.path.join(path, 'library', 'deviceModelLibrary')
            if os.path.isdir(lib_path):
                logger.info(f"eSim-SPICE: Found eSim at {path}")
                return path
        
        logger.warning("eSim-SPICE: Could not auto-detect eSim installation path")
        return None
    
    def _scan_all(self):
        """Scan both library directories."""
        if not self.esim_home:
            logger.warning("eSim-SPICE: No eSim home directory - skipping library scan")
            return
        
        logger.info(f"eSim-SPICE: Starting library scan at {self.esim_home}")
        
        # Scan deviceModelLibrary
        if self.device_model_dir and os.path.isdir(self.device_model_dir):
            self._scan_device_model_library()
        else:
            self.scan_errors.append(
                f"deviceModelLibrary not found at: {self.device_model_dir}")
        
        # Scan SubcircuitLibrary
        if self.subcircuit_dir and os.path.isdir(self.subcircuit_dir):
            self._scan_subcircuit_library()
        else:
            self.scan_errors.append(
                f"SubcircuitLibrary not found at: {self.subcircuit_dir}")
        
        self.scan_complete = True
        logger.info(
            f"eSim-SPICE: Scan complete - {len(self.device_models)} device models, "
            f"{len(self.subcircuits)} subcircuits from {self.total_files_scanned} files")
    
    def _scan_device_model_library(self):
        """
        Scan eSim's deviceModelLibrary/ directory.
        
        Structure:
            deviceModelLibrary/
            ├── Diode/          → 1N4148.lib, D.lib, LED.lib, ZenerD1N750.lib ...
            ├── Transistor/     → NPN.lib, PNP.lib, BC547B.lib, BC107/ ...
            ├── MOS/            → NMOS-180nm.lib, PMOS-5um.lib ...
            ├── JFET/           → NJF.lib, PJF.lib, BF244B/ ...
            ├── IGBT/           → NIGBT.lib, PIGBT.lib
            ├── LEDs/           → eSim_BlueLED.lib, eSim_RedLED.lib
            ├── Switch/         → switch1.lib
            ├── Misc/           → CORE.lib
            ├── Templates/      → Template versions (generic params)
            ├── Transmission Lines/ → ymod.lib
            └── User Libraries/ → User-uploaded models
        """
        logger.info(f"eSim-SPICE: Scanning deviceModelLibrary at {self.device_model_dir}")
        
        for root, dirs, files in os.walk(self.device_model_dir):
            # Determine category from folder name
            rel_path = os.path.relpath(root, self.device_model_dir)
            category = rel_path.split(os.sep)[0] if rel_path != '.' else 'Uncategorized'
            
            # Initialize category list
            if category not in self.categories:
                self.categories[category] = []
            
            for filename in files:
                if not filename.lower().endswith(self.SUPPORTED_EXTENSIONS):
                    continue
                
                filepath = os.path.join(root, filename)
                self.total_files_scanned += 1
                
                try:
                    models_found = self._parse_lib_file(
                        filepath, category=category, source='deviceModelLibrary')
                    self.file_index[filepath] = models_found
                except Exception as e:
                    self.scan_errors.append(f"Error parsing {filepath}: {e}")
                    logger.debug(f"eSim-SPICE: Error parsing {filepath}: {e}")
    
    def _scan_subcircuit_library(self):
        """
        Scan eSim's SubcircuitLibrary/ directory.
        
        Structure:
            SubcircuitLibrary/
            ├── lm_741/         → lm_741-cache.lib, NPN.lib, PNP.lib ...
            ├── lm555n/         → lm555n-cache.lib ...
            ├── LM358_Sub/      → LM358_Sub-cache.lib ...
            ├── LM317_sub/      → LM317_sub-cache.lib ...
            ├── 74HC86/         → 74HC86-cache.lib ...
            ├── CD4011/         → CD4011-cache.lib, NMOS-180nm.lib, PMOS-180nm.lib
            └── ... (hundreds more)
        
        Key insight: Each IC folder contains a *-cache.lib file which is the
        main subcircuit definition. Other .lib files in the folder are
        dependency models (NPN.lib, PNP.lib, etc.) used by the subcircuit.
        
        We index the folder name as the IC name, and parse the -cache.lib
        for the .subckt definition.
        """
        logger.info(f"eSim-SPICE: Scanning SubcircuitLibrary at {self.subcircuit_dir}")
        
        for root, dirs, files in os.walk(self.subcircuit_dir):
            rel_path = os.path.relpath(root, self.subcircuit_dir)
            folder_name = rel_path.split(os.sep)[0] if rel_path != '.' else ''
            
            for filename in files:
                if not filename.lower().endswith(self.SUPPORTED_EXTENSIONS):
                    continue
                
                filepath = os.path.join(root, filename)
                self.total_files_scanned += 1
                
                try:
                    models_found = self._parse_lib_file(
                        filepath,
                        category='SubcircuitLibrary',
                        source='SubcircuitLibrary',
                        folder_name=folder_name
                    )
                    self.file_index[filepath] = models_found
                except Exception as e:
                    self.scan_errors.append(f"Error parsing {filepath}: {e}")
                    logger.debug(f"eSim-SPICE: Error parsing {filepath}: {e}")
    
    def _parse_lib_file(self, filepath, category='', source='', folder_name=''):
        """
        Parse a single .lib file and extract all .model and .subckt definitions.
        
        Returns list of model/subcircuit names found.
        """
        models_found = []
        
        try:
            with open(filepath, 'r', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            logger.debug(f"eSim-SPICE: Cannot read {filepath}: {e}")
            return models_found
        
        filename = os.path.basename(filepath)
        
        # ── Parse .model definitions ──
        # Matches: .model <name> <type> ( <params> )
        # Also handles multi-line with + continuation
        model_pattern = re.compile(
            r'^\s*\.model\s+(\S+)\s+'
            r'(NPN|PNP|NMOS|PMOS|D|NJF|PJF|R|C|SW|VSWITCH|ISWITCH|LTRA)'
            r'\s*\(([^)]*(?:\n\+[^)]*)*)\)',
            re.MULTILINE | re.IGNORECASE
        )
        
        for match in model_pattern.finditer(content):
            model_name = match.group(1)
            model_type = match.group(2).upper()
            model_params = match.group(3).strip()
            
            # Clean up continuation lines
            model_params = re.sub(r'\n\+\s*', ' ', model_params)
            
            full_definition = f".model {model_name} {model_type}({model_params})"
            
            # Create clean lookup key (lowercase, alphanumeric only)
            clean_key = self._make_clean_key(model_name)
            
            self.device_models[clean_key] = {
                'name': model_name,
                'type': model_type,
                'definition': full_definition,
                'file_path': filepath,
                'filename': filename,
                'category': category,
                'source': source,
                'folder_name': folder_name,
            }
            
            # Also index by variations
            # e.g., for "BC547B" also index "bc547b", "bc547"
            alt_keys = self._generate_alt_keys(model_name)
            for alt_key in alt_keys:
                if alt_key not in self.device_models:
                    self.device_models[alt_key] = self.device_models[clean_key]
            
            if category in self.categories:
                self.categories[category].append(clean_key)
            
            models_found.append(model_name)
        
        # ── Parse .subckt definitions ──
        # Matches: .subckt <name> <nodes...> \n ... \n .ends [name]
        subckt_pattern = re.compile(
            r'(^\s*\.subckt\s+(\S+)\s+[^\n]*\n'
            r'(?:.*?\n)*?'
            r'^\s*\.ends\b[^\n]*)',
            re.MULTILINE | re.IGNORECASE
        )
        
        for match in subckt_pattern.finditer(content):
            full_subckt = match.group(1).strip()
            subckt_name = match.group(2)
            
            clean_key = self._make_clean_key(subckt_name)
            
            self.subcircuits[clean_key] = {
                'name': subckt_name,
                'definition': full_subckt,
                'file_path': filepath,
                'filename': filename,
                'category': category,
                'source': source,
                'folder_name': folder_name,
            }
            
            # Also index the folder name as a key
            # (e.g., folder "lm_741" maps to subcircuit "lm_741")
            if folder_name:
                folder_key = self._make_clean_key(folder_name)
                if folder_key not in self.subcircuits:
                    self.subcircuits[folder_key] = self.subcircuits[clean_key]
            
            # Generate alternate keys
            alt_keys = self._generate_alt_keys(subckt_name)
            for alt_key in alt_keys:
                if alt_key not in self.subcircuits:
                    self.subcircuits[alt_key] = self.subcircuits[clean_key]
            
            models_found.append(subckt_name)
        
        return models_found
    
    def _make_clean_key(self, name):
        """Convert a model/subcircuit name to a clean lookup key."""
        return re.sub(r'[^a-z0-9]', '', name.lower())
    
    def _generate_alt_keys(self, name):
        """
        Generate alternate lookup keys for matching.
        Only generates meaningful, specific keys - avoids generic words.
        
        Examples:
            'BC547B' → ['bc547b', 'bc547']
            'D1N4148' → ['d1n4148', '1n4148']
            'NMOS-180nm' → ['nmos180nm']
            'lm_741' → ['lm741']
            'SN74LS00' → ['sn74ls00', '74ls00']
        """
        keys = set()
        clean = self._make_clean_key(name)
        keys.add(clean)
        
        # Remove common IC prefixes (SN, CD, MC, DM, HD)
        ic_stripped = re.sub(r'^(sn|cd|mc|dm|hd|cy)', '', clean)
        if ic_stripped and len(ic_stripped) >= 4:
            keys.add(ic_stripped)
        
        # Remove trailing letter variants (BC547B → BC547)
        # But only if the last char is a single letter after digits
        no_suffix = re.sub(r'([0-9])[a-z]$', r'\1', clean)
        if no_suffix != clean and len(no_suffix) >= 3:
            keys.add(no_suffix)
        
        # Remove 'cache', 'rescue', 'sub' suffixes from library naming
        no_lib_suffix = re.sub(r'(cache|rescue)$', '', clean)
        if no_lib_suffix != clean and len(no_lib_suffix) >= 3:
            keys.add(no_lib_suffix)
        
        # For names with _sub suffix (like LM317_sub), remove it
        if clean.endswith('sub'):
            no_sub = clean[:-3]
            if len(no_sub) >= 3:
                keys.add(no_sub)
        
        return keys
    
    # ── Blacklisted keys that are too generic to match ──
    GENERIC_KEYS = {
        'and', 'or', 'not', 'nor', 'nand', 'xor', 'xnor', 'buffer',
        'nmos', 'pmos', 'npn', 'pnp', 'njf', 'pjf',
        'd', 'r', 'c', 'l', 'sw', 'switch', 'mux', 'demux',
        'dff', 'tff', 'jkff', 'sram', 'core',
        'switch1', 'fulladder', 'halfadder', 'fullsub', 'halfsub',
    }
    
    # ── Public lookup methods ──
    
    def _match_score(self, search_clean, candidate_key, candidate_data):
        """
        Calculate a match score between search term and candidate.
        Higher score = better match. Returns 0 for no match.
        
        Scoring:
            100 = Exact match (search == key)
             90 = Exact folder name match
             80 = Search equals key with common prefix/suffix removed
             60 = Key starts with search or search starts with key (full token)
             40 = Key contains search as a whole word boundary match
              0 = No meaningful match (reject)
        """
        if not search_clean or not candidate_key:
            return 0
        
        # Skip generic/common keys that would cause false matches
        if candidate_key in self.GENERIC_KEYS:
            return 0
        
        # Exact match
        if search_clean == candidate_key:
            return 100
        
        # Check folder_name match (most reliable for subcircuits)
        folder = candidate_data.get('folder_name', '')
        if folder:
            folder_clean = self._make_clean_key(folder)
            if folder_clean and search_clean == folder_clean:
                return 90
            # Also check common variations: sn74ls00 matches 74ls00
            folder_stripped = re.sub(r'^(sn|cd|mc|dm|hd|cy)', '', folder_clean)
            search_stripped = re.sub(r'^(sn|cd|mc|dm|hd|cy)', '', search_clean)
            if folder_stripped and search_stripped and folder_stripped == search_stripped:
                return 88
        
        # Match with common prefixes removed (sn7400 == 7400)
        prefixes_to_strip = [r'^sn', r'^cd', r'^mc', r'^dm', r'^hd', r'^cy',
                            r'^lm', r'^lt', r'^tl', r'^ic', r'^q', r'^d', r'^m']
        search_stripped = search_clean
        for prefix in prefixes_to_strip:
            search_stripped = re.sub(prefix, '', search_stripped)
        
        candidate_stripped = candidate_key
        for prefix in prefixes_to_strip:
            candidate_stripped = re.sub(prefix, '', candidate_stripped)
        
        if (search_stripped and candidate_stripped and 
            len(search_stripped) >= 3 and search_stripped == candidate_stripped):
            return 80
        
        # One starts with the other (but both must be meaningful length)
        if len(search_clean) >= 4 and len(candidate_key) >= 4:
            if candidate_key.startswith(search_clean):
                return 60
            if search_clean.startswith(candidate_key):
                return 60
        
        # No match
        return 0
    
    def find_device_model(self, component_value, description=''):
        """
        Search eSim's device model library for a match.
        Uses strict scoring to avoid false positives.
        
        Args:
            component_value: Component value from KiCad (e.g., "BC547", "1N4148")
            description: Additional text to help matching
        
        Returns:
            dict with keys: name, type, definition, file_path, source
            or None if not found
        """
        clean_value = self._make_clean_key(component_value)
        
        if not clean_value or len(clean_value) < 1:
            return None
        
        # Strategy 1: Direct key lookup (exact match)
        if clean_value in self.device_models:
            return self.device_models[clean_value]
        
        # Strategy 2: Try alternate keys (exact match only)
        alt_keys = self._generate_alt_keys(component_value)
        for alt_key in alt_keys:
            if alt_key in self.device_models and alt_key not in self.GENERIC_KEYS:
                return self.device_models[alt_key]
        
        # Strategy 3: Score-based matching
        best_score = 0
        best_match = None
        
        for key, data in self.device_models.items():
            score = self._match_score(clean_value, key, data)
            if score > best_score:
                best_score = score
                best_match = data
        
        if best_score >= 60:
            return best_match
        
        return None
    
    def find_subcircuit(self, component_value, description=''):
        """
        Search eSim's subcircuit library for a match.
        Uses strict scoring to avoid false positives.
        
        For 74-series ICs (7400, 7402, 74HC86, etc.), matches against
        eSim folder names like SN74LS00, CD4011, etc.
        
        Args:
            component_value: Component value from KiCad (e.g., "LM741", "7400")
            description: Additional text to help matching
        
        Returns:
            dict with keys: name, definition, file_path, source
            or None if not found
        """
        clean_value = self._make_clean_key(component_value)
        
        if not clean_value or len(clean_value) < 2:
            return None
        
        # Strategy 1: Direct key lookup (exact match)
        if clean_value in self.subcircuits:
            data = self.subcircuits[clean_value]
            # Verify it's not a generic key
            if clean_value not in self.GENERIC_KEYS:
                return data
        
        # Strategy 2: Try alternate keys (exact match only)
        alt_keys = self._generate_alt_keys(component_value)
        for alt_key in alt_keys:
            if alt_key in self.subcircuits and alt_key not in self.GENERIC_KEYS:
                return self.subcircuits[alt_key]
        
        # Strategy 3: Score-based matching against all candidates
        best_score = 0
        best_match = None
        
        for key, data in self.subcircuits.items():
            score = self._match_score(clean_value, key, data)
            if score > best_score:
                best_score = score
                best_match = data
        
        if best_score >= 60:
            return best_match


        # Strategy 4: For 74-series, try with SN/CD prefix added
        if re.match(r'^\d{2,4}', clean_value):
            for prefix in ['sn', 'sn74ls', 'sn74', 'cd', 'cd40', 'mc74hc']:
                prefixed = prefix + clean_value
                if prefixed in self.subcircuits:
                    return self.subcircuits[prefixed]
            
            # Also try: 7402 → sn74ls02, 7486 → sn74ls86, etc.
            # Strip leading '74' or '7' and retry with LS/HC prefixes
            if clean_value.startswith('74'):
                suffix = clean_value[2:]   # '7402' → '02'
            elif clean_value.startswith('7'):
                suffix = clean_value[1:]   # '7400' → '400' fallback
            else:
                suffix = clean_value
            
            if suffix:
                for prefix in ['sn74ls', 'sn74hc', 'sn74', 'cd74ls', 'cd74hc']:
                    prefixed = prefix + suffix
                    if prefixed in self.subcircuits:
                        return self.subcircuits[prefixed]
        
        # Strategy 5: Try matching just the folder names directly
        for key, data in self.subcircuits.items():
            folder = data.get('folder_name', '')
            if folder:
                folder_clean = self._make_clean_key(folder)
                # Exact folder match
                if folder_clean == clean_value:
                    return data
                # Folder without common prefixes
                folder_stripped = re.sub(r'^(sn|cd|mc|dm|hd)', '', folder_clean)
                if folder_stripped and folder_stripped == clean_value and len(clean_value) >= 4:
                    return data
        
        return None
    
    def get_all_dependencies(self, subcircuit_data):
        """
        For a subcircuit, find all dependency .lib files in the same folder.
        
        eSim subcircuits often depend on NPN.lib, PNP.lib, D.lib etc.
        in the same directory. This method collects all of them.
        
        Returns:
            list of dicts: [{name, type, definition, file_path}, ...]
        """
        dependencies = []
        
        if not subcircuit_data or 'file_path' not in subcircuit_data:
            return dependencies
        
        subckt_dir = os.path.dirname(subcircuit_data['file_path'])
        
        for filename in os.listdir(subckt_dir):
            if not filename.lower().endswith(self.SUPPORTED_EXTENSIONS):
                continue
            
            filepath = os.path.join(subckt_dir, filename)
            
            # Skip the main subcircuit file itself
            if filepath == subcircuit_data['file_path']:
                continue
            
            # Parse dependency file for .model definitions
            try:
                with open(filepath, 'r', errors='ignore') as f:
                    content = f.read()
                
                model_pattern = re.compile(
                    r'^\s*\.model\s+(\S+)\s+'
                    r'(NPN|PNP|NMOS|PMOS|D|NJF|PJF)\s*\(([^)]*)\)',
                    re.MULTILINE | re.IGNORECASE
                )
                
                for match in model_pattern.finditer(content):
                    dep_name = match.group(1)
                    dep_type = match.group(2).upper()
                    dep_params = match.group(3).strip()
                    dep_def = f".model {dep_name} {dep_type}({dep_params})"
                    
                    dependencies.append({
                        'name': dep_name,
                        'type': dep_type,
                        'definition': dep_def,
                        'file_path': filepath,
                    })
            except Exception:
                pass
        
        return dependencies
    
    def get_stats(self):
        """Return scan statistics."""
        return {
            'esim_home': self.esim_home,
            'esim_found': self.esim_home is not None and os.path.isdir(
                self.esim_home) if self.esim_home else False,
            'device_model_count': len({v['name'] for v in self.device_models.values()}),
            'subcircuit_count': len({v['name'] for v in self.subcircuits.values()}),
            'total_files_scanned': self.total_files_scanned,
            'categories': list(self.categories.keys()),
            'scan_errors': len(self.scan_errors),
            'scan_complete': self.scan_complete,
        }
    
    def get_summary_text(self):
        """Human-readable summary for UI display."""
        stats = self.get_stats()
        
        if not stats['esim_found']:
            return (
                "eSim installation not found.\n"
                "Expected at: ~/Downloads/eSim-2.5\n"
                "eSim library models are not available."
            )
        
        return (
            f"eSim Library Scanner (eSim-SPICE v1.0)\n"
            f"eSim home: {self.esim_home}\n"
            f"Device models indexed: {stats['device_model_count']}\n"
            f"Subcircuits indexed: {stats['subcircuit_count']}\n"
            f"Files scanned: {stats['total_files_scanned']}\n"
            f"Categories: {', '.join(stats['categories'])}"
        )


# ══════════════════════════════════════════════════════════════════════
# TEXTBOOK MODEL GENERATOR
# Generates basic .model cards from textbook parameters as last resort
# ══════════════════════════════════════════════════════════════════════

class TextbookModelGenerator:
    """
    Generates generic SPICE .model cards using textbook-standard parameters.
    
    These are NOT proprietary - they are published values from standard
    electronics textbooks (Sedra/Smith, Razavi, Boylestad, etc.)
    
    Used as a LAST RESORT when:
      - eSim's built-in library has no match
      - User's external folder has no match
      - eSim-BRIDGE's hardcoded library has no match
    
    The generated models are approximate and suitable for educational
    simulation (which is eSim's primary use case).
    """
    
    # ── Textbook parameter database (JSON-style) ──
    # All values are from standard electronics references
    
    TEXTBOOK_DIODES = {
        '1n4148': {'IS': '2.52e-9', 'RS': '0.568', 'N': '1.752', 'BV': '100', 'IBV': '100u', 'CJO': '4p', 'M': '0.4', 'TT': '5.76n'},
        '1n4007': {'IS': '7.02e-9', 'RS': '0.0341', 'N': '1.8', 'BV': '1000', 'IBV': '5u', 'CJO': '26.5p', 'M': '0.35', 'TT': '4.32u'},
        '1n4001': {'IS': '29.5e-9', 'RS': '0.073', 'N': '1.96', 'BV': '50', 'IBV': '5u', 'CJO': '26.5p', 'M': '0.35'},
        '1n5819': {'IS': '40.7e-9', 'RS': '0.042', 'N': '1.2', 'BV': '40', 'IBV': '1m', 'CJO': '110p'},
        'generic_diode': {'IS': '1e-14', 'N': '1.0', 'RS': '0', 'CJO': '10p', 'BV': '100', 'IBV': '100u'},
        'generic_led': {'IS': '2.52e-9', 'N': '1.752', 'RS': '0.568', 'CJO': '825p', 'BV': '30', 'IBV': '10u'},
        'generic_zener': {'IS': '1e-14', 'N': '1.0', 'RS': '10', 'BV': '5.1', 'IBV': '5m', 'CJO': '50p'},
    }
    
    TEXTBOOK_NPN = {
        '2n2222': {'IS': '14.34e-15', 'BF': '255.9', 'VAF': '74.03', 'IKF': '0.2847', 'RB': '10', 'RC': '1', 'CJC': '7.306p', 'CJE': '22.01p', 'TF': '0.345n', 'TR': '46.91n'},
        '2n3904': {'IS': '6.734e-15', 'BF': '416.4', 'VAF': '74.03', 'IKF': '66.78e-3', 'RB': '10', 'RC': '1', 'CJC': '3.638p', 'CJE': '4.493p', 'TF': '0.301n', 'TR': '239.5n'},
        'bc547': {'IS': '1.8e-14', 'BF': '400', 'VAF': '80', 'IKF': '0.1', 'RB': '10', 'RC': '1', 'CJC': '5.25p', 'CJE': '11.5p', 'TF': '0.64n', 'TR': '50n'},
        'bc548': {'IS': '1.95e-14', 'BF': '400', 'VAF': '80', 'IKF': '0.08', 'RB': '10', 'RC': '1', 'CJC': '5.25p', 'CJE': '11.5p', 'TF': '0.64n', 'TR': '50n'},
        'generic_npn': {'IS': '1e-15', 'BF': '100', 'VAF': '100', 'CJC': '10p', 'CJE': '15p', 'RB': '100', 'TF': '0.3n'},
    }
    
    TEXTBOOK_PNP = {
        '2n3906': {'IS': '1.41e-15', 'BF': '180.7', 'VAF': '18.7', 'IKF': '80e-3', 'RB': '10', 'RC': '2.5', 'CJC': '9.728p', 'CJE': '8.063p', 'TF': '0.3n', 'TR': '50n'},
        '2n2907': {'IS': '650.6e-18', 'BF': '231.7', 'VAF': '116.1', 'IKF': '0.1856', 'RB': '10', 'RC': '1', 'CJC': '14.76p', 'CJE': '19.82p', 'TF': '0.5n', 'TR': '50n'},
        'bc557': {'IS': '2e-14', 'BF': '290', 'VAF': '60', 'IKF': '0.1', 'RB': '10', 'RC': '1', 'CJC': '7.5p', 'CJE': '12.5p', 'TF': '0.6n', 'TR': '50n'},
        'bc558': {'IS': '2e-14', 'BF': '290', 'VAF': '60', 'IKF': '0.1', 'RB': '10', 'RC': '1', 'CJC': '7.5p', 'CJE': '12.5p', 'TF': '0.6n', 'TR': '50n'},
        'generic_pnp': {'IS': '1e-15', 'BF': '100', 'VAF': '100', 'CJC': '10p', 'CJE': '15p', 'RB': '100', 'TF': '0.3n'},
    }
    
    TEXTBOOK_NMOS = {
        '2n7000': {'LEVEL': '3', 'VTO': '2.0', 'KP': '0.15', 'RS': '5.0', 'RD': '1.5', 'CBD': '35p', 'CGSO': '40p', 'CGDO': '5p'},
        '2n7002': {'LEVEL': '3', 'VTO': '1.8', 'KP': '0.15', 'RS': '5.0', 'RD': '1.5', 'CBD': '35p', 'CGSO': '40p', 'CGDO': '5p'},
        'irf540': {'LEVEL': '3', 'VTO': '3.0', 'KP': '20.43', 'RS': '0.0768', 'RD': '0.2', 'CBD': '1.36n', 'CGSO': '1.95n', 'CGDO': '0.13n'},
        'bs170': {'LEVEL': '3', 'VTO': '1.5', 'KP': '0.12', 'RS': '5.0', 'RD': '2.0', 'CBD': '30p', 'CGSO': '35p', 'CGDO': '5p'},
        'generic_nmos': {'LEVEL': '1', 'VTO': '0.7', 'KP': '110u', 'LAMBDA': '0.04'},
    }
    
    TEXTBOOK_PMOS = {
        'irf9540': {'LEVEL': '3', 'VTO': '-3.0', 'KP': '10.2', 'RS': '0.12', 'RD': '0.3', 'CBD': '1.36n', 'CGSO': '1.95n', 'CGDO': '0.13n'},
        'bs250': {'LEVEL': '3', 'VTO': '-2.0', 'KP': '0.06', 'RS': '8.0', 'RD': '3.0', 'CBD': '30p', 'CGSO': '35p', 'CGDO': '5p'},
        'generic_pmos': {'LEVEL': '1', 'VTO': '-0.7', 'KP': '50u', 'LAMBDA': '0.04'},
    }
    
    # ── Equivalence table: common equivalent substitutions ──
    # Maps component names to known equivalents available in eSim
    EQUIVALENTS = {
        # BJT NPN equivalents
        'bc547': ['bc547b', '2n2222', '2n3904'],
        'bc547b': ['bc547', '2n2222', '2n3904'],
        'bc548': ['bc547', 'bc547b', '2n3904'],
        '2n2222': ['2n2222a', '2n3904', 'bc547'],
        '2n2222a': ['2n2222', '2n3904', 'bc547'],
        '2n3904': ['2n2222', 'bc547', 'bc548'],
        '2n2219': ['2n2222', '2n3904'],
        
        # BJT PNP equivalents
        'bc557': ['bc558', '2n3906', '2n2907'],
        'bc558': ['bc557', '2n3906'],
        '2n3906': ['2n2907', 'bc557'],
        '2n2907': ['2n3906', 'bc557'],
        
        # Diode equivalents
        '1n4001': ['1n4002', '1n4003', '1n4004', '1n4007'],
        '1n4002': ['1n4001', '1n4003', '1n4007'],
        '1n4003': ['1n4001', '1n4007'],
        '1n4004': ['1n4001', '1n4007'],
        '1n4007': ['1n4001', '1n4004'],
        '1n5817': ['1n5819', '1n5818'],
        '1n5819': ['1n5817', '1n5818'],
        
        # Op-amp equivalents
        'lm741': ['ua741', 'lm741', 'lm_741', 'mc1741'],
        'ua741': ['lm741', 'lm_741', 'mc1741'],
        'lm358': ['lm358', 'lm324'],
        'lm324': ['lm358'],
        
        # MOSFET equivalents
        'irf540': ['irf540n'],
        'irf540n': ['irf540'],
        '7402': [],   # NOR gate - not in eSim 2.5 library


        # 74-series gate equivalents (based on eSim 2.5 library)
        '7400': ['sn74ls00'],          # NAND  - eSim has SN74LS00
        # '7402': ['sn7432'],            # NOR   - no direct match; SN7432 is OR (note for user)
        '7404': ['sn7404', '74ls04'], # NOT   - eSim has SN7404
        '7408': ['sn7408'],            # AND   - eSim has SN7408
        '7432': ['sn7432'],            # OR    - eSim has SN7432
        '7420': ['sn7420'],            # NAND4 - eSim has SN7420
        '74hc86': ['74hc86'],          # XOR   - eSim has 74HC86
        '74ls04': ['sn7404', '74ls04'],
        '74ls00': ['sn74ls00'],
    }
    
    @classmethod
    def generate_model(cls, component_value, component_type='auto'):
        """
        Generate a .model card from textbook parameters.
        
        Args:
            component_value: e.g., "BC547", "1N4148", "2N7000"
            component_type: 'D', 'NPN', 'PNP', 'NMOS', 'PMOS', or 'auto'
        
        Returns:
            (model_name, model_definition, model_type) or (None, None, None)
        """
        clean = re.sub(r'[^a-z0-9]', '', component_value.lower())
        
        # Auto-detect type if not specified
        if component_type == 'auto':
            component_type = cls._detect_type(clean, component_value)
        
        if component_type == 'D':
            return cls._generate_diode(clean, component_value)
        elif component_type == 'NPN':
            return cls._generate_npn(clean, component_value)
        elif component_type == 'PNP':
            return cls._generate_pnp(clean, component_value)
        elif component_type == 'NMOS':
            return cls._generate_nmos(clean, component_value)
        elif component_type == 'PMOS':
            return cls._generate_pmos(clean, component_value)
        
        return None, None, None
    
    @classmethod
    def _detect_type(cls, clean, original):
        """Auto-detect component type from name."""
        orig_lower = original.lower()
        
        if clean.startswith('1n') or 'diode' in orig_lower or 'led' in orig_lower:
            return 'D'
        if any(k in clean for k in ['2n2222', '2n3904', 'bc547', 'bc548', '2n2219', 'tip31']):
            return 'NPN'
        if any(k in clean for k in ['2n3906', '2n2907', 'bc557', 'bc558', 'tip32']):
            return 'PNP'
        if any(k in clean for k in ['irf9', 'bs250']) or 'pmos' in orig_lower or 'pchannel' in orig_lower:
            return 'PMOS'
        if any(k in clean for k in ['irf', '2n7', 'bs170']) or 'nmos' in orig_lower or 'nchannel' in orig_lower:
            return 'NMOS'
        if 'npn' in orig_lower:
            return 'NPN'
        if 'pnp' in orig_lower:
            return 'PNP'
        
        return None
    
    @classmethod
    def _generate_diode(cls, clean, original):
        """Generate a diode .model card."""
        # Try exact match in textbook database
        for key, params in cls.TEXTBOOK_DIODES.items():
            key_clean = re.sub(r'[^a-z0-9]', '', key)
            if key_clean in clean or clean in key_clean:
                model_name = f"D_{original.upper().replace(' ', '_')}"
                param_str = ' '.join(f"{k}={v}" for k, v in params.items())
                definition = f".model {model_name} D({param_str})"
                return model_name, definition, 'D'
        
        # Check for LED
        if 'led' in clean:
            params = cls.TEXTBOOK_DIODES['generic_led']
            model_name = f"D_{original.upper().replace(' ', '_')}"
            param_str = ' '.join(f"{k}={v}" for k, v in params.items())
            definition = f".model {model_name} D({param_str})"
            return model_name, definition, 'D'
        
        # Check for Zener
        if 'zener' in clean or 'bzt' in clean or 'bzx' in clean:
            params = cls.TEXTBOOK_DIODES['generic_zener']
            model_name = f"D_{original.upper().replace(' ', '_')}"
            param_str = ' '.join(f"{k}={v}" for k, v in params.items())
            definition = f".model {model_name} D({param_str})"
            return model_name, definition, 'D'
        
        # Generic fallback
        params = cls.TEXTBOOK_DIODES['generic_diode']
        model_name = f"D_{original.upper().replace(' ', '_')}"
        param_str = ' '.join(f"{k}={v}" for k, v in params.items())
        definition = f".model {model_name} D({param_str})"
        return model_name, definition, 'D'
    
    @classmethod
    def _generate_npn(cls, clean, original):
        """Generate an NPN BJT .model card."""
        for key, params in cls.TEXTBOOK_NPN.items():
            key_clean = re.sub(r'[^a-z0-9]', '', key)
            if key_clean in clean or clean in key_clean:
                model_name = f"Q_{original.upper().replace(' ', '_')}"
                param_str = ' '.join(f"{k}={v}" for k, v in params.items())
                definition = f".model {model_name} NPN({param_str})"
                return model_name, definition, 'NPN'
        
        # Generic fallback
        params = cls.TEXTBOOK_NPN['generic_npn']
        model_name = f"Q_{original.upper().replace(' ', '_')}"
        param_str = ' '.join(f"{k}={v}" for k, v in params.items())
        definition = f".model {model_name} NPN({param_str})"
        return model_name, definition, 'NPN'
    
    @classmethod
    def _generate_pnp(cls, clean, original):
        """Generate a PNP BJT .model card."""
        for key, params in cls.TEXTBOOK_PNP.items():
            key_clean = re.sub(r'[^a-z0-9]', '', key)
            if key_clean in clean or clean in key_clean:
                model_name = f"Q_{original.upper().replace(' ', '_')}"
                param_str = ' '.join(f"{k}={v}" for k, v in params.items())
                definition = f".model {model_name} PNP({param_str})"
                return model_name, definition, 'PNP'
        
        params = cls.TEXTBOOK_PNP['generic_pnp']
        model_name = f"Q_{original.upper().replace(' ', '_')}"
        param_str = ' '.join(f"{k}={v}" for k, v in params.items())
        definition = f".model {model_name} PNP({param_str})"
        return model_name, definition, 'PNP'
    
    @classmethod
    def _generate_nmos(cls, clean, original):
        """Generate an NMOS MOSFET .model card."""
        for key, params in cls.TEXTBOOK_NMOS.items():
            key_clean = re.sub(r'[^a-z0-9]', '', key)
            if key_clean in clean or clean in key_clean:
                model_name = f"M_{original.upper().replace(' ', '_')}"
                param_str = ' '.join(f"{k}={v}" for k, v in params.items())
                definition = f".model {model_name} NMOS({param_str})"
                return model_name, definition, 'NMOS'
        
        params = cls.TEXTBOOK_NMOS['generic_nmos']
        model_name = f"M_{original.upper().replace(' ', '_')}"
        param_str = ' '.join(f"{k}={v}" for k, v in params.items())
        definition = f".model {model_name} NMOS({param_str})"
        return model_name, definition, 'NMOS'
    
    @classmethod
    def _generate_pmos(cls, clean, original):
        """Generate a PMOS MOSFET .model card."""
        for key, params in cls.TEXTBOOK_PMOS.items():
            key_clean = re.sub(r'[^a-z0-9]', '', key)
            if key_clean in clean or clean in key_clean:
                model_name = f"M_{original.upper().replace(' ', '_')}"
                param_str = ' '.join(f"{k}={v}" for k, v in params.items())
                definition = f".model {model_name} PMOS({param_str})"
                return model_name, definition, 'PMOS'
        
        params = cls.TEXTBOOK_PMOS['generic_pmos']
        model_name = f"M_{original.upper().replace(' ', '_')}"
        param_str = ' '.join(f"{k}={v}" for k, v in params.items())
        definition = f".model {model_name} PMOS({param_str})"
        return model_name, definition, 'PMOS'
    
    @classmethod
    def get_equivalents(cls, component_value):
        """
        Get list of known equivalent components.
        
        Returns list of equivalent component names, or empty list.
        """
        clean = re.sub(r'[^a-z0-9]', '', component_value.lower())
        
        for key, equivalents in cls.EQUIVALENTS.items():
            key_clean = re.sub(r'[^a-z0-9]', '', key)
            if key_clean == clean:
                return equivalents
        
        return []


# ══════════════════════════════════════════════════════════════════════
# CLASS 2: ModelMatcher
# Orchestrates the full search across all sources
# ══════════════════════════════════════════════════════════════════════

class ModelMatcher:
    """
    Main matching engine for eSim-SPICE.
    
    For each component in a schematic, searches across all available
    sources in priority order and returns the best match.
    
    Search order:
      1. eSim deviceModelLibrary (via ESimLibraryScanner)
      2. eSim SubcircuitLibrary (via ESimLibraryScanner)
      3. User's ~/.esim-bridge/models/ (via ExternalModelLoader from eSim-BRIDGE)
      4. eSim-BRIDGE built-in SPICEModelLibrary
      5. TextbookModelGenerator (last resort)
    """
    
    # Match result status codes
    STATUS_FOUND_ESIM_DEVICE = 'esim_device'      # Found in eSim deviceModelLibrary
    STATUS_FOUND_ESIM_SUBCKT = 'esim_subcircuit'   # Found in eSim SubcircuitLibrary
    STATUS_FOUND_EXTERNAL = 'external'              # Found in user's external folder
    STATUS_FOUND_BUILTIN = 'builtin'                # Found in eSim-BRIDGE built-in library
    STATUS_GENERATED = 'generated'                  # Generated from textbook params
    STATUS_EQUIVALENT = 'equivalent'                # Using a suggested equivalent
    STATUS_NOT_FOUND = 'not_found'                  # No match anywhere
    STATUS_PASSIVE = 'passive'                      # Passive component (R, C, L) - no model needed
    STATUS_SOURCE = 'source'                        # Voltage/current source - no model needed
    
    def __init__(self, esim_scanner=None, external_loader=None):
        """
        Args:
            esim_scanner: ESimLibraryScanner instance (created if None)
            external_loader: ExternalModelLoader from eSim-BRIDGE (created if None)
        """
        self.scanner = esim_scanner or ESimLibraryScanner()
        
        # Import ExternalModelLoader from eSim-BRIDGE if available
        if external_loader:
            self.external_loader = external_loader
        else:
            try:
                # Try to import from eSim-BRIDGE's module
                from esim_bridge import ExternalModelLoader as ExtLoader
                self.external_loader = ExtLoader()
            except ImportError:
                self.external_loader = None
        
        # Cache for match results
        self._cache = {}
    
    def match_component(self, ref, value, description='', lib_name=''):
        """
        Find the best SPICE model for a component.
        
        Args:
            ref: Reference designator (e.g., "R1", "Q1", "U1")
            value: Component value (e.g., "10k", "BC547", "LM741")
            description: Component description from KiCad
            lib_name: KiCad library name
        
        Returns:
            MatchResult dict with keys:
                status: one of the STATUS_* constants
                model_name: SPICE model name (or None)
                model_definition: full .model/.subckt text (or None)
                model_type: 'D', 'NPN', 'PNP', 'NMOS', 'PMOS', etc. (or None)
                source_description: human-readable source description
                file_path: path to the source .lib file (or None)
                dependencies: list of dependency models needed (or [])
                equivalents: list of suggested equivalent components (or [])
                is_model: True if .model, False if .subckt
        """
        # Check cache
        cache_key = f"{ref}_{value}_{description}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        prefix = ref[0].upper() if ref else ''
        search_text = value + ' ' + description + ' ' + lib_name
        
        # ── Passive components: no model needed ──
        if prefix in ('R', 'C', 'L'):
            result = self._make_result(
                status=self.STATUS_PASSIVE,
                source_description=f"Passive component ({prefix}) - no SPICE model needed"
            )
            self._cache[cache_key] = result
            return result


        # ── Voltage/current sources and batteries: no model needed ──
        if prefix in ('V', 'I') or ref.upper().startswith('BT'):
            result = self._make_result(
                status=self.STATUS_SOURCE,
                source_description=f"Source ({ref}) - uses built-in SPICE source syntax"
            )
            self._cache[cache_key] = result
            return result
        

        # ── SW* prefix: DIP switches, push-buttons ──
        if ref.upper().startswith('SW'):
            result = self._make_result(
                status=self.STATUS_PASSIVE,
                source_description=(
                    f"Switch ({ref}) - modeled as 1Ω resistor by eSim-BRIDGE; "
                    "no SPICE .model needed"))
            self._cache[cache_key] = result
            return result


        # ── Active components: search for model ──
        
        # STEP 1: Search eSim deviceModelLibrary
        esim_model = self.scanner.find_device_model(value, description)
        if esim_model:
            result = self._make_result(
                status=self.STATUS_FOUND_ESIM_DEVICE,
                model_name=esim_model['name'],
                model_definition=esim_model['definition'],
                model_type=esim_model.get('type', ''),
                source_description=f"eSim {esim_model['category']} library: {esim_model['filename']}",
                file_path=esim_model['file_path'],
                is_model=True,
            )
            self._cache[cache_key] = result
            return result
        
        # STEP 2: Search eSim SubcircuitLibrary
        esim_subckt = self.scanner.find_subcircuit(value, description)
        if esim_subckt:
            # Also get dependency models
            deps = self.scanner.get_all_dependencies(esim_subckt)
            
            result = self._make_result(
                status=self.STATUS_FOUND_ESIM_SUBCKT,
                model_name=esim_subckt['name'],
                model_definition=esim_subckt['definition'],
                source_description=f"eSim SubcircuitLibrary: {esim_subckt.get('folder_name', '')} / {esim_subckt['filename']}",
                file_path=esim_subckt['file_path'],
                dependencies=deps,
                is_model=False,
            )
            self._cache[cache_key] = result
            return result
        
        # STEP 3: Search user's external models (~/.esim-bridge/models/)
        if self.external_loader:
            ext_name, ext_def, ext_type = self.external_loader.find_model(
                value, description)
            if ext_name:
                result = self._make_result(
                    status=self.STATUS_FOUND_EXTERNAL,
                    model_name=ext_name,
                    model_definition=ext_def,
                    model_type=ext_type,
                    source_description=f"User external models: {self.external_loader.model_dir}",
                    is_model=True,
                )
                self._cache[cache_key] = result
                return result
            
            ext_subckt_name, ext_subckt_def = self.external_loader.find_subcircuit(
                value, description)
            if ext_subckt_name:
                result = self._make_result(
                    status=self.STATUS_FOUND_EXTERNAL,
                    model_name=ext_subckt_name,
                    model_definition=ext_subckt_def,
                    source_description=f"User external models: {self.external_loader.model_dir}",
                    is_model=False,
                )
                self._cache[cache_key] = result
                return result
        
        # STEP 4: Try equivalents - search eSim library for known substitutes
        equivalents = TextbookModelGenerator.get_equivalents(value)
        for equiv in equivalents:
            esim_equiv = self.scanner.find_device_model(equiv)
            if esim_equiv:
                result = self._make_result(
                    status=self.STATUS_EQUIVALENT,
                    model_name=esim_equiv['name'],
                    model_definition=esim_equiv['definition'],
                    model_type=esim_equiv.get('type', ''),
                    source_description=(
                        f"Equivalent substitute: {value} → {esim_equiv['name']} "
                        f"(from eSim {esim_equiv['category']} library)"
                    ),
                    file_path=esim_equiv['file_path'],
                    equivalents=equivalents,
                    is_model=True,
                )
                self._cache[cache_key] = result
                return result
            
            esim_equiv_subckt = self.scanner.find_subcircuit(equiv)
            if esim_equiv_subckt:
                deps = self.scanner.get_all_dependencies(esim_equiv_subckt)
                result = self._make_result(
                    status=self.STATUS_EQUIVALENT,
                    model_name=esim_equiv_subckt['name'],
                    model_definition=esim_equiv_subckt['definition'],
                    source_description=(
                        f"Equivalent substitute: {value} → {esim_equiv_subckt['name']} "
                        f"(from eSim SubcircuitLibrary)"
                    ),
                    file_path=esim_equiv_subckt['file_path'],
                    dependencies=deps,
                    equivalents=equivalents,
                    is_model=False,
                )
                self._cache[cache_key] = result
                return result
        
        # STEP 5: Generate from textbook parameters (last resort)
        gen_name, gen_def, gen_type = TextbookModelGenerator.generate_model(value)
        if gen_name:
            result = self._make_result(
                status=self.STATUS_GENERATED,
                model_name=gen_name,
                model_definition=gen_def,
                model_type=gen_type,
                source_description=f"Generated from textbook parameters (approximate, for educational use)",
                equivalents=equivalents,
                is_model=True,
            )
            self._cache[cache_key] = result
            return result
        
        # STEP 6: Nothing found anywhere
        result = self._make_result(
            status=self.STATUS_NOT_FOUND,
            source_description=(
                f"No model found for {value}. "
                f"Suggestions:\n"
                f"  1. Place a .lib file in ~/.esim-bridge/models/\n"
                f"  2. Use eSim Model Editor to create one\n"
                f"  3. Check if eSim has a compatible equivalent"
            ),
            equivalents=equivalents,
        )
        self._cache[cache_key] = result
        return result
    
    def match_all_components(self, components):
        """
        Match models for all components in a schematic.
        
        Args:
            components: dict from SPICEConverter.parse_full_netlist()
                       {ref: {value, description, lib_name, ...}}
        
        Returns:
            dict: {ref: MatchResult}
        """
        results = {}
        
        for ref, comp_data in components.items():
            value = comp_data.get('value', '?')
            description = comp_data.get('description', '')
            lib_name = comp_data.get('lib_name', '')
            
            results[ref] = self.match_component(ref, value, description, lib_name)
        
        return results
    
    def get_coverage_summary(self, match_results):
        """
        Generate a coverage summary from match results.
        
        Returns dict with:
            total, found, missing, passive, generated, equivalent counts
            and lists of component refs in each category
        """
        summary = {
            'total': len(match_results),
            'found': 0,
            'missing': 0,
            'passive': 0,
            'source': 0,
            'generated': 0,
            'equivalent': 0,
            'found_refs': [],
            'missing_refs': [],
            'passive_refs': [],
            'source_refs': [],
            'generated_refs': [],
            'equivalent_refs': [],
        }
        
        for ref, result in match_results.items():
            status = result['status']
            
            if status in (self.STATUS_FOUND_ESIM_DEVICE,
                         self.STATUS_FOUND_ESIM_SUBCKT,
                         self.STATUS_FOUND_EXTERNAL,
                         self.STATUS_FOUND_BUILTIN):
                summary['found'] += 1
                summary['found_refs'].append(ref)
            elif status == self.STATUS_NOT_FOUND:
                summary['missing'] += 1
                summary['missing_refs'].append(ref)
            elif status == self.STATUS_PASSIVE:
                summary['passive'] += 1
                summary['passive_refs'].append(ref)
            elif status == self.STATUS_SOURCE:
                summary['source'] += 1
                summary['source_refs'].append(ref)
            elif status == self.STATUS_GENERATED:
                summary['generated'] += 1
                summary['generated_refs'].append(ref)
            elif status == self.STATUS_EQUIVALENT:
                summary['equivalent'] += 1
                summary['equivalent_refs'].append(ref)
        
        return summary
    
    @staticmethod
    def _make_result(status, model_name=None, model_definition=None,
                     model_type=None, source_description='',
                     file_path=None, dependencies=None,
                     equivalents=None, is_model=True):
        """Create a standardized match result dict."""
        return {
            'status': status,
            'model_name': model_name,
            'model_definition': model_definition,
            'model_type': model_type,
            'source_description': source_description,
            'file_path': file_path,
            'dependencies': dependencies or [],
            'equivalents': equivalents or [],
            'is_model': is_model,
        }


# ══════════════════════════════════════════════════════════════════════
# CLASS 3: ModelStatusReport (wxPython Dialog)
# Shows model coverage report with found/missing/suggested components
# ══════════════════════════════════════════════════════════════════════

class ModelStatusReport(wx.Dialog):
    """
    wxPython dialog that shows the SPICE Model Status Report.
    
    Displays a table:
        Reference | Value | Status | Source | Action
        R1        | 10k   |   OK   | Passive - no model needed | -
        Q1        | BC547 |   OK   | eSim Transistor library   | -
        U1        | LM741 |   OK   | eSim SubcircuitLibrary    | -
        U2        | TL071 |  EQUIV | Equivalent: TL071 (eSim)  | Use
        D3        | 1N4148| TEXTBK | Generated from textbook   | Use
        U3        | XYZ123| MISSING| No model found             | Manual
    
    Provides buttons:
        [Auto-Fix All] - Apply all available matches
        [Export Report] - Save report to text file
        [Continue] - Proceed with simulation
        [Cancel] - Abort
    """
    
    # Status display colors and labels
    STATUS_DISPLAY = {
        ModelMatcher.STATUS_FOUND_ESIM_DEVICE: ('FOUND', wx.Colour(0, 128, 0)),
        ModelMatcher.STATUS_FOUND_ESIM_SUBCKT: ('FOUND', wx.Colour(0, 128, 0)),
        ModelMatcher.STATUS_FOUND_EXTERNAL:    ('FOUND', wx.Colour(0, 128, 0)),
        ModelMatcher.STATUS_FOUND_BUILTIN:     ('FOUND', wx.Colour(0, 128, 0)),
        ModelMatcher.STATUS_GENERATED:         ('TEXTBK', wx.Colour(180, 120, 0)),
        ModelMatcher.STATUS_EQUIVALENT:        ('EQUIV', wx.Colour(0, 100, 180)),
        ModelMatcher.STATUS_NOT_FOUND:         ('MISSING', wx.Colour(200, 0, 0)),
        ModelMatcher.STATUS_PASSIVE:           ('OK', wx.Colour(100, 100, 100)),
        ModelMatcher.STATUS_SOURCE:            ('OK', wx.Colour(100, 100, 100)),
    }
    
    def __init__(self, parent, components, match_results, coverage_summary,
                 scanner_stats=None):
        """
        Args:
            parent: wx parent window
            components: {ref: {value, description, ...}}
            match_results: {ref: MatchResult} from ModelMatcher
            coverage_summary: dict from ModelMatcher.get_coverage_summary()
            scanner_stats: dict from ESimLibraryScanner.get_stats()
        """
        super().__init__(
            parent,
            title="eSim-SPICE - SPICE Model Status Report",
            size=(900, 620),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        )
        
        self.components = components
        self.match_results = match_results
        self.coverage_summary = coverage_summary
        self.scanner_stats = scanner_stats or {}
        
        # User's decision: True = proceed, False = cancel
        self.user_approved = False
        
        self._build_ui()
        self.Centre()
    
    def _build_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # ── Title ──
        title = wx.StaticText(self, label="eSim-SPICE - SPICE Model Auto-Linker")
        title_font = wx.Font(13, wx.FONTFAMILY_DEFAULT,
                            wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        title.SetFont(title_font)
        main_sizer.Add(title, 0, wx.ALL, 10)
        
        # ── Coverage summary bar ──
        cs = self.coverage_summary
        total_active = cs['total'] - cs['passive'] - cs['source']
        found_count = cs['found'] + cs['equivalent'] + cs['generated']
        
        if total_active > 0:
            coverage_pct = int((found_count / total_active) * 100)
        else:
            coverage_pct = 100
        
        summary_text = (
            f"Model Coverage: {found_count}/{total_active} active components resolved "
            f"({coverage_pct}%)"
        )
        if cs['missing'] > 0:
            summary_text += f"  |  {cs['missing']} MISSING"
        if cs['equivalent'] > 0:
            summary_text += f"  |  {cs['equivalent']} using equivalents"
        if cs['generated'] > 0:
            summary_text += f"  |  {cs['generated']} from textbook"
        
        summary_label = wx.StaticText(self, label=summary_text)
        if cs['missing'] > 0:
            summary_label.SetForegroundColour(wx.Colour(200, 100, 0))
        else:
            summary_label.SetForegroundColour(wx.Colour(0, 128, 0))
        main_sizer.Add(summary_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        
        # ── Scanner info ──
        if self.scanner_stats:
            scanner_text = (
                f"eSim Library: {self.scanner_stats.get('device_model_count', 0)} device models, "
                f"{self.scanner_stats.get('subcircuit_count', 0)} subcircuits indexed"
            )
            scanner_label = wx.StaticText(self, label=scanner_text)
            scanner_label.SetForegroundColour(wx.Colour(80, 80, 80))
            scanner_font = wx.Font(8, wx.FONTFAMILY_DEFAULT,
                                  wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
            scanner_label.SetFont(scanner_font)
            main_sizer.Add(scanner_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        
        main_sizer.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        
        # ── Component table ──
        self.list_ctrl = wx.ListCtrl(
            self,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN | wx.HSCROLL
        )
        
        # Columns
        self.list_ctrl.InsertColumn(0, "Ref", width=60)
        self.list_ctrl.InsertColumn(1, "Value", width=100)
        self.list_ctrl.InsertColumn(2, "Status", width=70)
        self.list_ctrl.InsertColumn(3, "Source / Action", width=900)
        
        # Populate rows
        row = 0
        
        # Sort: missing first, then equivalents, then generated, then found, then passive
        sort_order = {
            ModelMatcher.STATUS_NOT_FOUND: 0,
            ModelMatcher.STATUS_EQUIVALENT: 1,
            ModelMatcher.STATUS_GENERATED: 2,
            ModelMatcher.STATUS_FOUND_ESIM_DEVICE: 3,
            ModelMatcher.STATUS_FOUND_ESIM_SUBCKT: 3,
            ModelMatcher.STATUS_FOUND_EXTERNAL: 3,
            ModelMatcher.STATUS_FOUND_BUILTIN: 3,
            ModelMatcher.STATUS_PASSIVE: 4,
            ModelMatcher.STATUS_SOURCE: 4,
        }
        
        sorted_refs = sorted(
            self.match_results.keys(),
            key=lambda r: (
                sort_order.get(self.match_results[r]['status'], 5),
                r
            )
        )
        
        for ref in sorted_refs:
            result = self.match_results[ref]
            comp_data = self.components.get(ref, {})
            value = comp_data.get('value', '?')
            
            status = result['status']
            display_label, display_color = self.STATUS_DISPLAY.get(
                status, ('???', wx.Colour(0, 0, 0)))
            
            source_desc = result['source_description']
            
            # Insert row
            idx = self.list_ctrl.InsertItem(row, ref)
            self.list_ctrl.SetItem(idx, 1, value)
            self.list_ctrl.SetItem(idx, 2, display_label)
            self.list_ctrl.SetItem(idx, 3, source_desc[:])
            
            # Color the status column text
            item = self.list_ctrl.GetItem(idx, 2)
            item.SetTextColour(display_color)
            self.list_ctrl.SetItem(item)
            
            # Highlight missing rows
            if status == ModelMatcher.STATUS_NOT_FOUND:
                self.list_ctrl.SetItemBackgroundColour(idx, wx.Colour(255, 235, 235))
            elif status == ModelMatcher.STATUS_EQUIVALENT:
                self.list_ctrl.SetItemBackgroundColour(idx, wx.Colour(235, 245, 255))
            elif status == ModelMatcher.STATUS_GENERATED:
                self.list_ctrl.SetItemBackgroundColour(idx, wx.Colour(255, 250, 230))
            
            row += 1
        
        main_sizer.Add(self.list_ctrl, 1, wx.ALL | wx.EXPAND, 10)
        
        # ── Legend ──
        legend_text = (
            "FOUND = Model in eSim library  |  "
            "EQUIV = Using compatible equivalent  |  "
            "TEXTBK = Generated from textbook parameters  |  "
            "MISSING = No model found"
        )
        legend = wx.StaticText(self, label=legend_text)
        legend.SetForegroundColour(wx.Colour(100, 100, 100))
        legend_font = wx.Font(8, wx.FONTFAMILY_DEFAULT,
                             wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        legend.SetFont(legend_font)
        main_sizer.Add(legend, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        
        # ── Buttons ──
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Export report button
        export_btn = wx.Button(self, wx.ID_ANY, "Export Report")
        export_btn.Bind(wx.EVT_BUTTON, self._on_export)
        btn_sizer.Add(export_btn, 0, wx.RIGHT, 5)
        
        btn_sizer.AddStretchSpacer()
        
        # Continue / Cancel
        if cs['missing'] > 0:
            continue_btn = wx.Button(self, wx.ID_OK,
                f"Continue Anyway ({cs['missing']} missing)")
            continue_btn.SetForegroundColour(wx.Colour(200, 100, 0))
        else:
            continue_btn = wx.Button(self, wx.ID_OK, "Continue - All Models Resolved")
            continue_btn.SetForegroundColour(wx.Colour(0, 128, 0))
        
        continue_btn.SetDefault()
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Cancel")
        
        btn_sizer.Add(continue_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(cancel_btn, 0)
        
        main_sizer.Add(btn_sizer, 0, wx.ALL | wx.EXPAND, 10)
        
        self.SetSizer(main_sizer)
    
    def _on_export(self, event):
        """Export the model status report to a text file."""
        dialog = wx.FileDialog(
            self,
            "Save Model Status Report",
            defaultFile="esim_spice_model_report.txt",
            wildcard="Text files (*.txt)|*.txt",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
        )
        
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        
        filepath = dialog.GetPath()
        dialog.Destroy()
        
        try:
            report = self._generate_text_report()
            with open(filepath, 'w') as f:
                f.write(report)
            wx.MessageBox(
                f"Report saved to:\n{filepath}",
                "Export Successful", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(
                f"Could not save report:\n{e}",
                "Export Failed", wx.OK | wx.ICON_ERROR)
    
    def _generate_text_report(self):
        """Generate a plain-text model status report."""
        lines = []
        lines.append("=" * 70)
        lines.append("eSim-SPICE - SPICE Model Status Report")
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 70)
        lines.append("")
        
        cs = self.coverage_summary
        total_active = cs['total'] - cs['passive'] - cs['source']
        found_count = cs['found'] + cs['equivalent'] + cs['generated']
        
        lines.append(f"Total components:     {cs['total']}")
        lines.append(f"Passive (no model):   {cs['passive']}")
        lines.append(f"Sources (no model):   {cs['source']}")
        lines.append(f"Active (need model):  {total_active}")
        lines.append(f"  Found in eSim:      {cs['found']}")
        lines.append(f"  Using equivalent:   {cs['equivalent']}")
        lines.append(f"  From textbook:      {cs['generated']}")
        lines.append(f"  MISSING:            {cs['missing']}")
        lines.append("")
        lines.append("-" * 70)
        lines.append(f"{'Ref':<8} {'Value':<15} {'Status':<10} {'Source'}")
        lines.append("-" * 70)
        
        for ref, result in sorted(self.match_results.items()):
            comp_data = self.components.get(ref, {})
            value = comp_data.get('value', '?')
            
            status_label = self.STATUS_DISPLAY.get(
                result['status'], ('???', None))[0]
            
            source = result['source_description'][:]
            lines.append(f"{ref:<8} {value:<15} {status_label:<10} {source}")
        
        lines.append("-" * 70)
        lines.append("")
        lines.append("Legend:")
        lines.append("  FOUND  = Model available in eSim's open-source library")
        lines.append("  EQUIV  = Using a known compatible equivalent device")
        lines.append("  TEXTBK = Generated from textbook parameters (approximate)")
        lines.append("  MISSING = No model found - manual intervention needed")
        lines.append("")
        lines.append("Report generated by eSim-SPICE v1.0.0")
        lines.append("FOSSEE Semester Long Internship, IIT Bombay")
        
        return '\n'.join(lines)


# ══════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR: SPICEAutoLinker
# Ties everything together - called from eSim-BRIDGE's SPICEConverter
# ══════════════════════════════════════════════════════════════════════

class SPICEAutoLinker:
    """
    Main entry point for eSim-SPICE functionality.
    
    Usage from eSim-BRIDGE:
        linker = SPICEAutoLinker()
        
        # Before simulation: check model coverage
        components = converter.parse_full_netlist(netlist_path)
        results = linker.check_models(components)
        
        # Show report dialog (optional)
        linker.show_report(parent_window, components, results)
        
        # Get models to inject into SPICE file
        models, subcircuits = linker.get_injection_data(results)
    """
    
    def __init__(self, esim_home=None, external_model_dir=None):
        """
        Initialize eSim-SPICE with all search engines.
        
        Args:
            esim_home: eSim installation path (auto-detected if None)
            external_model_dir: User model folder (default ~/.esim-bridge/models)
        """
        # Initialize the eSim library scanner
        self.scanner = ESimLibraryScanner(esim_home=esim_home)
        
        # Initialize external loader (from eSim-BRIDGE)
        try:
            from esim_bridge import ExternalModelLoader
            self.external_loader = ExternalModelLoader(
                model_dir=external_model_dir)
        except ImportError:
            # Standalone mode - create a minimal external loader
            self.external_loader = None
            logger.info(
                "eSim-SPICE: Running standalone (eSim-BRIDGE ExternalModelLoader "
                "not available)")
        
        # Initialize the matcher
        self.matcher = ModelMatcher(
            esim_scanner=self.scanner,
            external_loader=self.external_loader
        )
        
        logger.info(
            f"eSim-SPICE: Initialized - "
            f"{self.scanner.get_stats()['device_model_count']} device models, "
            f"{self.scanner.get_stats()['subcircuit_count']} subcircuits indexed"
        )
    
    def check_models(self, components):
        """
        Check model availability for all components.
        
        Args:
            components: dict from SPICEConverter.parse_full_netlist()
                       {ref: {value, description, lib_name, pins, ...}}
        
        Returns:
            {ref: MatchResult} - match results for every component
        """
        return self.matcher.match_all_components(components)
    
    def show_report(self, parent, components, match_results):
        """
        Show the Model Status Report dialog.
        
        Args:
            parent: wx parent window (can be None)
            components: {ref: {value, description, ...}}
            match_results: {ref: MatchResult} from check_models()
        
        Returns:
            True if user wants to proceed, False if cancelled
        """
        if wx is None:
            logger.warning("eSim-SPICE: wx not available, cannot show report dialog")
            return True
        
        coverage = self.matcher.get_coverage_summary(match_results)
        scanner_stats = self.scanner.get_stats()
        
        dialog = ModelStatusReport(
            parent, components, match_results, coverage, scanner_stats)
        
        result = dialog.ShowModal()
        dialog.Destroy()
        
        return result == wx.ID_OK
    
    def get_injection_data(self, match_results):
        """
        Extract all models and subcircuits that need to be injected
        into the SPICE file.
        
        Args:
            match_results: {ref: MatchResult} from check_models()
        
        Returns:
            (models_dict, subcircuits_dict)
            models_dict: {model_name: model_definition}
            subcircuits_dict: {subckt_name: subckt_definition}
        """
        models = {}
        subcircuits = {}
        
        for ref, result in match_results.items():
            if result['model_name'] is None or result['model_definition'] is None:
                continue
            
            if result['status'] in (
                ModelMatcher.STATUS_PASSIVE,
                ModelMatcher.STATUS_SOURCE,
                ModelMatcher.STATUS_NOT_FOUND
            ):
                continue
            
            name = result['model_name']
            definition = result['model_definition']
            
            if result['is_model']:
                models[name] = definition
            else:
                subcircuits[name] = definition
                
                # Also inject dependency models for subcircuits
                for dep in result.get('dependencies', []):
                    dep_name = dep.get('name')
                    dep_def = dep.get('definition')
                    if dep_name and dep_def:
                        models[dep_name] = dep_def
        
        return models, subcircuits
    
    def get_model_for_component(self, ref, value, description='', lib_name=''):
        """
        Quick lookup for a single component.
        Used by SPICEConverter during line-by-line conversion.
        
        Returns:
            MatchResult dict (same as ModelMatcher.match_component)
        """
        return self.matcher.match_component(ref, value, description, lib_name)
    
    def get_scanner_summary(self):
        """Get a human-readable summary of the library scanner."""
        return self.scanner.get_summary_text()
    
    def get_stats(self):
        """Get combined statistics."""
        scanner_stats = self.scanner.get_stats()
        return {
            'esim_home': scanner_stats['esim_home'],
            'esim_found': scanner_stats['esim_found'],
            'device_models': scanner_stats['device_model_count'],
            'subcircuits': scanner_stats['subcircuit_count'],
            'files_scanned': scanner_stats['total_files_scanned'],
            'categories': scanner_stats['categories'],
            'external_available': self.external_loader is not None,
        }


# ══════════════════════════════════════════════════════════════════════
# INTEGRATION HELPER: How to use eSim-SPICE from eSim-BRIDGE
# ══════════════════════════════════════════════════════════════════════

"""
INTEGRATION GUIDE - Adding eSim-SPICE to eSim-BRIDGE's esim_bridge.py
================================================================

1. Import at the top of esim_bridge.py:
   
   from esim_spice_linker import SPICEAutoLinker

2. In ESimBridgePlugin.Run(), AFTER parsing the netlist and BEFORE conversion:
   
   # ── NEW: eSim-SPICE Model Check ──
   linker = SPICEAutoLinker()
   components_raw, nets_raw = converter.parse_full_netlist(netlist_xml_path)
   match_results = linker.check_models(components_raw)
   
   # Show model status report to user
   if not linker.show_report(None, components_raw, match_results):
       progress.Destroy()
       return  # User cancelled
   
   # Get models to inject
   esim_models, esim_subcircuits = linker.get_injection_data(match_results)
   
   # Merge into converter's model tracking
   converter.required_models.update(esim_models)
   converter.required_subcircuits.update(esim_subcircuits)

3. In SPICEConverter.component_to_spice(), for diodes/BJTs/MOSFETs/ICs,
   you can optionally use eSim-SPICE's single-component lookup BEFORE
   falling back to the built-in library:
   
   # At the start of SPICEConverter.__init__():
   try:
       from esim_spice_linker import SPICEAutoLinker
       self.auto_linker = SPICEAutoLinker()
   except ImportError:
       self.auto_linker = None
   
   # Then in the diode section of component_to_spice():
   if self.auto_linker:
       result = self.auto_linker.get_model_for_component(ref, value, description)
       if result['model_name'] and result['status'] != 'not_found':
           self.required_models[result['model_name']] = result['model_definition']
           return f"{ref} {anode} {cathode} {result['model_name']}"

That's it! eSim-SPICE works as a transparent layer that enhances eSim-BRIDGE
without breaking any existing functionality.
"""


# ══════════════════════════════════════════════════════════════════════
# STANDALONE TEST - Run this file directly to test the scanner
# ══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 60)
    print("eSim-SPICE v1.0.0 - eSim SPICE Model Auto-Linker")
    print("Standalone Test Mode")
    print("=" * 60)
    print()
    
    # Initialize
    linker = SPICEAutoLinker()
    stats = linker.get_stats()
    
    print(f"eSim home: {stats['esim_home']}")
    print(f"eSim found: {stats['esim_found']}")
    print(f"Device models indexed: {stats['device_models']}")
    print(f"Subcircuits indexed: {stats['subcircuits']}")
    print(f"Files scanned: {stats['files_scanned']}")
    print(f"Categories: {stats['categories']}")
    print()
    
    # Test lookups
    test_components = {
        'R1': {'value': '10k', 'description': 'Resistor', 'lib_name': ''},
        'C1': {'value': '100n', 'description': 'Capacitor', 'lib_name': ''},
        'V1': {'value': '5', 'description': 'DC source', 'lib_name': ''},
        'D1': {'value': '1N4148', 'description': 'Signal diode', 'lib_name': ''},
        'D2': {'value': 'LED', 'description': 'Light Emitting Diode', 'lib_name': ''},
        'Q1': {'value': 'BC547', 'description': 'NPN transistor', 'lib_name': ''},
        'Q2': {'value': '2N2222', 'description': 'NPN transistor', 'lib_name': ''},
        'Q3': {'value': '2N3906', 'description': 'PNP transistor', 'lib_name': ''},
        'M1': {'value': '2N7000', 'description': 'N-channel MOSFET', 'lib_name': ''},
        'U1': {'value': 'LM741', 'description': 'Op-amp', 'lib_name': ''},
        'U2': {'value': 'LM555', 'description': '555 Timer', 'lib_name': ''},
        'U3': {'value': 'LM358', 'description': 'Dual op-amp', 'lib_name': ''},
        'U4': {'value': 'LM317', 'description': 'Voltage regulator', 'lib_name': ''},
        'U5': {'value': 'CD4011', 'description': 'CMOS NAND gate', 'lib_name': ''},
        'U6': {'value': '74HC86', 'description': 'XOR gate IC', 'lib_name': ''},
        'U7': {'value': 'UNKNOWN_IC_XYZ', 'description': 'Test unknown', 'lib_name': ''},
    }
    
    print("-" * 60)
    print(f"{'Ref':<6} {'Value':<18} {'Status':<10} {'Source'}")
    print("-" * 60)
    
    results = linker.check_models(test_components)
    
    for ref in sorted(results.keys()):
        result = results[ref]
        comp = test_components[ref]
        
        status_labels = {
            'esim_device': 'FOUND',
            'esim_subcircuit': 'FOUND',
            'external': 'EXTERN',
            'builtin': 'BUILT-IN',
            'generated': 'TEXTBK',
            'equivalent': 'EQUIV',
            'not_found': 'MISSING',
            'passive': 'PASSIVE',
            'source': 'SOURCE',
        }
        
        label = status_labels.get(result['status'], '???')
        source = result['source_description'][:40]
        
        print(f"{ref:<6} {comp['value']:<18} {label:<10} {source}")
    
    print("-" * 60)
    
    # Coverage summary
    coverage = linker.matcher.get_coverage_summary(results)
    total_active = coverage['total'] - coverage['passive'] - coverage['source']
    found = coverage['found'] + coverage['equivalent'] + coverage['generated']
    
    print()
    print(f"Total: {coverage['total']} | Active: {total_active} | "
          f"Found: {found} | Missing: {coverage['missing']}")
    print()
    print("eSim-SPICE standalone test complete.")


