"""No network: scientific selection and per-frame provenance regressions."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from astropy.table import Table
from scripts.acquire_demo import selected_rows, frame_position
from scripts.discover_demo import read_table, summary
from backend.app.demo import Manifest


def test_selection_never_mixes_releases_or_detectors_and_keeps_endpoints():
    table=Table(rows=[(f'id{i}',float(i),'spherex_qr2' if i<12 else 'spherex_qr3',f'SPHEREx-D{2 if i%2==0 else 5}',f'https://example/{i}') for i in range(20)],names=['obs_id','t_min','obs_collection','energy_bandpassname','access_url'])
    rows=selected_rows(table,2)
    assert len(rows)==6
    assert [float(r['t_min']) for r in rows]==[0,2,4,6,8,10]
    assert all(r['obs_collection']=='spherex_qr2' and r['energy_bandpassname']=='SPHEREx-D2' for r in rows)


def test_comet_positions_are_per_exposure_not_constant():
    assert frame_position('3i-atlas',{'comet_ra':250.,'comet_dec':-17.})==(250.,-17.)
    assert frame_position('3i-atlas',{'comet_ra':151.,'comet_dec':6.})==(151.,6.)
    with pytest.raises(KeyError): frame_position('3i-atlas',{})


def test_truncated_metadata_never_becomes_a_complete_count(tmp_path):
    p=tmp_path/'bad.vot'
    p.write_text('<VOTABLE><RESOURCE><INFO name="QUERY_STATUS" value="OVERFLOW"/></RESOURCE></VOTABLE>')
    with pytest.raises(ValueError,match='truncated'): read_table(p)


def test_real_comet_discovery_has_actual_epochs_and_positions():
    table=read_table(Path(__file__).resolve().parents[2]/'demo/discovery/3i-atlas.vot')
    audit=summary(table)
    assert audit['records']==259
    assert audit['exposure_epochs']==167
    assert audit['baseline_days']>130
    assert all(frame_position('3i-atlas',r)[0]>=0 for r in table)


def test_new_acquisition_rejects_release_or_position_mismatch():
    bundle=Path(__file__).resolve().parents[2]/'frontend/public/demo/manifest.json'
    data=json.loads(bundle.read_text())
    # Adapt a real existing record for structural validation only; no image mutation.
    row=data['targets'][0]['observations'][0]
    from urllib.parse import urlsplit,parse_qs
    parts=urlsplit(row['source_url']);ra,dec=map(float,parse_qs(parts.query)['center'][0].split(','))
    row['acquisition']=dict(mission='SPHEREx',data_release='spherex_qr2',calibration=parts.path.split('/')[-3],ra=ra,dec=dec,
        position_source='https://irsa.ipac.caltech.edu/',position_mode='fixed-sky-region',position_note='test validation',discovery_sha256='0'*64,archive_em_min_m=1e-6,archive_em_max_m=2e-6)
    Manifest.model_validate(data)
    bad=deepcopy(data);bad['targets'][0]['observations'][0]['acquisition']['data_release']='spherex_qr3'
    with pytest.raises(ValueError,match='Release'): Manifest.model_validate(bad)
    bad=deepcopy(data);bad['targets'][0]['observations'][0]['acquisition']['ra']+=1
    with pytest.raises(ValueError,match='position'): Manifest.model_validate(bad)
