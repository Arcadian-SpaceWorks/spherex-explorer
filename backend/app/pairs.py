"""Suggest SPHEREx observation pairs for a time comparison of one sky point.

Suggestions only: a pair marked ACCEPT is suitable for blinking and a difference image. It is
not evidence of motion or of any new object. SPHEREx uses linear variable filters, so the same
detector (band) sees a target at a different wavelength depending on where it lands; pairs are
therefore judged on the wavelength measured at the target, not on the band name alone.
"""
import math

from .image_download import ImageError
from .irsa import IRSAUnavailable  # noqa: F401  (re-exported for callers)

VISIT_GAP_DAYS = 20.0      # observations further apart than this start a new visit
MAX_DELTA_WL_UM = 0.02     # target wavelengths closer than this count as comparable
MIN_DT_HOURS = 1.0         # pairs closer in time than this are not a time comparison
NOTE = ('Suggestions only. ACCEPT means the two cutouts are suitable for blinking and a difference '
        'image; it is not evidence of motion or of any new object.')


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


def shortlist(observations, ra, dec, per_visit=2, gap_days=VISIT_GAP_DAYS):
    """Per visit, keep the observations whose image centre is closest to the target.

    A target near the detector centre should sit near the middle of the band in wavelength, so
    this tends to pick comparable images without downloading anything. It is only a heuristic;
    the measured wavelength decides afterwards.
    """
    picked = []
    for index, visit in enumerate(group_visits(observations, gap_days)):
        usable = [o for o in visit if o.get('access_url') and o.get('s_ra') is not None and o.get('s_dec') is not None]
        usable.sort(key=lambda o: (separation_deg(ra, dec, o['s_ra'], o['s_dec']), str(o.get('obs_id'))))
        for o in usable[:per_visit]:
            picked.append({**o, 'visit': index,
                           'center_distance_deg': round(separation_deg(ra, dec, o['s_ra'], o['s_dec']), 4)})
    return picked


def suggest_pairs(candidates, max_dwl=MAX_DELTA_WL_UM, min_dt_hours=MIN_DT_HOURS, limit=10):
    """Rank candidate pairs. Candidates need t_min, visit, target_status, wavelength_um, image_id."""
    usable = [c for c in candidates if c.get('target_status') == 'inside' and not c.get('error')
              and c.get('t_min') is not None]
    pairs = []
    for i in range(len(usable)):
        for j in range(i + 1, len(usable)):
            a, b = sorted((usable[i], usable[j]), key=lambda c: c['t_min'])
            dt_days = b['t_min'] - a['t_min']
            if dt_days * 24 < min_dt_hours:
                continue
            wa, wb = a.get('wavelength_um'), b.get('wavelength_um')
            if wa is None or wb is None:
                dwl, decision = None, 'WARN'
                reasons = [{'code': 'wavelength_unknown',
                            'message': 'The wavelength at the target could not be read for one image, '
                                       'so brightness differences may not be real. Blink only.'}]
            else:
                dwl = abs(wb - wa)
                if dwl <= max_dwl:
                    decision, reasons = 'ACCEPT', []
                else:
                    decision = 'WARN'
                    reasons = [{'code': 'wavelength_mismatch',
                                'message': f'The target is seen at {wa:.3f} and {wb:.3f} micron (difference '
                                           f'{dwl:.3f} > {max_dwl} micron). Brightness changes may come from the '
                                           f'wavelength, not the sky. Blink only, no difference image.'}]
            pairs.append({
                'a': {key: a.get(key) for key in ('obs_id', 'image_id', 'observed_at_utc', 'wavelength_um', 'visit')},
                'b': {key: b.get(key) for key in ('obs_id', 'image_id', 'observed_at_utc', 'wavelength_um', 'visit')},
                'dt_days': round(dt_days, 4),
                'delta_wavelength_um': None if dwl is None else round(dwl, 4),
                'baseline': 'same_visit' if a.get('visit') == b.get('visit') else 'between_visits',
                'decision': decision,
                'difference_allowed': decision == 'ACCEPT',
                'reasons': reasons,
            })
    pairs.sort(key=lambda p: (p['decision'] != 'ACCEPT',
                              math.inf if p['delta_wavelength_um'] is None else p['delta_wavelength_um'],
                              -p['dt_days']))
    return pairs[:limit]


def build_pair_report(data_client, service, ra, dec, band='SPHEREx-D1', per_visit=2, cutout_deg=0.3):
    """Search one band, shortlist per visit, fetch cutouts (cached), measure wavelength, rank pairs.

    Raises IRSAUnavailable if the search fails. Individual cutout failures are reported per candidate.
    """
    result = data_client.observations(ra, dec, band)
    observations = result['observations']
    visits = group_visits(observations)
    candidates = []
    for row in shortlist(observations, ra, dec, per_visit):
        item = {key: row.get(key) for key in ('obs_id', 'energy_bandpassname', 'observed_at_utc', 't_min',
                                              'visit', 'center_distance_deg')}
        try:
            meta = service.prepare(row['access_url'], ra, dec, cutout_deg)
            target = meta.get('target') or {}
            spectral = target.get('spectral')
            source = 'target_pixel' if spectral else None
            if not spectral and (meta.get('center') or {}).get('spectral'):
                spectral, source = meta['center']['spectral'], 'cutout_center'
            item.update(image_id=meta['image_id'], preview_url=meta['preview_url'],
                        target_status=target.get('status'), cache_hit=meta.get('cache_hit'),
                        wavelength_um=spectral['wavelength_um'] if spectral else None,
                        wavelength_source=source)
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
        'rules': {'max_delta_wavelength_um': MAX_DELTA_WL_UM, 'min_separation_hours': MIN_DT_HOURS,
                  'visit_gap_days': VISIT_GAP_DAYS, 'per_visit': per_visit, 'cutout_deg': cutout_deg},
        'note': NOTE,
    }
