"""Suggest SPHEREx observation pairs for a time comparison of one sky point.

Ported from the original /api/pairs work (PR #1), now sharing the comparison rules of
backend/app/analysis/compare.py so suggestions and POST /api/compare can never disagree.

Suggestions only: an ACCEPT pair passes the detector, time and wavelength-at-target rules; image
overlap is checked when the pair is actually compared. It is not evidence of motion or of any new
object. SPHEREx uses linear variable filters, so pairs are judged on the wavelength measured at the
target pixel, never on the band name alone. If that wavelength cannot be read, it stays unknown.
"""
import math
from types import SimpleNamespace

from .analysis.compare import cutout_size_for_grid, validate
from .image_download import ImageError

VISIT_GAP_DAYS = 20.0   # observations further apart than this start a new visit
MAX_CANDIDATES = 12     # bounds the number of cutouts one request may download
NOTE = ('Suggestions only. ACCEPT means the detector, time and wavelength-at-target rules are met; '
        'overlap is checked when you compare the pair. It is not evidence of motion or of any new object.')


def separation_deg(ra1, dec1, ra2, dec2):
    """Great-circle distance in degrees (haversine)."""
    ra1, dec1, ra2, dec2 = map(math.radians, (ra1, dec1, ra2, dec2))
    h = (math.sin((dec2 - dec1) / 2) ** 2
         + math.cos(dec1) * math.cos(dec2) * math.sin((ra2 - ra1) / 2) ** 2)
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(h))))


def group_visits(observations, gap_days=VISIT_GAP_DAYS):
    """Split observations (any order) into visits: runs in time separated by more than gap_days."""
    rows = sorted((o for o in observations if o.get('t_min') is not None), key=lambda o: o['t_min'])
    visits = []
    for row in rows:
        if not visits or row['t_min'] - visits[-1][-1]['t_min'] > gap_days:
            visits.append([])
        visits[-1].append(row)
    return visits


def shortlist(observations, ra, dec, per_visit=2, gap_days=VISIT_GAP_DAYS, max_candidates=MAX_CANDIDATES):
    """Per visit, keep the observations whose image centre is closest to the target.

    A target near the detector centre tends to sit mid-band in wavelength, so this picks likely
    comparable images without downloading anything. It is only a heuristic; the measured
    wavelength decides afterwards. At most max_candidates are kept, earliest visits first.
    """
    picked = []
    for index, visit in enumerate(group_visits(observations, gap_days)):
        usable = [o for o in visit if o.get('access_url') and o.get('s_ra') is not None and o.get('s_dec') is not None]
        usable.sort(key=lambda o: (separation_deg(ra, dec, o['s_ra'], o['s_dec']), str(o.get('obs_id'))))
        for o in usable[:per_visit]:
            picked.append({**o, 'visit': index,
                           'center_distance_deg': round(separation_deg(ra, dec, o['s_ra'], o['s_dec']), 4)})
    return picked[:max_candidates]


def _frame(candidate):
    """The attributes validate() reads, built from a candidate (no pixels needed)."""
    detector = candidate.get('detector')
    return SimpleNamespace(obs_id=candidate.get('obs_id'), detector=detector,
                           band=f'SPHEREx-D{detector}' if detector is not None else None,
                           mjd=candidate.get('t_min'), wavelength_um=candidate.get('wavelength_um'))


def suggest_pairs(candidates, limit=10):
    """Rank candidate pairs with the shared time-comparison rules (overlap not yet measured).

    Candidates need t_min, detector, wavelength_um (None if unknown), target_status and visit.
    Candidates with errors, or whose target is not inside the image, are skipped.
    """
    usable = [c for c in candidates if c.get('target_status') == 'inside' and not c.get('error')
              and c.get('t_min') is not None]
    pairs = []
    for i in range(len(usable)):
        for j in range(i + 1, len(usable)):
            a, b = sorted((usable[i], usable[j]), key=lambda c: c['t_min'])
            check = validate(_frame(a), _frame(b), 'time', require_overlap=False)
            if any(reason.code == 'too_close_in_time' for reason in check.reasons):
                continue  # Not a time comparison at all; not worth listing.
            pairs.append({
                'a': {key: a.get(key) for key in ('obs_id', 'image_id', 'access_url', 'observed_at_utc', 'wavelength_um', 'visit')},
                'b': {key: b.get(key) for key in ('obs_id', 'image_id', 'access_url', 'observed_at_utc', 'wavelength_um', 'visit')},
                'dt_days': round(b['t_min'] - a['t_min'], 4),
                'delta_wavelength_um': None if check.wavelength_delta_um is None else round(check.wavelength_delta_um, 4),
                'baseline': 'same_visit' if a.get('visit') == b.get('visit') else 'between_visits',
                'decision': check.decision,
                'difference_expected': check.decision == 'ACCEPT',
                'reasons': [reason.to_dict() for reason in check.reasons],
            })
    rank = {'ACCEPT': 0, 'WARN': 1, 'REJECT': 2}
    pairs.sort(key=lambda p: (rank[p['decision']],
                              math.inf if p['delta_wavelength_um'] is None else p['delta_wavelength_um'],
                              -p['dt_days']))
    return pairs[:limit]


def build_pair_report(data_client, service, ra, dec, band='SPHEREx-D1', per_visit=2, size_deg=0.3):
    """Search one band, shortlist per visit, fetch cutouts (cached), read the target wavelength, rank pairs.

    Cutouts use the size /api/compare needs for a size_deg grid, so suggested pairs can be compared
    straight away. Raises IRSAUnavailable if the search fails; cutout failures are reported per candidate.
    """
    cutout_deg = round(cutout_size_for_grid(size_deg), 4)
    result = data_client.observations(ra, dec, band=band)
    observations = result['observations']
    visits = group_visits(observations)
    candidates = []
    for row in shortlist(observations, ra, dec, per_visit):
        item = {key: row.get(key) for key in ('obs_id', 'energy_bandpassname', 'observed_at_utc', 't_min',
                                              'access_url', 'visit', 'center_distance_deg')}
        try:
            meta = service.prepare(row['access_url'], ra, dec, cutout_deg)
            target = meta.get('target') or {}
            spectral = target.get('spectral')
            item.update(image_id=meta['image_id'], preview_url=meta['preview_url'], detector=meta.get('detector'),
                        target_status=target.get('status'), cache_hit=meta.get('cache_hit'),
                        wavelength_um=spectral['wavelength_um'] if spectral else None,
                        bandwidth_um=spectral['bandwidth_um'] if spectral else None)
        except ImageError as exc:
            item.update(error={'code': exc.code, 'status': exc.status, 'message': str(exc)})
        candidates.append(item)
    return {
        'status': 'live', 'ra': ra, 'dec': dec, 'band': band, 'source': result.get('source'),
        'observations_considered': len(observations), 'truncated': result.get('truncated', False),
        'visits': [{'visit': i, 'first_utc': v[0].get('observed_at_utc'), 'last_utc': v[-1].get('observed_at_utc'),
                    'observations': len(v)} for i, v in enumerate(visits)],
        'candidates': candidates,
        'pairs': suggest_pairs(candidates),
        'rules': {'source': 'backend.app.analysis.compare.validate (time mode, overlap checked on compare)',
                  'visit_gap_days': VISIT_GAP_DAYS, 'per_visit': per_visit, 'max_candidates': MAX_CANDIDATES,
                  'size_deg': size_deg, 'cutout_deg': cutout_deg},
        'note': NOTE,
    }
