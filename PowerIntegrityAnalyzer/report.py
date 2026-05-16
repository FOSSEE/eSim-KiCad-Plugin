import os
import datetime

def generate_report(violations, board_path):
    """
    violations : list of violation dicts from checkers
    board_path : full path to the .kicad_pcb file
    """
    
    # save report next to the .kicad_pcb file
    report_dir = os.path.dirname(board_path)
    report_path = os.path.join(report_dir, "power_integrity_report.html")
    
    reds   = [v for v in violations if v.get("severity") == "red"]
    ambers = [v for v in violations if v.get("severity") == "amber"]
    passed = [v for v in violations if v.get("severity") == "ok"]
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    rows = ""
    for v in violations:
        sev = v.get("severity", "ok")
        if sev == "red":
            bg = "#fee2e2"
            badge = "<span style='color:#dc2626;font-weight:bold'>● ERROR</span>"
        elif sev == "amber":
            bg = "#fef9c3"
            badge = "<span style='color:#d97706;font-weight:bold'>● WARN</span>"
        else:
            bg = "#dcfce7"
            badge = "<span style='color:#16a34a;font-weight:bold'>● OK</span>"
        
        rows += f"""
        <tr style='background:{bg}'>
            <td>{v.get('net', '-')}</td>
            <td>{v.get('type', '-')}</td>
            <td>{badge}</td>
            <td>{v.get('message', '-')}</td>
        </tr>"""
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset='utf-8'>
    <title>Power Integrity Report</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 40px;
            background: #f8fafc;
            color: #1e293b;
        }}
        h1 {{ color: #1e293b; margin-bottom: 4px; }}
        .timestamp {{ color: #64748b; font-size: 0.9em; margin-bottom: 24px; }}
        
        .summary {{
            display: flex;
            gap: 16px;
            margin-bottom: 28px;
        }}
        .card {{
            padding: 16px 28px;
            border-radius: 8px;
            font-size: 1.4em;
            font-weight: bold;
            text-align: center;
            min-width: 100px;
        }}
        .card span {{ display: block; font-size: 0.5em; font-weight: normal; margin-top: 4px; }}
        .card-red   {{ background: #fee2e2; color: #dc2626; }}
        .card-amber {{ background: #fef9c3; color: #d97706; }}
        .card-green {{ background: #dcfce7; color: #16a34a; }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 1px 4px rgba(0,0,0,0.08);
        }}
        th {{
            background: #1e293b;
            color: white;
            padding: 12px 16px;
            text-align: left;
            font-size: 0.9em;
            letter-spacing: 0.05em;
        }}
        td {{
            padding: 10px 16px;
            border-bottom: 1px solid #e2e8f0;
            font-size: 0.95em;
        }}
        tr:last-child td {{ border-bottom: none; }}
    </style>
</head>
<body>
    <h1> Power Integrity Report</h1>
    <div class='timestamp'>Generated: {timestamp} &nbsp;|&nbsp; Board: {os.path.basename(board_path)}</div>
    
    <div class='summary'>
        <div class='card card-red'>{len(reds)}<span>Errors</span></div>
        <div class='card card-amber'>{len(ambers)}<span>Warnings</span></div>
        <div class='card card-green'>{len(passed)}<span>Passed</span></div>
    </div>
    
    <table>
        <thead>
            <tr>
                <th>Net</th>
                <th>Check Type</th>
                <th>Status</th>
                <th>Message</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
</body>
</html>"""
    
    with open(report_path, "w") as f:
        f.write(html)
    
    return report_path