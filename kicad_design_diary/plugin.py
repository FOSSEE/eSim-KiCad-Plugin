import pcbnew
import os
import json
import subprocess
from datetime import datetime

import wx

_listener = None
_plugin_instance = None


class DesignDiaryPlugin:

    @staticmethod
    def snapshot_components(board):
        components = {}
        for fp in board.GetFootprints():
            pos = fp.GetPosition()
            components[fp.GetReference()] = {
                'value': fp.GetValue(),
                'footprint': fp.GetFPIDAsString(),
                'x': pcbnew.ToMM(pos.x),
                'y': pcbnew.ToMM(pos.y),
                'rotation': fp.GetOrientationDegrees(),
            }
        return components

    @staticmethod
    def snapshot_tracks(board):
        tracks = {}
        for idx, trk in enumerate(board.GetTracks()):
            start = trk.GetStart()
            end = trk.GetEnd()
            layer = trk.GetLayerName()
            width = pcbnew.ToMM(trk.GetWidth())
            net = trk.GetNetname()
            sx, sy = pcbnew.ToMM(start.x), pcbnew.ToMM(start.y)
            ex, ey = pcbnew.ToMM(end.x), pcbnew.ToMM(end.y)
            pts = sorted([(sx, sy), (ex, ey)])
            key = f"{net}|{layer}|{pts[0][0]:.3f},{pts[0][1]:.3f}-{pts[1][0]:.3f},{pts[1][1]:.3f}"
            is_via = isinstance(trk, pcbnew.PCB_VIA) if hasattr(pcbnew, 'PCB_VIA') else False
            tracks[key] = {
                'net': net,
                'layer': layer,
                'width_mm': round(width, 3),
                'start': [round(sx, 3), round(sy, 3)],
                'end': [round(ex, 3), round(ey, 3)],
                'is_via': is_via,
            }
        return tracks

    @staticmethod
    def diff_components(current, previous):
        changes = []
        for ref in current:
            if ref not in previous:
                changes.append(
                    f"PCB: Added component {ref} "
                    f"with value {current[ref]['value']}"
                )
            else:
                if current[ref]['value'] != previous[ref].get('value'):
                    changes.append(
                        f"PCB: Changed value of {ref} from "
                        f"{previous[ref].get('value')} to {current[ref]['value']}"
                    )
                if (current[ref].get('x') != previous[ref].get('x') or
                        current[ref].get('y') != previous[ref].get('y')):
                    changes.append(
                        f"PCB: Moved {ref} from "
                        f"({previous[ref].get('x')}, {previous[ref].get('y')}) to "
                        f"({current[ref]['x']}, {current[ref]['y']})"
                    )
                if current[ref].get('rotation') != previous[ref].get('rotation'):
                    changes.append(
                        f"PCB: Rotated {ref} from "
                        f"{previous[ref].get('rotation')}° to {current[ref]['rotation']}°"
                    )
        for ref in previous:
            if ref not in current:
                changes.append(f"PCB: Deleted component {ref}")
        return changes

    @staticmethod
    def diff_tracks(current, previous):
        changes = []
        for key in current:
            if key not in previous:
                t = current[key]
                changes.append(
                    f"PCB: Added track on {t['layer']} — "
                    f"net '{t['net']}', width {t['width_mm']}mm"
                )
            else:
                if current[key]['width_mm'] != previous[key]['width_mm']:
                    changes.append(
                        f"PCB: Changed track width on {current[key]['layer']} "
                        f"(net '{current[key]['net']}') from "
                        f"{previous[key]['width_mm']}mm to {current[key]['width_mm']}mm"
                    )
        for key in previous:
            if key not in current:
                t = previous[key]
                changes.append(
                    f"PCB: Deleted track on {t['layer']} — net '{t['net']}'"
                )
        return changes

    @staticmethod
    def restore_snapshot(board, snapshot_data):
        target_components = snapshot_data.get('components', {})
        if not target_components:
            wx.MessageBox(
                'This snapshot has no component data to restore.',
                'Rollback', wx.OK | wx.ICON_WARNING
            )
            return False

        board_fps = {}
        for fp in board.GetFootprints():
            board_fps[fp.GetReference()] = fp

        restored = []
        warnings = []

        for ref, data in target_components.items():
            if isinstance(data, str):
                data = {'value': data}

            if ref in board_fps:
                fp = board_fps[ref]

                target_value = data.get('value', '')
                if fp.GetValue() != target_value:
                    fp.SetValue(target_value)
                    restored.append(f"Restored {ref} value → {target_value}")

                if 'x' in data and 'y' in data:
                    target_pos = pcbnew.VECTOR2I(
                        pcbnew.FromMM(data['x']),
                        pcbnew.FromMM(data['y'])
                    )
                    if fp.GetPosition() != target_pos:
                        fp.SetPosition(target_pos)
                        restored.append(
                            f"Restored {ref} position → ({data['x']}, {data['y']})"
                        )

                if 'rotation' in data:
                    target_rot = data['rotation']
                    if fp.GetOrientationDegrees() != target_rot:
                        fp.SetOrientationDegrees(target_rot)
                        restored.append(f"Restored {ref} rotation → {target_rot}°")
            else:
                warnings.append(
                    f"⚠ {ref} not found on board — "
                    f"cannot auto-add (place it manually)"
                )

        for ref in board_fps:
            if ref not in target_components:
                warnings.append(
                    f"⚠ {ref} exists on board but was not in this snapshot — "
                    f"consider removing it manually"
                )

        pcbnew.Refresh()

        msg_parts = []
        if restored:
            msg_parts.append(f"✓ {len(restored)} properties restored:\n")
            msg_parts.extend(f"  • {r}\n" for r in restored[:20])
            if len(restored) > 20:
                msg_parts.append(f"  ... and {len(restored) - 20} more\n")
        if warnings:
            msg_parts.append(f"\n⚠ {len(warnings)} warnings:\n")
            msg_parts.extend(f"  • {w}\n" for w in warnings[:10])

        if not restored and not warnings:
            msg_parts.append("Board already matches this snapshot — nothing to change.")

        wx.MessageBox(''.join(msg_parts), 'Rollback Complete', wx.OK | wx.ICON_INFORMATION)
        return True

    @staticmethod
    def auto_export_netlist(board, project_folder):
        board_path = board.GetFileName()
        sch_files = [f for f in os.listdir(project_folder) if f.endswith('.kicad_sch')]
        if not sch_files:
            return False, "No .kicad_sch file found in project folder."

        sch_path = os.path.join(project_folder, sch_files[0])
        netlist_path = os.path.join(
            project_folder,
            os.path.splitext(sch_files[0])[0] + '.net'
        )

        is_wsl = False
        try:
            with open('/proc/version', 'r') as f:
                if 'microsoft' in f.read().lower():
                    is_wsl = True
        except FileNotFoundError:
            pass

        if is_wsl:
            try:
                sch_path_win = subprocess.check_output(
                    ['wslpath', '-w', sch_path]
                ).decode().strip()
                netlist_path_win = subprocess.check_output(
                    ['wslpath', '-w', netlist_path]
                ).decode().strip()
            except Exception:
                sch_path_win = sch_path
                netlist_path_win = netlist_path

            kicad_cli_candidates = [
                '/mnt/c/Program Files/KiCad/9.0/bin/kicad-cli.exe',
                '/mnt/c/Program Files/KiCad/8.0/bin/kicad-cli.exe',
                '/mnt/c/Program Files/KiCad/7.0/bin/kicad-cli.exe',
                '/mnt/c/Program Files/KiCad/bin/kicad-cli.exe',
            ]
            kicad_cli = None
            for candidate in kicad_cli_candidates:
                if os.path.exists(candidate):
                    kicad_cli = candidate
                    break

            if kicad_cli:
                try:
                    result = subprocess.run(
                        [kicad_cli, 'sch', 'export', 'netlist',
                         '--output', netlist_path_win, sch_path_win],
                        capture_output=True, text=True, timeout=30
                    )
                    if result.returncode == 0:
                        return True, f"Netlist exported → {netlist_path}"
                    else:
                        return False, f"kicad-cli error: {result.stderr}"
                except subprocess.TimeoutExpired:
                    return False, "kicad-cli timed out after 30s."
                except Exception as e:
                    return False, f"kicad-cli exception: {e}"

        try:
            result = subprocess.run(
                ['kicad-cli', 'sch', 'export', 'netlist',
                 '--output', netlist_path, sch_path],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return True, f"Netlist exported → {netlist_path}"
            else:
                return False, f"kicad-cli error: {result.stderr}"
        except FileNotFoundError:
            return False, (
                "kicad-cli not found. Please ensure KiCad 7+ is installed "
                "and kicad-cli is on your PATH."
            )
        except Exception as e:
            return False, f"Netlist export error: {e}"

    @staticmethod
    def tag_snapshot(diary_folder, snapshot_fname, tag_name):
        tags_path = os.path.join(diary_folder, '_tags.json')
        tags = {}
        if os.path.exists(tags_path):
            with open(tags_path, 'r') as f:
                tags = json.load(f)
        tags[tag_name] = {
            'snapshot': snapshot_fname,
            'created': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        with open(tags_path, 'w') as f:
            json.dump(tags, f, indent=2)
        return True

    @staticmethod
    def get_tags(diary_folder):
        tags_path = os.path.join(diary_folder, '_tags.json')
        if os.path.exists(tags_path):
            with open(tags_path, 'r') as f:
                return json.load(f)
        return {}

    @staticmethod
    def compare_snapshots(diary_folder, fname_a, fname_b):
        path_a = os.path.join(diary_folder, fname_a)
        path_b = os.path.join(diary_folder, fname_b)
        try:
            with open(path_a, 'r') as f:
                data_a = json.load(f)
            with open(path_b, 'r') as f:
                data_b = json.load(f)
        except Exception:
            return []

        comp_a = data_a.get('components', {})
        comp_b = data_b.get('components', {})
        diffs = []

        all_refs = set(list(comp_a.keys()) + list(comp_b.keys()))
        for ref in sorted(all_refs):
            in_a = ref in comp_a
            in_b = ref in comp_b
            if in_a and not in_b:
                diffs.append(f"  − {ref} ({comp_a[ref].get('value','')}) removed")
            elif in_b and not in_a:
                diffs.append(f"  + {ref} ({comp_b[ref].get('value','')}) added")
            elif in_a and in_b:
                val_a = comp_a[ref].get('value', '')
                val_b = comp_b[ref].get('value', '')
                if val_a != val_b:
                    diffs.append(f"  ~ {ref}: {val_a} → {val_b}")

        return diffs

    def Run(self):
        global _listener, _plugin_instance
        _plugin_instance = self

        board = pcbnew.GetBoard()
        board_path = board.GetFileName()
        if not board_path:
            wx.MessageBox(
                'Please save your project first.',
                'KiCad Design Diary',
                wx.OK | wx.ICON_WARNING,
            )
            return

        project_folder = os.path.dirname(board_path)
        board_name = os.path.splitext(os.path.basename(board_path))[0]
        diary_folder = os.path.join(project_folder, '.design_diary_' + board_name)
        os.makedirs(diary_folder, exist_ok=True)

        if _listener is None:
            from kicad_design_diary.board_listener import DesignDiaryListener
            _listener = DesignDiaryListener(board, diary_folder)
            board.AddListener(_listener)

        current_components = self.snapshot_components(board)
        current_tracks = self.snapshot_tracks(board)

        previous_components = {}
        previous_tracks = {}
        snapshots = sorted([
            f for f in os.listdir(diary_folder)
            if f.endswith('.json')
            and not f.startswith('SCH_')
            and not f.startswith('SIM_')
            and not f.startswith('RUN_')
            and not f.startswith('_')
        ])
        if snapshots:
            last_path = os.path.join(diary_folder, snapshots[-1])
            with open(last_path, 'r') as f:
                last_snapshot = json.load(f)
            previous_components = last_snapshot.get('components', {})
            previous_tracks = last_snapshot.get('tracks', {})

        changes = self.diff_components(current_components, previous_components)
        changes.extend(self.diff_tracks(current_tracks, previous_tracks))

        sch_files = [f for f in os.listdir(project_folder) if f.endswith('.kicad_sch')]
        if sch_files:
            sch_path = os.path.join(project_folder, sch_files[0])
            from kicad_design_diary.schematic_tracker import SchematicTracker
            sch_tracker = SchematicTracker(diary_folder)
            sch_tracker.take_snapshot(sch_path)

        if changes:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            filename = datetime.now().strftime('%Y%m%d_%H%M%S') + '.json'
            snapshot = {
                'timestamp': timestamp,
                'board_file': board_path,
                'components': current_components,
                'tracks': current_tracks,
                'changes': changes,
            }
            snapshot_path = os.path.join(diary_folder, filename)
            with open(snapshot_path, 'w') as f:
                json.dump(snapshot, f, indent=2)
            print(f"Design Diary: {len(changes)} change(s) saved → {filename}")

        from kicad_design_diary.ui_panel import DiaryPanel
        frame = DiaryPanel(None, diary_folder, board, project_folder)
