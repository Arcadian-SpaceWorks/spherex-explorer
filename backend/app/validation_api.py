"""Offline validation only. No caller-provided files, URLs or eligibility assertions."""
from functools import lru_cache
import threading
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from .analysis.validation_demo import run_experiment
router = APIRouter(prefix='/api/validation', tags=['Synthetic injection validation'])
_lock = threading.Lock()

@lru_cache(maxsize=15)
def _run(experiment, seed):
    return run_experiment(experiment, seed)

@router.get('')
def validation(experiment: Literal['brightness','transient','no_change']='transient', seed: int=Query(0,ge=0,le=4)):
    with _lock:
        try:
            before = _run.cache_info().hits
            result = _run(experiment,seed)
            return {**result, 'execution': 'cached deterministic local result' if _run.cache_info().hits > before else 'computed locally for this request'}
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(422, detail=f'Validation experiment unavailable: {exc}') from exc
