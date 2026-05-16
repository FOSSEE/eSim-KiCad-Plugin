import os
import re
import json
from datetime import datetime


class SchematicTracker:

    def __init__(self, diary_folder):
        self.diary_folder = diary_folder
        os.makedirs(self.diary_folder, exist_ok=True)

    def read_schematic(self, sch_path):
        with open(sch_path, 'r', encoding='utf-8') as f:
            content = f.read()

        components = {}
        refs = re.findall(r'\(property "Reference" "([A-Z]+[0-9]+)"', content)
        for ref in refs:
            pattern = (
                r'\(property "Reference" "' + re.escape(ref) +
                r'".*?\(property "Value" "([^"]+)"'
            )
            val_match = re.search(pattern, content, re.DOTALL)
            if val_match:
                components[ref] = val_match.group(1)
        return components

    def get_last_schematic_snapshot(self):
        snapshots = sorted([
            f for f in os.listdir(self.diary_folder)
            if f.startswith('SCH_') and f.endswith('.json')
        ])
        if snapshots:
            path = os.path.join(self.diary_folder, snapshots[-1])
            with open(path, 'r') as f:
                data = json.load(f)
            return data.get('components', {})
        return {}

    def take_snapshot(self, sch_path):
        current = self.read_schematic(sch_path)
        previous = self.get_last_schematic_snapshot()

        changes = []
        for ref in current:
            if ref not in previous:
                changes.append(
                    f"Schematic: Added component {ref} with value {current[ref]}"
                )
            elif current[ref] != previous[ref]:
                changes.append(
                    f"Schematic: Changed value of {ref} from "
                    f"{previous[ref]} to {current[ref]}"
                )
        for ref in previous:
            if ref not in current:
                changes.append(f"Schematic: Deleted component {ref}")

        if not changes:
            return changes

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        filename = 'SCH_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.json'
        snapshot = {
            'timestamp': timestamp,
            'schematic_file': sch_path,
            'components': current,
            'changes': changes,
        }
        path = os.path.join(self.diary_folder, filename)
        with open(path, 'w') as f:
            json.dump(snapshot, f, indent=2)
        print(f"Design Diary: {len(changes)} schematic change(s) detected")
        return changes