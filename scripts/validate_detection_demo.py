"""Reproduce local engineering experiments; prints metrics, never downloads or writes FITS.
Run from repository root: .venv/bin/python scripts/validate_detection_demo.py
"""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.app.analysis.validation_demo import run_experiment

if __name__=='__main__':
    for kind in ('brightness','transient','no_change'):
        for seed in range(5):
            result=run_experiment(kind,seed)
            print(json.dumps({k:v for k,v in result.items() if k not in ('previews','detection')},allow_nan=False))
