import wx
import os
import re
import json
import webbrowser
from datetime import datetime
from collections import Counter


class DiaryPanel(wx.Frame):

    def __init__(self, parent, diary_folder, board=None, project_folder=None):
        super().__init__(parent, title='KiCad Design Diary v2', size=(920, 700))
        self.diary_folder = diary_folder
        self.board = board
        self.project_folder = project_folder

        bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        fg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
        is_dark = bg.Red() < 128

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(panel, label='KiCad Design Diary — Timeline')
        title_font = title.GetFont()
        title_font.SetPointSize(14)
        title_font.SetWeight(wx.FONTWEIGHT_BOLD)
        title.SetFont(title_font)
        vbox.Add(title, flag=wx.ALL, border=10)

        stale_changes = self.get_changes_since_last_checkpoint()
        if stale_changes:
            warning_text = (
                '⚠ STALE NETLIST DETECTED — '
                f'{len(stale_changes)} change(s) since last simulation:\n'
            )
            for c in stale_changes[:5]:
                warning_text += f'  • {c}\n'
            if len(stale_changes) > 5:
                warning_text += f'  ... and {len(stale_changes) - 5} more'
            warning_banner = wx.StaticText(panel, label=warning_text)
            warning_banner.SetForegroundColour(wx.Colour(255, 140, 50) if is_dark else wx.Colour(180, 60, 0))
            vbox.Add(warning_banner, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)
        else:
            ok_text = wx.StaticText(
                panel,
                label='✓ Netlist is up to date — safe to simulate.'
            )
            ok_text.SetForegroundColour(wx.Colour(100, 220, 120) if is_dark else wx.Colour(30, 100, 50))
            vbox.Add(ok_text, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        self.is_dark = is_dark

        self.list_ctrl = wx.ListCtrl(
            panel, style=wx.LC_REPORT | wx.BORDER_SUNKEN
        )
        self.list_ctrl.InsertColumn(0, 'Timestamp', width=150)
        self.list_ctrl.InsertColumn(1, 'Type', width=75)
        self.list_ctrl.InsertColumn(2, 'Change', width=480)
        self.list_ctrl.InsertColumn(3, 'Tag', width=120)
        vbox.Add(self.list_ctrl, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        row1 = wx.BoxSizer(wx.HORIZONTAL)

        btn_sim_run = wx.Button(panel, label='▶ Run Simulation')
        btn_sim_run.SetForegroundColour(wx.Colour(30, 100, 50))
        btn_sim_run.Bind(wx.EVT_BUTTON, self.on_run_simulation)
        row1.Add(btn_sim_run, flag=wx.RIGHT, border=5)

        btn_esim = wx.Button(panel, label='Launch eSim')
        btn_esim.Bind(wx.EVT_BUTTON, self.on_launch_esim)
        row1.Add(btn_esim, flag=wx.RIGHT, border=5)

        btn_sim = wx.Button(panel, label='Mark Checkpoint')
        btn_sim.Bind(wx.EVT_BUTTON, self.on_simulation_checkpoint)
        row1.Add(btn_sim, flag=wx.RIGHT, border=5)

        btn_rollback = wx.Button(panel, label='⏪ Rollback')
        btn_rollback.Bind(wx.EVT_BUTTON, self.on_rollback)
        row1.Add(btn_rollback, flag=wx.RIGHT, border=5)

        vbox.Add(row1, flag=wx.LEFT | wx.RIGHT, border=10)
        vbox.AddSpacer(5)

        row2 = wx.BoxSizer(wx.HORIZONTAL)

        btn_history = wx.Button(panel, label='Component History')
        btn_history.Bind(wx.EVT_BUTTON, self.on_component_history)
        row2.Add(btn_history, flag=wx.RIGHT, border=5)

        btn_tag = wx.Button(panel, label='🏷 Tag Snapshot')
        btn_tag.Bind(wx.EVT_BUTTON, self.on_tag_snapshot)
        row2.Add(btn_tag, flag=wx.RIGHT, border=5)

        btn_compare = wx.Button(panel, label='Compare Snapshots')
        btn_compare.Bind(wx.EVT_BUTTON, self.on_compare_snapshots)
        row2.Add(btn_compare, flag=wx.RIGHT, border=5)

        btn_export = wx.Button(panel, label='Export HTML Report')
        btn_export.Bind(wx.EVT_BUTTON, self.on_export_html)
        row2.Add(btn_export, flag=wx.RIGHT, border=5)

        vbox.Add(row2, flag=wx.ALL, border=10)

        panel.SetSizer(vbox)

        self.snapshot_files = []
        self.tags = {}
        self._load_tags()
        self.load_entries()
        self.Centre()
        self.Show()

    def _load_tags(self):
        from kicad_design_diary.plugin import DesignDiaryPlugin as Core
        self.tags = Core.get_tags(self.diary_folder)
        self._tag_by_fname = {}
        for tag_name, info in self.tags.items():
            fname = info.get('snapshot', '')
            self._tag_by_fname[fname] = tag_name

    def load_entries(self):
        all_files = sorted([
            f for f in os.listdir(self.diary_folder)
            if f.endswith('.json')
            and not f.startswith('_')
            and not f.startswith('SCH_')
            and not f.startswith('RUN_')
        ], reverse=True)
        self.snapshot_files = []

        for fname in all_files:
            path = os.path.join(self.diary_folder, fname)
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue

            timestamp = data.get('timestamp', fname)
            changes = data.get('changes', [])
            if fname.startswith('SIM_'):
                change_type = 'SIM'
            elif fname.startswith('SCH_'):
                change_type = 'SCH'
            elif fname.startswith('RUN_'):
                change_type = 'RUN'
            else:
                change_type = 'PCB'

            tag_label = self._tag_by_fname.get(fname, '')

            if changes:
                for change in changes:
                    if 'ROLLBACK' in change:
                        line_type = 'ROLLBACK'
                    elif 'SIMULATION' in change:
                        line_type = 'RUN'
                    elif 'track' in change.lower() or 'Track' in change:
                        line_type = 'TRACK'
                    elif change.startswith('Schematic:'):
                        line_type = 'SCH'
                    elif change_type == 'SIM':
                        line_type = 'SIM'
                    elif change_type == 'RUN':
                        line_type = 'RUN'
                    else:
                        line_type = 'PCB'

                    idx = self.list_ctrl.InsertItem(
                        self.list_ctrl.GetItemCount(), timestamp
                    )
                    self.list_ctrl.SetItem(idx, 1, line_type)
                    self.list_ctrl.SetItem(idx, 2, change)
                    self.list_ctrl.SetItem(idx, 3, tag_label)

                    if line_type == 'TRACK':
                        c = wx.Colour(30, 50, 70) if self.is_dark else wx.Colour(224, 235, 245)
                        self.list_ctrl.SetItemBackgroundColour(idx, c)
                    elif line_type == 'SCH':
                        c = wx.Colour(60, 55, 30) if self.is_dark else wx.Colour(252, 248, 232)
                        self.list_ctrl.SetItemBackgroundColour(idx, c)
                    elif line_type == 'SIM':
                        c = wx.Colour(25, 55, 35) if self.is_dark else wx.Colour(230, 245, 233)
                        self.list_ctrl.SetItemBackgroundColour(idx, c)
                    elif line_type == 'RUN':
                        c = wx.Colour(30, 45, 65) if self.is_dark else wx.Colour(232, 240, 250)
                        self.list_ctrl.SetItemBackgroundColour(idx, c)
                    elif line_type == 'ROLLBACK':
                        c = wx.Colour(70, 30, 30) if self.is_dark else wx.Colour(250, 225, 225)
                        self.list_ctrl.SetItemBackgroundColour(idx, c)

            self.snapshot_files.append((fname, data))

    def get_changes_since_last_checkpoint(self):
        all_files = sorted([
            f for f in os.listdir(self.diary_folder)
            if f.endswith('.json') and not f.startswith('_')
        ])
        sim_files = sorted([f for f in all_files if f.startswith('SIM_')])
        pcb_files = sorted([
            f for f in all_files
            if not f.startswith('SIM_') and not f.startswith('SCH_')
            and not f.startswith('RUN_')
        ])

        if not sim_files:
            return []

        last_sim_time = sim_files[-1].replace('SIM_', '').replace('.json', '')
        changes = []
        for fname in pcb_files:
            file_time = fname.replace('.json', '')
            if file_time > last_sim_time:
                path = os.path.join(self.diary_folder, fname)
                try:
                    with open(path, 'r') as f:
                        data = json.load(f)
                    changes.extend(data.get('changes', []))
                except (json.JSONDecodeError, IOError):
                    continue
        return changes

    def _refresh(self):
        self.list_ctrl.DeleteAllItems()
        self.snapshot_files = []
        self._load_tags()
        self.load_entries()

    def on_component_history(self, event):
        dlg = wx.TextEntryDialog(
            self, 'Enter component reference (e.g. R1, C3, U1):',
            'Component History'
        )
        if dlg.ShowModal() == wx.ID_OK:
            ref = dlg.GetValue().strip().upper()
            if ref:
                ComponentHistoryFrame(self, self.diary_folder, ref)
        dlg.Destroy()

    def on_run_simulation(self, event):
        if not self.project_folder:
            wx.MessageBox('Project folder not available.', 'Simulation', wx.OK | wx.ICON_WARNING)
            return

        from kicad_design_diary.simulation_engine import SimulationEngine
        engine = SimulationEngine(self.project_folder, self.diary_folder)

        ngspice = engine.find_ngspice()
        if not ngspice:
            wx.MessageBox(
                'ngspice not found.\n\n'
                'Checked:\n'
                '  C:\\FOSSEE\\nghdl-simulator\\bin\\ngspice.exe\n'
                '  /usr/bin/ngspice (WSL)',
                'Simulation', wx.OK | wx.ICON_WARNING
            )
            return

        components = None
        if self.board:
            from kicad_design_diary.plugin import DesignDiaryPlugin as Core
            components = Core.snapshot_components(self.board)

        cir_path = engine.find_cir_file()

        status = engine.get_simulatability_status(cir_path, components)
        if not status['simulatable']:
            if engine.should_show_popup_warning(cir_path, components):
                wx.MessageBox(
                    status['message'],
                    'Circuit Not Simulatable',
                    wx.OK | wx.ICON_INFORMATION
                )
                engine.mark_warning_shown(cir_path, components)
            else:
                wx.MessageBox(
                    status['short_message'],
                    'Circuit Not Simulatable',
                    wx.OK | wx.ICON_INFORMATION
                )
            return

        if not cir_path:
            confirm = wx.MessageBox(
                'No .cir file found in your project.\n\n'
                'You need to run eSim\'s "KiCad to Ngspice" converter\n'
                'once to generate the .cir file.\n\n'
                'After that, this plugin will handle everything.\n\n'
                'Launch eSim now?',
                'Simulation', wx.YES_NO | wx.ICON_QUESTION
            )
            if confirm == wx.YES:
                self.on_launch_esim(event)
            return


        wx.MessageBox(
            f'Running simulation...\n'
            f'Circuit: {os.path.basename(cir_path)}\n'
            f'Engine: {os.path.basename(ngspice)}',
            'Simulation', wx.OK | wx.ICON_INFORMATION
        )

        success, message, raw_path, log_path = engine.run_simulation(cir_path, components)

        if success:
            result_msg = f'✓ Simulation completed!\n\n{message}'
            if raw_path and os.path.exists(raw_path):
                plot_path = engine.generate_plot_html(raw_path)
                if plot_path:
                    result_msg += f'\n\nPlot saved: {os.path.basename(plot_path)}'
                    open_plot = wx.MessageBox(
                        result_msg + '\n\nOpen plot in browser?',
                        'Simulation Complete',
                        wx.YES_NO | wx.ICON_INFORMATION
                    )
                    if open_plot == wx.YES:
                        webbrowser.open('file://' + os.path.abspath(plot_path))
                else:
                    wx.MessageBox(result_msg, 'Simulation Complete', wx.OK | wx.ICON_INFORMATION)
            else:
                wx.MessageBox(result_msg, 'Simulation Complete', wx.OK | wx.ICON_INFORMATION)
        else:
            wx.MessageBox(
                f'✗ Simulation failed:\n\n{message}',
                'Simulation Failed', wx.OK | wx.ICON_ERROR
            )

        self._refresh()

    def on_launch_esim(self, event):
        from kicad_design_diary.simulation_engine import SimulationEngine
        engine = SimulationEngine(self.project_folder, self.diary_folder)
        success, message = engine.launch_esim()
        if success:
            wx.MessageBox(
                'eSim launched.\n\n'
                'Steps:\n'
                '1. Open your .kicad_sch in eSim\n'
                '2. Click "KiCad to Ngspice Converter"\n'
                '3. Configure analysis type and models\n'
                '4. Click Convert\n\n'
                'After that, come back here and click "▶ Run Simulation" '
                'to simulate directly from the plugin.',
                'eSim', wx.OK | wx.ICON_INFORMATION
            )
        else:
            wx.MessageBox(message, 'eSim', wx.OK | wx.ICON_WARNING)

    def on_tag_snapshot(self, event):
        selected_idx = self.list_ctrl.GetFirstSelected()
        if selected_idx == -1:
            wx.MessageBox(
                'Select a row in the timeline first.',
                'Tag Snapshot', wx.OK | wx.ICON_INFORMATION
            )
            return

        selected_timestamp = self.list_ctrl.GetItemText(selected_idx, 0)

        target_fname = None
        for fname, data in self.snapshot_files:
            if data.get('timestamp') == selected_timestamp:
                target_fname = fname
                break

        if not target_fname:
            wx.MessageBox('Could not find snapshot.', 'Tag', wx.OK | wx.ICON_WARNING)
            return

        dlg = wx.TextEntryDialog(
            self,
            f'Enter a tag name for snapshot at {selected_timestamp}:\n'
            f'(e.g. "v1-before-review", "pre-simulation-fix", "final-values")',
            'Tag Snapshot'
        )
        if dlg.ShowModal() == wx.ID_OK:
            tag_name = dlg.GetValue().strip()
            if tag_name:
                from kicad_design_diary.plugin import DesignDiaryPlugin as Core
                Core.tag_snapshot(self.diary_folder, target_fname, tag_name)
                wx.MessageBox(
                    f'Tagged as: {tag_name}',
                    'Tag Created', wx.OK | wx.ICON_INFORMATION
                )
                self._refresh()
        dlg.Destroy()

    def on_compare_snapshots(self, event):
        pcb_snapshots = [
            (fname, data) for fname, data in self.snapshot_files
            if not fname.startswith('SIM_') and not fname.startswith('SCH_')
            and not fname.startswith('RUN_') and not fname.startswith('_')
            and data.get('components')
        ]

        if len(pcb_snapshots) < 2:
            wx.MessageBox(
                'Need at least 2 PCB snapshots to compare.',
                'Compare', wx.OK | wx.ICON_INFORMATION
            )
            return

        choices = []
        for fname, data in pcb_snapshots:
            ts = data.get('timestamp', fname)
            tag = self._tag_by_fname.get(fname, '')
            label = f"{ts}"
            if tag:
                label += f"  [{tag}]"
            choices.append(label)

        dlg_a = wx.SingleChoiceDialog(
            self, 'Select FIRST snapshot (older):', 'Compare — Step 1', choices
        )
        if dlg_a.ShowModal() != wx.ID_OK:
            dlg_a.Destroy()
            return
        idx_a = dlg_a.GetSelection()
        dlg_a.Destroy()

        dlg_b = wx.SingleChoiceDialog(
            self, 'Select SECOND snapshot (newer):', 'Compare — Step 2', choices
        )
        if dlg_b.ShowModal() != wx.ID_OK:
            dlg_b.Destroy()
            return
        idx_b = dlg_b.GetSelection()
        dlg_b.Destroy()

        fname_a = pcb_snapshots[idx_a][0]
        fname_b = pcb_snapshots[idx_b][0]
        ts_a = pcb_snapshots[idx_a][1].get('timestamp', fname_a)
        ts_b = pcb_snapshots[idx_b][1].get('timestamp', fname_b)

        from kicad_design_diary.plugin import DesignDiaryPlugin as Core
        diffs = Core.compare_snapshots(self.diary_folder, fname_a, fname_b)

        if diffs:
            msg = f"Comparing:\n  A: {ts_a}\n  B: {ts_b}\n\nDifferences:\n"
            msg += '\n'.join(diffs[:30])
            if len(diffs) > 30:
                msg += f'\n... and {len(diffs) - 30} more'
        else:
            msg = f"No differences between:\n  A: {ts_a}\n  B: {ts_b}"

        wx.MessageBox(msg, 'Snapshot Comparison', wx.OK | wx.ICON_INFORMATION)

    def on_rollback(self, event):
        if self.board is None:
            wx.MessageBox(
                'Board reference not available.',
                'Rollback', wx.OK | wx.ICON_WARNING
            )
            return

        selected_idx = self.list_ctrl.GetFirstSelected()
        if selected_idx == -1:
            wx.MessageBox(
                'Select a row in the timeline first, then click Rollback.',
                'Rollback', wx.OK | wx.ICON_INFORMATION
            )
            return

        selected_timestamp = self.list_ctrl.GetItemText(selected_idx, 0)

        target_snapshot = None
        target_ts = None

        for fname, data in self.snapshot_files:
            if data.get('timestamp') == selected_timestamp and data.get('components'):
                target_snapshot = data
                target_ts = selected_timestamp
                break

        if target_snapshot is None:
            for fname, data in self.snapshot_files:
                ts = data.get('timestamp', '')
                if ts <= selected_timestamp and data.get('components'):
                    target_snapshot = data
                    target_ts = ts
                    break

        if target_snapshot is None:
            for fname, data in reversed(self.snapshot_files):
                if data.get('components'):
                    target_snapshot = data
                    target_ts = data.get('timestamp', '')
                    break

        if target_snapshot is None:
            wx.MessageBox(
                'No snapshot with component data found.\n'
                'Rollback requires a PCB snapshot (not SIM or SCH).',
                'Rollback', wx.OK | wx.ICON_WARNING
            )
            return

        comp_count = len(target_snapshot.get('components', {}))
        confirm = wx.MessageBox(
            f"Restore board to state from {target_ts}?\n"
            f"({comp_count} components in this snapshot)\n\n"
            "This will change component values, positions, and rotations "
            "to match the selected snapshot.\n\n"
            "⚠ This cannot be undone automatically — save your board first!",
            'Confirm Rollback',
            wx.YES_NO | wx.ICON_QUESTION
        )
        if confirm != wx.YES:
            return

        from kicad_design_diary.plugin import DesignDiaryPlugin as Core
        success = Core.restore_snapshot(self.board, target_snapshot)

        if success:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            filename = datetime.now().strftime('%Y%m%d_%H%M%S') + '.json'
            rollback_snapshot = {
                'timestamp': timestamp,
                'components': Core.snapshot_components(self.board),
                'tracks': Core.snapshot_tracks(self.board),
                'changes': [
                    f"ROLLBACK: Board restored to snapshot from "
                    f"{selected_timestamp}"
                ],
            }
            path = os.path.join(self.diary_folder, filename)
            with open(path, 'w') as f:
                json.dump(rollback_snapshot, f, indent=2)

            self._refresh()

    def on_simulation_checkpoint(self, event):
        changes_since_last = self.get_changes_since_last_checkpoint()

        if changes_since_last:
            msg = 'Changes since last simulation:\n'
            for c in changes_since_last[:15]:
                msg += f'  • {c}\n'
            if len(changes_since_last) > 15:
                msg += f'  ... and {len(changes_since_last) - 15} more\n'
            msg += '\nMark checkpoint and auto-export netlist?'
        else:
            msg = 'No changes since last checkpoint.\nMark checkpoint anyway?'

        confirm = wx.MessageBox(msg, 'Simulation Checkpoint',
                                wx.YES_NO | wx.ICON_QUESTION)
        if confirm != wx.YES:
            return

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        filename = 'SIM_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.json'
        summary = (
            f"Simulation checkpoint — "
            f"{len(changes_since_last)} change(s) since last"
        )
        checkpoint = {
            'timestamp': timestamp,
            'type': 'simulation_checkpoint',
            'changes_since_last': changes_since_last,
            'changes': [summary],
        }
        path = os.path.join(self.diary_folder, filename)
        with open(path, 'w') as f:
            json.dump(checkpoint, f, indent=2)

        export_msg = ""
        if self.board and self.project_folder:
            from kicad_design_diary.plugin import DesignDiaryPlugin as Core
            success, detail = Core.auto_export_netlist(
                self.board, self.project_folder
            )
            if success:
                export_msg = f"\n\n✓ Netlist auto-exported:\n{detail}"
            else:
                export_msg = (
                    f"\n\n⚠ Netlist export failed:\n{detail}\n"
                    "You may need to export manually from KiCad."
                )
        else:
            export_msg = "\n\nNetlist auto-export skipped."

        wx.MessageBox(
            f"✓ Checkpoint saved at {timestamp}{export_msg}",
            'Simulation Checkpoint',
            wx.OK | wx.ICON_INFORMATION
        )

        self._refresh()

    def _gather_report_data(self):
        all_files = sorted([
            f for f in os.listdir(self.diary_folder)
            if f.endswith('.json') and not f.startswith('_')
        ])

        sessions = []
        all_changes = []
        all_refs = set()
        ref_counter = Counter()
        board_file = ''

        for fname in all_files:
            path = os.path.join(self.diary_folder, fname)
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue

            if not board_file:
                board_file = data.get('board_file', '')

            timestamp = data.get('timestamp', fname)
            changes = data.get('changes', [])
            components = data.get('components', {})

            if fname.startswith('SIM_'):
                ftype = 'SIM'
            elif fname.startswith('SCH_'):
                ftype = 'SCH'
            elif fname.startswith('RUN_'):
                ftype = 'RUN'
            else:
                ftype = 'PCB'

            sessions.append({
                'fname': fname,
                'timestamp': timestamp,
                'changes': changes,
                'type': ftype,
            })

            for ref in components:
                all_refs.add(ref)

            for change in changes:
                ref_match = re.search(r'\b([A-Z]+\d+)\b', change)
                if ref_match:
                    ref_counter[ref_match.group(1)] += 1

                if 'ROLLBACK' in change:
                    ctype = 'ROLLBACK'
                elif 'SIMULATION' in change:
                    ctype = 'RUN'
                elif 'track' in change.lower():
                    ctype = 'TRACK'
                elif change.startswith('Schematic:'):
                    ctype = 'SCH'
                elif ftype == 'SIM':
                    ctype = 'SIM'
                else:
                    ctype = 'PCB'

                all_changes.append({
                    'timestamp': timestamp,
                    'change': change,
                    'type': ctype,
                    'fname': fname,
                })

        stale = self.get_changes_since_last_checkpoint()
        top_refs = ref_counter.most_common(12)
        max_ref_count = top_refs[0][1] if top_refs else 1

        sim_count = sum(1 for s in sessions if s['type'] == 'RUN')

        return {
            'sessions': sessions,
            'all_changes': all_changes,
            'all_refs': all_refs,
            'top_refs': top_refs,
            'max_ref_count': max_ref_count,
            'board_file': board_file,
            'stale': stale,
            'total_sessions': len(sessions),
            'total_changes': len(all_changes),
            'total_refs': len(all_refs),
            'sim_count': sim_count,
            'tags': self.tags,
        }

    def on_export_html(self, event):
        d = self._gather_report_data()

        board_name = os.path.basename(d['board_file']) if d['board_file'] else 'Unknown'
        gen_time = datetime.now().strftime('%B %d, %Y at %H:%M:%S')

        if d['stale']:
            netlist_html = (
                '<div class="netlist-banner netlist-stale">'
                f'⚠ Stale netlist — {len(d["stale"])} change(s) since last simulation checkpoint.'
                '</div>'
            )
        else:
            netlist_html = (
                '<div class="netlist-banner netlist-ok">'
                '✓ Netlist is up to date — no changes since last simulation checkpoint.'
                '</div>'
            )

        freq_bars = ''
        for ref, count in d['top_refs']:
            pct = (count / d['max_ref_count']) * 100
            freq_bars += (
                f'<div class="freq-row">'
                f'<span class="freq-label">{ref}</span>'
                f'<div class="freq-track"><div class="freq-fill" style="width:{pct}%"></div></div>'
                f'<span class="freq-count">{count}</span>'
                f'</div>\n'
            )

        timeline_rows = ''
        for entry in reversed(d['all_changes']):
            ctype = entry['type']
            badge_map = {
                'PCB': ('pcb', 'PCB'),
                'SCH': ('sch', 'SCHEMATIC'),
                'TRACK': ('track', 'TRACK'),
                'SIM': ('sim', 'CHECKPOINT'),
                'RUN': ('run', 'SIMULATION'),
                'ROLLBACK': ('rollback', 'ROLLBACK'),
            }
            cls, label = badge_map.get(ctype, ('pcb', 'PCB'))

            tag_html = ''
            fname = entry.get('fname', '')
            tag = self._tag_by_fname.get(fname, '')
            if tag:
                tag_html = f'<span class="tag-pill">{tag}</span>'

            timeline_rows += (
                f'<div class="tl-entry tl-{cls}">'
                f'<div class="tl-time">{entry["timestamp"]}</div>'
                f'<div class="tl-badge badge-{cls}">{label}</div>'
                f'<div class="tl-text">{entry["change"]} {tag_html}</div>'
                f'</div>\n'
            )

        sim_entries = ''
        for s in reversed(d['sessions']):
            if s['type'] == 'SIM':
                sim_entries += (
                    f'<div class="sim-card">'
                    f'<span class="sim-time">{s["timestamp"]}</span>'
                    f'<span class="sim-label">SIMULATION CHECKPOINT</span>'
                    f'</div>\n'
                )
            elif s['type'] == 'RUN':
                status = 'PASSED' if any('Passed' in c for c in s['changes']) else 'FAILED'
                status_cls = 'sim-pass' if status == 'PASSED' else 'sim-fail'
                sim_entries += (
                    f'<div class="sim-card {status_cls}">'
                    f'<span class="sim-time">{s["timestamp"]}</span>'
                    f'<span class="sim-label">SIMULATION {status}</span>'
                    f'</div>\n'
                )

        tags_html = ''
        if d['tags']:
            tags_html = '<div class="section-title">Tagged Snapshots</div>\n'
            for tag_name, info in sorted(d['tags'].items(), key=lambda x: x[1].get('created', ''), reverse=True):
                tags_html += (
                    f'<div class="tag-card">'
                    f'<span class="tag-name">🏷 {tag_name}</span>'
                    f'<span class="tag-meta">{info.get("created", "")} · {info.get("snapshot", "")}</span>'
                    f'</div>\n'
                )
            tags_html += '<div style="margin-bottom:40px"></div>\n'

        html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KiCad Design Diary — Report</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=IBM+Plex+Sans:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
:root {{
    --bg: #f5f2ed; --bg-card: #faf8f5; --bg-warm: #f0ece4;
    --text-primary: #2d3436; --text-secondary: #636e72; --text-muted: #9ba3a9;
    --accent: #c4713b; --accent-light: #e8a06c; --accent-dark: #8b4d2a;
    --green: #4a7c59; --green-bg: #e8f0ea; --green-border: #a8c5b0;
    --amber: #b8860b; --amber-bg: #fdf6e3;
    --blue: #456b8a; --blue-bg: #e4ecf2;
    --red: #8b3a3a; --red-bg: #f5e0e0;
    --border: #e0dbd3;
    --shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.03);
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'IBM Plex Sans',sans-serif; background:var(--bg); color:var(--text-primary); line-height:1.6; -webkit-font-smoothing:antialiased; }}
.container {{ max-width:960px; margin:0 auto; padding:48px 32px 80px; }}
header {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:48px; padding-bottom:32px; border-bottom:1px solid var(--border); }}
.header-left h1 {{ font-family:'DM Serif Display',serif; font-size:2.1rem; font-weight:400; letter-spacing:-0.02em; line-height:1.2; }}
.header-left h1 span {{ color:var(--accent); }}
.header-left .subtitle {{ font-size:0.85rem; color:var(--text-muted); margin-top:6px; font-weight:300; letter-spacing:0.02em; }}
.header-right {{ text-align:right; font-family:'JetBrains Mono',monospace; font-size:0.78rem; color:var(--text-muted); line-height:1.8; }}
.netlist-banner {{ padding:14px 20px; border-radius:6px; font-size:0.88rem; font-weight:500; margin-bottom:40px; border-left:4px solid; }}
.netlist-ok {{ background:var(--green-bg); border-color:var(--green); color:var(--green); }}
.netlist-stale {{ background:var(--amber-bg); border-color:var(--amber); color:#8a6508; }}
.stats-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:1px; background:var(--border); border-radius:10px; overflow:hidden; margin-bottom:48px; box-shadow:var(--shadow); }}
.stat-card {{ background:var(--bg-card); padding:28px 20px; text-align:center; }}
.stat-number {{ font-family:'DM Serif Display',serif; font-size:2.6rem; color:var(--text-primary); line-height:1; letter-spacing:-0.03em; }}
.stat-number sup {{ font-family:'IBM Plex Sans',sans-serif; font-size:0.35em; color:var(--accent); font-weight:500; vertical-align:super; letter-spacing:0.04em; }}
.stat-label {{ font-size:0.65rem; text-transform:uppercase; letter-spacing:0.12em; color:var(--text-muted); margin-top:8px; font-weight:500; }}
.section-title {{ font-size:0.72rem; text-transform:uppercase; letter-spacing:0.14em; color:var(--text-muted); font-weight:600; margin-bottom:20px; display:flex; align-items:center; gap:16px; }}
.section-title::after {{ content:''; flex:1; height:1px; background:var(--border); }}
.freq-card {{ background:var(--bg-card); border-radius:10px; padding:28px 32px; margin-bottom:48px; box-shadow:var(--shadow); }}
.freq-row {{ display:flex; align-items:center; padding:9px 0; gap:16px; }}
.freq-label {{ font-family:'JetBrains Mono',monospace; font-size:0.82rem; font-weight:500; width:48px; text-align:right; flex-shrink:0; }}
.freq-track {{ flex:1; height:10px; background:var(--bg-warm); border-radius:5px; overflow:hidden; }}
.freq-fill {{ height:100%; background:linear-gradient(90deg,var(--accent-dark),var(--accent),var(--accent-light)); border-radius:5px; }}
.freq-count {{ font-family:'JetBrains Mono',monospace; font-size:0.78rem; color:var(--text-muted); width:32px; text-align:left; flex-shrink:0; }}
.sim-card {{ display:flex; justify-content:space-between; align-items:center; background:var(--green-bg); border-radius:8px; padding:14px 20px; margin-bottom:8px; border:1px solid var(--green-border); }}
.sim-pass {{ background:var(--green-bg); border-color:var(--green-border); }}
.sim-fail {{ background:var(--red-bg); border-color:#d4a0a0; }}
.sim-fail .sim-label {{ color:var(--red); }}
.sim-time {{ font-family:'JetBrains Mono',monospace; font-size:0.82rem; color:var(--text-secondary); }}
.sim-label {{ font-size:0.72rem; text-transform:uppercase; letter-spacing:0.1em; font-weight:600; color:var(--green); }}
.tag-card {{ display:flex; justify-content:space-between; align-items:center; background:var(--bg-card); border-radius:8px; padding:14px 20px; margin-bottom:8px; border:1px solid var(--border); }}
.tag-name {{ font-weight:600; font-size:0.9rem; }}
.tag-meta {{ font-family:'JetBrains Mono',monospace; font-size:0.75rem; color:var(--text-muted); }}
.tag-pill {{ display:inline-block; background:var(--amber-bg); color:var(--amber); font-size:0.7rem; padding:2px 8px; border-radius:4px; font-weight:600; margin-left:8px; letter-spacing:0.03em; }}
.tl-entry {{ display:grid; grid-template-columns:150px 100px 1fr; gap:12px; align-items:center; padding:12px 16px; border-radius:6px; margin-bottom:3px; font-size:0.86rem; transition:background 0.15s; }}
.tl-entry:hover {{ background:var(--bg-warm); }}
.tl-time {{ font-family:'JetBrains Mono',monospace; font-size:0.78rem; color:var(--text-muted); }}
.tl-badge {{ font-size:0.65rem; text-transform:uppercase; letter-spacing:0.08em; font-weight:600; padding:3px 10px; border-radius:4px; text-align:center; width:fit-content; }}
.badge-pcb {{ background:var(--bg-warm); color:var(--text-secondary); }}
.badge-sch {{ background:var(--amber-bg); color:var(--amber); }}
.badge-track {{ background:var(--blue-bg); color:var(--blue); }}
.badge-sim {{ background:var(--green-bg); color:var(--green); }}
.badge-run {{ background:var(--blue-bg); color:var(--blue); }}
.badge-rollback {{ background:var(--red-bg); color:var(--red); }}
.tl-text {{ color:var(--text-primary); font-weight:400; }}
.tl-rollback .tl-text {{ font-weight:600; color:var(--red); }}
.tl-track .tl-text {{ color:var(--blue); }}
.tl-sch .tl-text {{ color:#6b5a00; }}
footer {{ margin-top:64px; padding-top:24px; border-top:1px solid var(--border); text-align:center; font-size:0.78rem; color:var(--text-muted); }}
footer a {{ color:var(--accent); text-decoration:none; }}
</style>
</head>
<body>
<div class="container">
<header>
    <div class="header-left">
        <h1>KiCad Design <span>Diary</span></h1>
        <div class="subtitle">Automatic PCB &amp; Schematic Change History — eSim Integration</div>
    </div>
    <div class="header-right">Generated: {gen_time}<br>Board: {board_name}</div>
</header>

{netlist_html}

<div class="stats-grid">
    <div class="stat-card">
        <div class="stat-number">{d['total_sessions']}<sup>sessions</sup></div>
        <div class="stat-label">Total Sessions</div>
    </div>
    <div class="stat-card">
        <div class="stat-number">{d['total_changes']}<sup>events</sup></div>
        <div class="stat-label">Total Changes</div>
    </div>
    <div class="stat-card">
        <div class="stat-number">{d['total_refs']}<sup>refs</sup></div>
        <div class="stat-label">Components Tracked</div>
    </div>
    <div class="stat-card">
        <div class="stat-number">{d['sim_count']}<sup>runs</sup></div>
        <div class="stat-label">Simulations</div>
    </div>
</div>

<div class="section-title">Modification Frequency</div>
<div class="freq-card">{freq_bars}</div>

{tags_html}

<div class="section-title">Simulation &amp; Checkpoint History</div>
{sim_entries if sim_entries else '<div style="color:var(--text-muted);font-size:0.86rem;margin-bottom:40px;">No simulations or checkpoints recorded yet.</div>'}
<div style="margin-bottom:48px"></div>

<div class="section-title">Change Timeline</div>
{timeline_rows}

<footer>KiCad Design Diary v2 — github.com/Sia2005/kicad-design-diary</footer>
</div>
</body>
</html>'''

        html_path = os.path.join(self.diary_folder, 'design_diary_report.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)

        wx.MessageBox(
            f"HTML report saved:\n{html_path}",
            'Export Complete', wx.OK | wx.ICON_INFORMATION
        )


class ComponentHistoryFrame(wx.Frame):

    def __init__(self, parent, diary_folder, ref):
        super().__init__(parent, title=f'History of {ref}', size=(650, 450))
        self.ref = ref
        self.diary_folder = diary_folder

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        label = wx.StaticText(panel, label=f'All changes to {ref}:')
        label_font = label.GetFont()
        label_font.SetPointSize(12)
        label_font.SetWeight(wx.FONTWEIGHT_BOLD)
        label.SetFont(label_font)
        vbox.Add(label, flag=wx.ALL, border=10)

        self.list_ctrl = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.list_ctrl.InsertColumn(0, 'Timestamp', width=160)
        self.list_ctrl.InsertColumn(1, 'Change', width=450)
        vbox.Add(self.list_ctrl, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        panel.SetSizer(vbox)
        self.load_history()
        self.Centre()
        self.Show()

    def load_history(self):
        all_files = sorted([
            f for f in os.listdir(self.diary_folder)
            if f.endswith('.json')
            and not f.startswith('_')
            and not f.startswith('SCH_')
            and not f.startswith('SIM_')
            and not f.startswith('RUN_')
        ], reverse=True)
        for fname in all_files:
            path = os.path.join(self.diary_folder, fname)
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue

            timestamp = data.get('timestamp', fname)
            changes = data.get('changes', [])
            for change in changes:
                if re.search(r'\b' + re.escape(self.ref) + r'\b', change):
                    idx = self.list_ctrl.InsertItem(
                        self.list_ctrl.GetItemCount(), timestamp
                    )
                    self.list_ctrl.SetItem(idx, 1, change)