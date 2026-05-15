import os
import re
import json
import subprocess
import shutil
import tempfile
import platform
from datetime import datetime


class SimulationEngine:

    NON_SIMULATABLE_PATTERNS = [
        (r'\bPIC[_\-]?\d+[A-Z_0-9]*\b', 'PIC microcontroller'),
        (r'\bATMEGA[_\-]?\d+[A-Z_0-9]*\b', 'AVR ATmega microcontroller'),
        (r'\bATTINY[_\-]?\d+[A-Z_0-9]*\b', 'AVR ATtiny microcontroller'),
        (r'\bSTM32[A-Z0-9_\-]*\b', 'STM32 microcontroller'),
        (r'\bMSP430[A-Z0-9_\-]*\b', 'MSP430 microcontroller'),
        (r'\bESP32[A-Z0-9_\-]*\b', 'ESP32 module'),
        (r'\bESP8266[A-Z0-9_\-]*\b', 'ESP8266 module'),
        (r'\bARDUINO[A-Z0-9_\-]*\b', 'Arduino board'),
        (r'\bRP2040\b', 'RP2040 microcontroller'),
        (r'\bNRF\d+[A-Z0-9]*\b', 'Nordic nRF microcontroller'),
        (r'\bICSP\b', 'ICSP programmer header'),
        (r'\bPICKIT\b', 'PICkit programmer interface'),
        (r'\bJTAG\b', 'JTAG debug interface'),
        (r'\bSWD\b', 'SWD debug interface'),
        (r'\bAVR[_\-]?ISP\b', 'AVR ISP programmer'),
        (r'\b74[A-Z]{1,4}\d+[A-Z]?\b', '74-series digital logic IC'),
        (r'\b4[0-9]{3}[A-Z]?\b', '4000-series digital logic IC'),
        (r'\b24C[A-Z0-9X]+\b', 'EEPROM (24Cxx series)'),
        (r'\b24[A-Z]{1,3}\d*\b', 'EEPROM / serial memory'),
        (r'\b25[A-Z]{1,3}\d*\b', 'SPI flash / EEPROM'),
        (r'\b93C\d+[A-Z]?\b', '93Cxx EEPROM'),
        (r'\bCONN[_\-]?\d*\b', 'Connector / pin header'),
        (r'\bSUPP\d+\b', 'IC socket / pin header'),
        (r'\bSCREW[_\-]?TERM[A-Z0-9_]*\b', 'Screw terminal'),
        (r'\bHEADER[_\-]?\d+[A-Z0-9_]*\b', 'Pin header'),
        (r'\bDB\d+[A-Z]?\b', 'D-sub connector'),
        (r'\bUSB[_\-]?[A-Z0-9]*\b', 'USB connector'),
        (r'\bRJ\d+\b', 'RJ connector'),
        (r'\bLT\d{3,4}[A-Z]*\b', 'Linear Technology IC (no generic SPICE model)'),
        (r'\bMAX\d{3,4}[A-Z]*\b', 'Maxim IC (often no generic SPICE model)'),
        (r'\bFTDI[A-Z0-9_\-]*\b', 'FTDI USB-UART chip'),
        (r'\bCH340[A-Z]?\b', 'CH340 USB-UART chip'),
    ]

    NON_SIMULATABLE_KEYWORDS_IN_VALUE = [
        ('pic16', 'PIC16 microcontroller'),
        ('pic18', 'PIC18 microcontroller'),
        ('pic24', 'PIC24 microcontroller'),
        ('pic32', 'PIC32 microcontroller'),
        ('atmega', 'AVR ATmega microcontroller'),
        ('attiny', 'AVR ATtiny microcontroller'),
        ('stm32', 'STM32 microcontroller'),
        ('esp32', 'ESP32 module'),
        ('esp8266', 'ESP8266 module'),
        ('msp430', 'MSP430 microcontroller'),
        ('rp2040', 'RP2040 microcontroller'),
        ('arduino', 'Arduino board'),
        ('icsp', 'ICSP programmer header'),
        ('pickit', 'PICkit programmer interface'),
        ('eeprom', 'EEPROM memory'),
        ('crystal', 'crystal oscillator (limited SPICE support)'),
        ('socket', 'IC socket / pin header'),
    ]

    def __init__(self, project_folder, diary_folder):
        self.project_folder = project_folder
        self.diary_folder = diary_folder
        self._warning_marker = os.path.join(self.diary_folder, '_sim_warning_shown.json')

    def find_cir_file(self):
        search_dirs = [
            self.project_folder,
            os.path.dirname(self.project_folder),
            os.path.join(self.project_folder, '..'),
        ]
        for d in search_dirs:
            try:
                for f in os.listdir(d):
                    if f.endswith('.cir'):
                        return os.path.join(d, f)
            except OSError:
                continue
        return None

    def detect_non_simulatable_components(self, components):
        if not components:
            return []
        findings = []
        seen_refs = set()
        for ref, data in components.items():
            if ref in seen_refs:
                continue
            value = data.get('value', '') if isinstance(data, dict) else str(data)
            footprint = data.get('footprint', '') if isinstance(data, dict) else ''
            haystack_upper = (ref + ' ' + value + ' ' + footprint).upper()
            haystack_lower = haystack_upper.lower()
            matched = False
            for pattern, label in self.NON_SIMULATABLE_PATTERNS:
                if re.search(pattern, haystack_upper):
                    findings.append({'ref': ref, 'value': value, 'reason': label})
                    seen_refs.add(ref)
                    matched = True
                    break
            if matched:
                continue
            for keyword, label in self.NON_SIMULATABLE_KEYWORDS_IN_VALUE:
                if keyword in haystack_lower:
                    findings.append({'ref': ref, 'value': value, 'reason': label})
                    seen_refs.add(ref)
                    break
        return findings

    def detect_non_simulatable_in_cir(self, cir_path):
        if not cir_path or not os.path.exists(cir_path):
            return []
        try:
            with open(cir_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except Exception:
            return []
        defined_subckts = set()
        for match in re.finditer(r'^\.subckt\s+(\S+)', content, re.MULTILINE | re.IGNORECASE):
            defined_subckts.add(match.group(1).lower())
        has_include = bool(re.search(
            r'^\.(include|lib)\s+', content, re.MULTILINE | re.IGNORECASE
        ))
        findings = []
        for line in content.split('\n'):
            stripped = line.strip()
            if not stripped or stripped.startswith('*') or stripped.startswith('.'):
                continue
            tokens = stripped.split()
            if not tokens:
                continue
            ref = tokens[0]
            first_char = ref[0].upper()
            line_upper = stripped.upper()
            line_lower = stripped.lower()
            for pattern, label in self.NON_SIMULATABLE_PATTERNS:
                if re.search(pattern, line_upper):
                    findings.append({'ref': ref, 'value': '', 'reason': label})
                    break
            else:
                for keyword, label in self.NON_SIMULATABLE_KEYWORDS_IN_VALUE:
                    if keyword in line_lower:
                        findings.append({'ref': ref, 'value': '', 'reason': label})
                        break
                else:
                    if first_char == 'X' and len(tokens) >= 2:
                        model_name = tokens[-1].lower()
                        if model_name not in defined_subckts and not has_include:
                            findings.append({
                                'ref': ref,
                                'value': tokens[-1],
                                'reason': "subcircuit '" + tokens[-1] + "' has no .subckt or .include"
                            })
        unique = []
        seen = set()
        for f in findings:
            key = f['ref']
            if key not in seen:
                seen.add(key)
                unique.append(f)
        return unique

    def get_simulatability_status(self, cir_path, components=None):
        result = {
            'simulatable': True,
            'has_cir': False,
            'findings': [],
            'message': '',
            'short_message': '',
        }
        if cir_path and os.path.exists(cir_path):
            result['has_cir'] = True
            cir_findings = self.detect_non_simulatable_in_cir(cir_path)
            result['findings'].extend(cir_findings)
        if components:
            comp_findings = self.detect_non_simulatable_components(components)
            existing_refs = {f['ref'] for f in result['findings']}
            for f in comp_findings:
                if f['ref'] not in existing_refs:
                    result['findings'].append(f)
        if result['findings']:
            result['simulatable'] = False
            lines = []
            for f in result['findings'][:8]:
                if f['value']:
                    lines.append("  - " + f['ref'] + " (" + f['value'] + "): " + f['reason'])
                else:
                    lines.append("  - " + f['ref'] + ": " + f['reason'])
            if len(result['findings']) > 8:
                lines.append("  ... and " + str(len(result['findings']) - 8) + " more")
            result['message'] = (
                "This circuit cannot be simulated by eSim/ngspice.\n\n"
                "ngspice is a SPICE analog simulator -- it works with passives "
                "(R, L, C), diodes, transistors, op-amps, and voltage/current sources. "
                "It cannot simulate:\n\n"
                + '\n'.join(lines) + "\n\n"
                "This is not an error in your design. The circuit is simply outside "
                "what SPICE-based simulation can model.\n\n"
                "What you can still do with Design Diary on this circuit:\n"
                "  - Track schematic and PCB changes over time\n"
                "  - Use snapshots, rollback, and component history\n"
                "  - Export the HTML report\n"
                "  - Compare design revisions"
            )
            refs = ', '.join(f['ref'] for f in result['findings'][:3])
            extra = '' if len(result['findings']) <= 3 else ' +' + str(len(result['findings']) - 3) + ' more'
            result['short_message'] = (
                "Not simulatable in ngspice -- contains: " + refs + extra
                + ". All other Design Diary features still work."
            )
        return result

    def _load_warning_state(self):
        if not os.path.exists(self._warning_marker):
            return {}
        try:
            with open(self._warning_marker, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_warning_state(self, state):
        try:
            os.makedirs(self.diary_folder, exist_ok=True)
            with open(self._warning_marker, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass

    def _circuit_fingerprint(self, cir_path, components):
        parts = []
        if cir_path:
            parts.append(os.path.basename(cir_path))
        if components:
            refs = sorted(components.keys())
            parts.append('|'.join(refs))
        return '::'.join(parts) if parts else 'default'

    def should_show_popup_warning(self, cir_path, components=None):
        fingerprint = self._circuit_fingerprint(cir_path, components)
        state = self._load_warning_state()
        return fingerprint not in state

    def mark_warning_shown(self, cir_path, components=None):
        fingerprint = self._circuit_fingerprint(cir_path, components)
        state = self._load_warning_state()
        state[fingerprint] = {
            'shown_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'cir': os.path.basename(cir_path) if cir_path else None,
        }
        self._save_warning_state(state)

    def preflight_check(self, cir_path):
        if not cir_path or not os.path.exists(cir_path):
            return False, (
                "No .cir netlist file found in this project.\n\n"
                "Design Diary needs a SPICE netlist (.cir) to simulate.\n\n"
                "How to create one:\n"
                "  1. Open this project in eSim\n"
                "  2. Use eSim's 'Convert KiCad to Ngspice' option\n"
                "  3. eSim will generate a .cir file in the project folder\n"
                "  4. Then come back to Design Diary and click Simulate again\n\n"
                "Note: Not all circuits are simulatable. Microcontrollers, "
                "programmers, and complex digital ICs cannot be simulated by "
                "ngspice without custom SPICE models."
            )

        try:
            with open(cir_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except Exception as e:
            return False, "Could not read .cir file: " + str(e)

        if not content.strip():
            return False, "The .cir file is empty:\n" + cir_path

        status = self.get_simulatability_status(cir_path, None)
        if not status['simulatable']:
            return False, status['message']

        has_analysis = bool(re.search(
            r'^\.(tran|ac|dc|op)\s+',
            content, re.MULTILINE | re.IGNORECASE
        ))
        if not has_analysis:
            return True, (
                "WARNING: No analysis directive (.tran/.ac/.dc) found in .cir.\n"
                "A default .tran 0.1m 3000m will be added automatically."
            )

        return True, "Pre-flight check passed."

    def find_ngspice(self):
        is_windows = platform.system() == 'Windows'
        if is_windows:
            paths = [
                r'C:\FOSSEE\nghdl-simulator\bin\ngspice.exe',
                r'C:\Program Files\ngspice\bin\ngspice.exe',
                r'C:\FOSSEE\eSim\ngspice\bin\ngspice.exe',
            ]
            for p in paths:
                if os.path.exists(p):
                    return p
            try:
                result = subprocess.run(['where', 'ngspice'], capture_output=True, text=True)
                if result.returncode == 0:
                    return result.stdout.strip().split('\n')[0].strip()
            except Exception:
                pass
        else:
            try:
                result = subprocess.run(['which', 'ngspice'], capture_output=True, text=True)
                if result.returncode == 0:
                    return result.stdout.strip()
            except Exception:
                pass
            wsl_paths = [
                '/mnt/c/FOSSEE/nghdl-simulator/bin/ngspice.exe',
                '/mnt/c/Program Files/ngspice/bin/ngspice.exe',
            ]
            for p in wsl_paths:
                if os.path.exists(p):
                    return p
        return None

    def find_esim(self):
        is_windows = platform.system() == 'Windows'
        if is_windows:
            paths = [
                r'C:\FOSSEE\eSim\eSim.exe',
                r'C:\Program Files\eSim\eSim.exe',
            ]
        else:
            paths = [
                '/mnt/c/FOSSEE/eSim/eSim.exe',
                '/mnt/c/Program Files/eSim/eSim.exe',
            ]
        for p in paths:
            if os.path.exists(p):
                return p
        return None

    def launch_esim(self):
        esim = self.find_esim()
        if not esim:
            return False, (
                "eSim not found. Checked:\n"
                "  C:\\FOSSEE\\eSim\\eSim.exe\n"
                "  C:\\Program Files\\eSim\\eSim.exe"
            )
        try:
            if platform.system() == 'Windows':
                os.startfile(esim)
            else:
                subprocess.Popen([esim], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, "eSim launched."
        except Exception as e:
            return False, "Failed to launch eSim: " + str(e)

    def _kicad_to_spice_value(self, value):
        val = value.strip()
        conversions = {
            r'(\d+(?:\.\d+)?)\s*[kK]$': r'\g<1>k',
            r'(\d+(?:\.\d+)?)\s*[mM]$': r'\g<1>MEG',
            r'(\d+(?:\.\d+)?)\s*[uU][fF]?$': r'\g<1>u',
            r'(\d+(?:\.\d+)?)\s*[nN][fF]?$': r'\g<1>n',
            r'(\d+(?:\.\d+)?)\s*[pP][fF]?$': r'\g<1>p',
        }
        for pattern, replacement in conversions.items():
            if re.match(pattern, val):
                return re.sub(pattern, replacement, val)
        return val

    def sync_cir_values(self, cir_path, components):
        with open(cir_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        original = content
        changes = []
        for ref, data in components.items():
            if ref[0].upper() in ('D', 'U', 'Q', 'X'):
                continue
            value = data.get('value', '') if isinstance(data, dict) else data
            spice_val = self._kicad_to_spice_value(value)
            pattern = re.compile(
                r'^(' + re.escape(ref) + r'\s+\S+\s+\S+\s+)(\S+)',
                re.MULTILINE | re.IGNORECASE
            )
            match = pattern.search(content)
            if match:
                old_val = match.group(2)
                if old_val.lower() != spice_val.lower():
                    content = pattern.sub(match.group(1) + spice_val, content, count=1)
                    changes.append("Synced " + ref + ": " + old_val + " -> " + spice_val)
        if content != original:
            with open(cir_path, 'w', encoding='utf-8') as f:
                f.write(content)
        return changes

    def prepare_cir_for_ngspice(self, cir_path):
        with open(cir_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')

        temp_dir = tempfile.gettempdir()
        sim_cir_path = os.path.join(temp_dir, 'dd_sim_' + timestamp_str + '.cir')
        temp_raw = os.path.join(temp_dir, 'dd_sim_' + timestamp_str + '.raw')
        final_raw = os.path.join(self.diary_folder, 'sim_run_' + timestamp_str + '.raw')

        lines = content.strip().split('\n')
        has_tran = any('.tran' in l.lower() for l in lines)
        has_control = any('.control' in l.lower() for l in lines)

        build_lines = []
        for line in lines:
            if line.strip().lower() == '.end':
                continue
            build_lines.append(line)

        if not has_tran and not has_control:
            build_lines.append('.tran 0.1m 3000m')
            build_lines.append('.control')
            build_lines.append('run')
            build_lines.append('set filetype=ascii')
            build_lines.append('write ' + temp_raw.replace(chr(92), "/") + ' all')
            build_lines.append('quit')
            build_lines.append('.endc')
        elif has_tran and not has_control:
            build_lines.append('.control')
            build_lines.append('run')
            build_lines.append('set filetype=ascii')
            build_lines.append('write ' + temp_raw.replace(chr(92), "/") + ' all')
            build_lines.append('quit')
            build_lines.append('.endc')
        elif has_control:
            new_lines = []
            for line in build_lines:
                if 'write' in line.lower() and '.raw' in line.lower():
                    new_lines.append('write ' + temp_raw.replace(chr(92), "/") + ' all')
                else:
                    new_lines.append(line)
            build_lines = new_lines

            has_write = any('write' in l.lower() and '.raw' in l.lower() for l in build_lines)
            if not has_write:
                final_lines = []
                for line in build_lines:
                    final_lines.append(line)
                    if line.strip().lower() == 'run':
                        final_lines.append('set filetype=ascii')
                        final_lines.append('write ' + temp_raw.replace(chr(92), "/") + ' all')
                build_lines = final_lines

        build_lines.append('.end')

        with open(sim_cir_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(build_lines))

        return sim_cir_path, temp_raw, final_raw

    def _translate_ngspice_errors(self, stdout, stderr, cir_path):
        combined = (stdout + '\n' + stderr).lower()
        if any(s in combined for s in ['unknown subcircuit', 'undefined subcircuit', 'subckt not found', "can't find subckt"]):
            return (
                "ngspice does not have a SPICE model for one or more components "
                "in this circuit.\n\n"
                "This is common when the circuit uses microcontrollers, programmers, "
                "or specialized ICs that ngspice cannot simulate without a custom .lib "
                "or .include file.\n\n"
                "This is not a bug in Design Diary -- it means this particular circuit "
                "is outside what SPICE simulation can model. Try a circuit made of "
                "passives, diodes, transistors, or op-amps."
            )
        if 'no such device' in combined or 'undefined model' in combined:
            return (
                "ngspice could not find a model for one of the components in this "
                "circuit. The .cir file references a model name that has no matching "
                ".model or .include statement.\n\n"
                "If this circuit contains microcontrollers, programmers, or other "
                "digital chips, that is expected -- ngspice cannot simulate them."
            )
        if 'singular matrix' in combined or 'no convergence' in combined:
            return (
                "ngspice ran the circuit but could not find a stable operating point "
                "(singular matrix / no convergence).\n\n"
                "This usually means the circuit topology has a problem -- e.g. a "
                "floating node, a missing ground reference, or a component value that "
                "creates an impossible operating condition. This is a circuit-design "
                "issue, not a Design Diary issue."
            )
        if 'parse error' in combined or 'syntax error' in combined:
            return (
                "ngspice could not parse the .cir file -- there is a syntax issue in "
                "the netlist.\n\n"
                "If this .cir was generated by eSim, try regenerating it. Otherwise, "
                "open the .cir file in a text editor and check for malformed lines."
            )
        return None

    def run_simulation(self, cir_path, components=None):
        if components:
            comp_findings = self.detect_non_simulatable_components(components)
            if comp_findings:
                lines = []
                for f in comp_findings[:8]:
                    if f['value']:
                        lines.append("  - " + f['ref'] + " (" + f['value'] + "): " + f['reason'])
                    else:
                        lines.append("  - " + f['ref'] + ": " + f['reason'])
                if len(comp_findings) > 8:
                    lines.append("  ... and " + str(len(comp_findings) - 8) + " more")
                msg = (
                    "This circuit cannot be simulated by eSim/ngspice.\n\n"
                    "ngspice is a SPICE analog simulator -- it works with passives "
                    "(R, L, C), diodes, transistors, op-amps, and voltage/current sources. "
                    "It cannot simulate the following components found on this board:\n\n"
                    + '\n'.join(lines) + "\n\n"
                    "This is not an error in your design. Boards built around "
                    "microcontrollers, programmers, EEPROMs, or digital logic chips "
                    "cannot be simulated by ngspice without custom SPICE models -- "
                    "and eSim will not generate a .cir netlist for them either.\n\n"
                    "What you can still do with Design Diary on this board:\n"
                    "  - Track schematic and PCB changes over time\n"
                    "  - Use snapshots, rollback, and component history\n"
                    "  - Export the HTML report\n"
                    "  - Compare design revisions"
                )
                log_path = os.path.join(
                    self.diary_folder,
                    'sim_run_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.log'
                )
                try:
                    os.makedirs(self.diary_folder, exist_ok=True)
                    with open(log_path, 'w', encoding='utf-8') as f:
                        f.write("=== CIRCUIT NOT SIMULATABLE (BOARD-LEVEL DETECTION) ===\n\n" + msg)
                except Exception:
                    pass
                return False, msg, None, log_path

        status = self.get_simulatability_status(cir_path, components)
        if not status['simulatable']:
            log_path = os.path.join(
                self.diary_folder,
                'sim_run_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.log'
            )
            try:
                os.makedirs(self.diary_folder, exist_ok=True)
                with open(log_path, 'w', encoding='utf-8') as f:
                    f.write("=== CIRCUIT NOT SIMULATABLE ===\n\n" + status['message'])
            except Exception:
                pass
            return False, status['message'], None, log_path

        ok, msg = self.preflight_check(cir_path)
        if not ok:
            log_path = os.path.join(
                self.diary_folder,
                'sim_run_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.log'
            )
            try:
                os.makedirs(self.diary_folder, exist_ok=True)
                with open(log_path, 'w', encoding='utf-8') as f:
                    f.write("=== PRE-FLIGHT CHECK FAILED ===\n\n" + msg)
            except Exception:
                pass
            return False, msg, None, log_path

        ngspice = self.find_ngspice()
        if not ngspice:
            return False, (
                "ngspice not found.\n\n"
                "Checked these locations:\n"
                "  C:\\FOSSEE\\nghdl-simulator\\bin\\ngspice.exe\n"
                "  C:\\Program Files\\ngspice\\bin\\ngspice.exe\n"
                "  C:\\FOSSEE\\eSim\\ngspice\\bin\\ngspice.exe\n\n"
                "Please install ngspice or check your eSim installation."
            ), None, None

        if components:
            self.sync_cir_values(cir_path, components)

        sim_cir, temp_raw, final_raw = self.prepare_cir_for_ngspice(cir_path)

        try:
            is_windows = platform.system() == 'Windows'
            if is_windows:
                cmd = '"' + ngspice + '" -b "' + sim_cir + '"'
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, shell=True)
            else:
                cmd = [ngspice, '-b', sim_cir]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            stdout = result.stdout
            stderr = result.stderr
            returncode = result.returncode

            log_path = os.path.join(
                self.diary_folder,
                'sim_run_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.log'
            )
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write("=== COMMAND ===\n" + str(cmd) + "\n\n")
                f.write("=== RETURN CODE ===\n" + str(returncode) + "\n\n")
                f.write("=== CIR FILE ===\n")
                try:
                    f.write(open(sim_cir, 'r').read())
                except Exception:
                    pass
                f.write("\n\n=== STDOUT ===\n" + stdout + "\n\n=== STDERR ===\n" + stderr + "\n")

            raw_exists = os.path.exists(temp_raw)
            if raw_exists:
                shutil.copy2(temp_raw, final_raw)
                raw_path = final_raw
            else:
                raw_path = None

            ngspice_errors = []
            combined_output = (stdout + '\n' + stderr).lower()
            error_patterns = [
                r'error[: ]',
                r'fatal',
                r'singular matrix',
                r'no convergence',
                r'unknown subcircuit',
                r'undefined model',
                r'no such device',
                r'mif-error',
                r'parse error',
            ]
            for pattern in error_patterns:
                if re.search(pattern, combined_output):
                    matches = re.findall(r'.*' + pattern + r'.*', combined_output)
                    ngspice_errors.extend(matches[:3])

            real_success = (returncode == 0) and raw_exists and not ngspice_errors

            sim_record = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'type': 'simulation_result',
                'cir_file': sim_cir,
                'raw_file': raw_path,
                'log_file': log_path,
                'success': real_success,
                'returncode': returncode,
                'errors_found': ngspice_errors[:5],
                'changes': [
                    "SIMULATION: " + ('Passed' if real_success else 'Failed') +
                    " -- ran ngspice on " + os.path.basename(cir_path)
                ],
            }
            record_fname = 'RUN_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.json'
            with open(os.path.join(self.diary_folder, record_fname), 'w') as f:
                json.dump(sim_record, f, indent=2)

            if real_success:
                return True, "Simulation completed.\nLog: " + log_path, raw_path, log_path

            friendly = self._translate_ngspice_errors(stdout, stderr, cir_path)
            if friendly:
                return False, friendly, None, log_path

            failure_msg = "Simulation failed.\n\n"
            if ngspice_errors:
                failure_msg += "ngspice reported errors:\n"
                for err in ngspice_errors[:5]:
                    failure_msg += "  " + err.strip() + "\n"
                failure_msg += "\n"
            if not raw_exists:
                failure_msg += "No output .raw file was produced.\n"
            if returncode != 0:
                failure_msg += "ngspice exit code: " + str(returncode) + "\n"
            failure_msg += "\nFull log: " + log_path

            return False, failure_msg, None, log_path

        except subprocess.TimeoutExpired:
            return False, "Simulation timed out (120s).", None, None
        except Exception as e:
            return False, "Simulation error: " + str(e), None, None

    def parse_raw_file(self, raw_path):
        if not raw_path or not os.path.exists(raw_path):
            return None
        try:
            with open(raw_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()

            variables = []
            data_points = {}
            in_variables = False
            in_values = False

            for line in content.split('\n'):
                stripped = line.strip()
                if stripped.startswith('Variables:'):
                    in_variables = True
                    continue
                if stripped.startswith('Values:'):
                    in_variables = False
                    in_values = True
                    continue
                if in_variables and stripped:
                    parts = stripped.split()
                    if len(parts) >= 3:
                        variables.append(parts[1])
                        data_points[parts[1]] = []
                if in_values and stripped:
                    parts = stripped.split()
                    if len(parts) == 2:
                        try:
                            int(parts[0])
                            data_points[variables[0]].append(float(parts[1]))
                        except (ValueError, IndexError):
                            pass
                    elif len(parts) == 1:
                        try:
                            val = float(parts[0])
                            for var in variables:
                                if len(data_points[var]) < len(data_points[variables[0]]):
                                    data_points[var].append(val)
                                    break
                        except ValueError:
                            pass

            return {
                'variables': variables,
                'data': data_points,
                'num_points': len(data_points.get(variables[0], [])) if variables else 0,
            }
        except Exception:
            return None

    def generate_plot_html(self, raw_path):
        parsed = self.parse_raw_file(raw_path)
        if not parsed or not parsed['variables']:
            return None

        time_var = parsed['variables'][0]
        signal_vars = [v for v in parsed['variables'][1:] if len(parsed['data'].get(v, [])) > 0]
        if not signal_vars:
            return None

        time_data = parsed['data'].get(time_var, [])
        colors = ['#c4713b', '#4a7c59', '#456b8a', '#8b3a3a', '#6b5b7b', '#b8860b', '#2d6a4f', '#9c4146']

        datasets_js = "const datasets = {\n"
        datasets_js += '  "time": ' + json.dumps(time_data[:5000]) + ',\n'
        for var in signal_vars[:8]:
            vals = parsed['data'].get(var, [])
            datasets_js += '  "' + var + '": ' + json.dumps(vals[:5000]) + ',\n'
        datasets_js += "};\n"

        checkboxes = ""
        for i, var in enumerate(signal_vars[:8]):
            color = colors[i % len(colors)]
            checked = "checked" if i < 3 else ""
            checkboxes += (
                '<label class="sig-label" style="--sig-color:' + color + '">'
                '<input type="checkbox" ' + checked + ' onchange="redraw()" value="' + var + '"> ' + var + '</label>\n'
            )

        html = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Simulation Results -- KiCad Design Diary</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=IBM+Plex+Sans:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
:root { --bg:#f5f2ed; --card:#faf8f5; --border:#e0dbd3; --text:#2d3436; --muted:#9ba3a9; --accent:#c4713b; }
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'IBM Plex Sans',sans-serif; background:var(--bg); color:var(--text); }
.container { max-width:1000px; margin:0 auto; padding:40px 32px; }
h1 { font-family:'DM Serif Display',serif; font-size:1.8rem; font-weight:400; margin-bottom:8px; }
h1 span { color:var(--accent); }
.meta { font-size:0.82rem; color:var(--muted); margin-bottom:32px; font-family:'JetBrains Mono',monospace; }
.controls { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:24px; }
.sig-label { display:inline-flex; align-items:center; gap:6px; padding:6px 14px; border-radius:6px; font-size:0.82rem; font-weight:500; background:var(--card); border:1px solid var(--border); cursor:pointer; }
.sig-label:hover { border-color:var(--accent); }
.sig-label input { accent-color:var(--sig-color); }
.plot-card { background:var(--card); border-radius:10px; padding:24px; box-shadow:0 1px 3px rgba(0,0,0,0.04); }
canvas { width:100%; height:450px; display:block; }
.info { margin-top:24px; font-size:0.82rem; color:var(--muted); font-family:'JetBrains Mono',monospace; }
</style>
</head>
<body>
<div class="container">
<h1>Simulation <span>Results</span></h1>
<div class="meta">''' + str(parsed['num_points']) + ''' data points -- ''' + str(len(signal_vars)) + ''' signals -- ''' + time_var + '''</div>
<div class="controls">''' + checkboxes + '''</div>
<div class="plot-card"><canvas id="plot"></canvas></div>
<div class="info">Generated by KiCad Design Diary -- ngspice simulation output</div>
</div>
<script>
''' + datasets_js + '''
const colors = ''' + json.dumps(colors) + ''';
const signalNames = ''' + json.dumps(signal_vars[:8]) + ''';
function redraw() {
    const canvas = document.getElementById('plot');
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const W = rect.width, H = rect.height;
    const pad = { top:20, right:20, bottom:45, left:65 };
    const pW = W-pad.left-pad.right, pH = H-pad.top-pad.bottom;
    ctx.clearRect(0, 0, W, H);
    const time = datasets["time"];
    if (!time || !time.length) return;
    const checks = document.querySelectorAll('.sig-label input:checked');
    const active = Array.from(checks).map(c => c.value);
    if (!active.length) return;
    const tMin = time[0], tMax = time[time.length-1];
    let vMin = Infinity, vMax = -Infinity;
    active.forEach(sig => { const d = datasets[sig]||[]; d.forEach(v => { if(v<vMin)vMin=v; if(v>vMax)vMax=v; }); });
    const vPad = (vMax-vMin)*0.1 || 0.5;
    vMin -= vPad; vMax += vPad;
    ctx.strokeStyle = '#e0dbd3'; ctx.lineWidth = 1;
    ctx.font = '11px JetBrains Mono, monospace'; ctx.fillStyle = '#9ba3a9';
    ctx.textAlign = 'right';
    for (let i=0;i<=5;i++) {
        const y = pad.top+pH-(i/5)*pH;
        const val = vMin+(i/5)*(vMax-vMin);
        ctx.beginPath(); ctx.moveTo(pad.left,y); ctx.lineTo(pad.left+pW,y); ctx.stroke();
        ctx.fillText(val.toFixed(2), pad.left-8, y+4);
    }
    ctx.textAlign = 'center';
    for (let i=0;i<=5;i++) {
        const x = pad.left+(i/5)*pW;
        const val = tMin+(i/5)*(tMax-tMin);
        ctx.beginPath(); ctx.moveTo(x,pad.top); ctx.lineTo(x,pad.top+pH); ctx.stroke();
        let label;
        if (val >= 1) label = val.toFixed(1)+'s';
        else if (val >= 0.001) label = (val*1000).toFixed(1)+'ms';
        else label = (val*1e6).toFixed(0)+'us';
        ctx.fillText(label, x, pad.top+pH+20);
    }
    active.forEach((sig, idx) => {
        const d = datasets[sig]||[];
        const ci = signalNames.indexOf(sig);
        ctx.strokeStyle = colors[ci%colors.length];
        ctx.lineWidth = 2;
        ctx.beginPath();
        for (let i=0;i<time.length&&i<d.length;i++) {
            const x = pad.left+((time[i]-tMin)/(tMax-tMin))*pW;
            const y = pad.top+pH-((d[i]-vMin)/(vMax-vMin))*pH;
            if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
        }
        ctx.stroke();
        ctx.fillStyle = colors[ci%colors.length];
        ctx.font = 'bold 12px IBM Plex Sans, sans-serif';
        ctx.textAlign = 'left';
        const lastI = Math.min(time.length,d.length)-1;
        if(lastI>=0) {
            const lx = pad.left+((time[lastI]-tMin)/(tMax-tMin))*pW;
            const ly = pad.top+pH-((d[lastI]-vMin)/(vMax-vMin))*pH;
            ctx.fillText(sig, Math.min(lx, W-sig.length*8), ly-8);
        }
    });
}
window.addEventListener('load', redraw);
window.addEventListener('resize', redraw);
</script>
</body>
</html>'''

        plot_path = os.path.join(
            self.diary_folder,
            'sim_plot_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.html'
        )
        with open(plot_path, 'w', encoding='utf-8') as f:
            f.write(html)
        return plot_path