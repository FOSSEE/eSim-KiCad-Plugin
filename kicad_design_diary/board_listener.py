import pcbnew
import os
import json
from datetime import datetime


class DesignDiaryListener(pcbnew.BOARD_LISTENER):

    def __init__(self, board, diary_folder):
        super().__init__()
        self.board = board
        self.diary_folder = diary_folder
        os.makedirs(self.diary_folder, exist_ok=True)

    def get_components(self):
        components = {}
        for fp in self.board.GetFootprints():
            pos = fp.GetPosition()
            components[fp.GetReference()] = {
                'value': fp.GetValue(),
                'footprint': fp.GetFPIDAsString(),
                'x': pcbnew.ToMM(pos.x),
                'y': pcbnew.ToMM(pos.y),
                'rotation': fp.GetOrientationDegrees(),
            }
        return components

    def get_tracks_summary(self):
        tracks = {}
        for trk in self.board.GetTracks():
            start = trk.GetStart()
            end = trk.GetEnd()
            layer = trk.GetLayerName()
            net = trk.GetNetname()
            width = pcbnew.ToMM(trk.GetWidth())
            sx, sy = pcbnew.ToMM(start.x), pcbnew.ToMM(start.y)
            ex, ey = pcbnew.ToMM(end.x), pcbnew.ToMM(end.y)
            pts = sorted([(sx, sy), (ex, ey)])
            key = (
                f"{net}|{layer}|"
                f"{pts[0][0]:.3f},{pts[0][1]:.3f}-"
                f"{pts[1][0]:.3f},{pts[1][1]:.3f}"
            )
            tracks[key] = {
                'net': net,
                'layer': layer,
                'width_mm': round(width, 3),
                'start': [round(sx, 3), round(sy, 3)],
                'end': [round(ex, 3), round(ey, 3)],
            }
        return tracks

    def get_last_snapshot(self):
        snapshots = sorted([
            f for f in os.listdir(self.diary_folder)
            if f.endswith('.json')
            and not f.startswith('SCH_')
            and not f.startswith('SIM_')
            and not f.startswith('RUN_')
            and not f.startswith('_')
        ])
        if snapshots:
            path = os.path.join(self.diary_folder, snapshots[-1])
            with open(path, 'r') as f:
                data = json.load(f)
            return data
        return {}

    def save_snapshot(self, changes):
        current_components = self.get_components()
        current_tracks = self.get_tracks_summary()
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        filename = datetime.now().strftime('%Y%m%d_%H%M%S') + '.json'
        snapshot = {
            'timestamp': timestamp,
            'components': current_components,
            'tracks': current_tracks,
            'changes': changes,
        }
        path = os.path.join(self.diary_folder, filename)
        with open(path, 'w') as f:
            json.dump(snapshot, f, indent=2)
        print(f"Design Diary: {len(changes)} change(s) saved → {filename}")

    def OnBoardItemAdded(self, board, item):
        try:
            fp = pcbnew.Cast_to_FOOTPRINT(item)
            if fp:
                changes = [
                    f"Added component {fp.GetReference()} "
                    f"with value {fp.GetValue()}"
                ]
                self.save_snapshot(changes)
                return
        except Exception:
            pass

        try:
            trk = pcbnew.Cast_to_PCB_TRACK(item)
            if trk:
                net = trk.GetNetname()
                layer = trk.GetLayerName()
                width = pcbnew.ToMM(trk.GetWidth())
                changes = [
                    f"Added track on {layer} — "
                    f"net '{net}', width {width:.3f}mm"
                ]
                self.save_snapshot(changes)
                return
        except Exception:
            pass

    def OnBoardItemRemoved(self, board, item):
        try:
            fp = pcbnew.Cast_to_FOOTPRINT(item)
            if fp:
                changes = [f"Deleted component {fp.GetReference()}"]
                self.save_snapshot(changes)
                return
        except Exception:
            pass

        try:
            trk = pcbnew.Cast_to_PCB_TRACK(item)
            if trk:
                net = trk.GetNetname()
                layer = trk.GetLayerName()
                changes = [f"Deleted track on {layer} — net '{net}'"]
                self.save_snapshot(changes)
                return
        except Exception:
            pass

    def OnBoardItemChanged(self, board, item):
        try:
            fp = pcbnew.Cast_to_FOOTPRINT(item)
            if fp:
                last = self.get_last_snapshot()
                previous = last.get('components', {})
                ref = fp.GetReference()
                new_value = fp.GetValue()
                if ref in previous and previous[ref].get('value') != new_value:
                    changes = [
                        f"Changed value of {ref} from "
                        f"{previous[ref]['value']} to {new_value}"
                    ]
                    self.save_snapshot(changes)
                return
        except Exception:
            pass

        try:
            trk = pcbnew.Cast_to_PCB_TRACK(item)
            if trk:
                net = trk.GetNetname()
                layer = trk.GetLayerName()
                width = pcbnew.ToMM(trk.GetWidth())
                changes = [
                    f"Modified track on {layer} — "
                    f"net '{net}', new width {width:.3f}mm"
                ]
                self.save_snapshot(changes)
                return
        except Exception:
            pass