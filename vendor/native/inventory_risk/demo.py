"""DEMO/SIMULATION CLI; no real API or operational write is performed."""
import argparse
import json
from pathlib import Path
from agents.inventory_risk import analyze_inventory_and_risk

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of",default="2026-09-17")
    parser.add_argument("--event")
    parser.add_argument("--output",type=Path)
    parser.add_argument("--html",type=Path,help="Read-only DEMO HTML report")
    args=parser.parse_args()
    report=analyze_inventory_and_risk({"as_of":args.as_of},args.event)
    value=json.dumps(report,ensure_ascii=False,indent=2)
    if args.html:
        from tools.report_html import render_report
        args.html.parent.mkdir(parents=True,exist_ok=True)
        args.html.write_text(render_report(report),encoding="utf-8")
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(value,encoding="utf-8")
    else:
        print(value)

if __name__=="__main__":
    main()
