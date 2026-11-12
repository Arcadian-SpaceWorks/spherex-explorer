"""What a set of forced-photometry points says: seasons, a binned spectrum, band strengths and
changes between seasons. Everything is measured from the points; nothing is fitted to a template.

Thresholds are conservative on purpose. A band is reported as detected only above 5 sigma AND an
8 % strength floor, because single-aperture photometry on undersampled 6 arcsec pixels has
percent-level systematics that the formal uncertainties do not contain.
"""
import math

import numpy as np

from .archive import mjd_to_utc

EPOCH_GAP_DAYS = 20
# Approximate resolving power of the six detector bands (SPHEREx instrument design values).
RESOLVING_POWER = {1: 41, 2: 41, 3: 41, 4: 35, 5: 110, 6: 130}
MIN_SIGMA, MIN_STRENGTH = 5.0, 0.08
MIN_CORE_POINTS, MIN_SIDE_POINTS, MIN_SIDES_TOTAL = 2, 1, 3
VARIABILITY_FLOOR = 0.08
MIXED_CHANGE = 0.5

# Wavelength windows in micrometres, observed frame. `left`/`right` are the continuum windows.
FEATURES = (
    dict(id='h2o_ice', label='Water ice', formula='H2O', center=3.05, core=(2.90, 3.20), left=(2.45, 2.65),
         right=(3.65, 3.95), kinds=('absorption',), group='Ices',
         meaning='Frozen water on dust grains in cold, dense clouds and discs: the reservoir that later supplies planets and comets.',
         caveat='Cool stars (M giants, Miras) also absorb here through water vapour in their atmospheres, and a dusty galaxy dips here where starlight gives way to hot dust; ice needs a source behind or inside a dark cloud.'),
    dict(id='co2', label='Carbon dioxide', formula='CO2', center=4.27, core=(4.22, 4.31), left=(4.06, 4.18),
         right=(4.35, 4.42), kinds=('absorption', 'emission'), group='Ices',
         meaning='In absorption: CO2 ice on dust grains. In emission: CO2 gas released by a comet. Earth\'s atmosphere blocks this band, so it is only measurable from space.',
         caveat='A broad dip across 4.3 to 5 µm in cool stars is photospheric CO, not CO2 ice.'),
    dict(id='co', label='Carbon monoxide ice', formula='CO', center=4.67, core=(4.645, 4.70), left=(4.55, 4.62),
         right=(4.73, 4.80), kinds=('absorption',), group='Ices',
         meaning='CO ice, which only freezes onto dust below about 20 K: a thermometer for the coldest cloud cores.',
         caveat='Cool stars show CO gas absorption over this whole region; a narrow band on a smooth continuum is needed for ice.'),
    dict(id='co_gas', label='Carbon monoxide gas', formula='CO', center=4.67, core=(4.60, 4.75), left=(4.36, 4.56),
         right=(4.82, 4.96), kinds=('emission',), group='Comet gas',
         meaning='Fluorescence of CO gas from a comet. CO sublimates far from the Sun, so it reveals material that was never heated.',
         caveat='Only meaningful for comets.'),
    dict(id='h2o_gas', label='Water vapour', formula='H2O', center=2.68, core=(2.62, 2.75), left=(2.47, 2.56),
         right=(2.84, 2.94), kinds=('emission',), group='Comet gas',
         meaning='Fluorescence of water molecules sublimating from a comet nucleus.',
         caveat='Only meaningful for comets. SPHEREx channels are broad here (about 0.08 µm).'),
    dict(id='pah', label='PAH 3.3 µm', formula='PAH', center=3.29, core=(3.24, 3.34), left=(3.12, 3.20),
         right=(3.55, 3.68), kinds=('emission',), group='Dust and gas',
         meaning='Polycyclic aromatic hydrocarbons: large carbon molecules lit up by ultraviolet light from young stars. A tracer of star formation.',
         caveat='The band is narrower than a SPHEREx channel here, so its strength is diluted.'),
    dict(id='br_alpha', label='Hydrogen Brackett α', formula='H I', center=4.052, core=(4.03, 4.075), left=(3.95, 4.01),
         right=(4.095, 4.16), kinds=('emission',), group='Dust and gas',
         meaning='Ionised hydrogen recombining: gas heated by hot stars or accretion.', caveat=''),
    dict(id='pa_alpha', label='Hydrogen Paschen α', formula='H I', center=1.875, core=(1.85, 1.90), left=(1.78, 1.83),
         right=(1.92, 1.97), kinds=('emission',), group='Dust and gas',
         meaning='The strongest infrared hydrogen line, unobservable from the ground because of atmospheric water.', caveat=''),
    dict(id='pa_beta', label='Hydrogen Paschen β', formula='H I', center=1.282, core=(1.262, 1.302), left=(1.215, 1.25),
         right=(1.315, 1.35), kinds=('emission',), group='Dust and gas',
         meaning='Ionised hydrogen recombining.', caveat=''),
    dict(id='he_i', label='Helium 1.083 µm', formula='He I', center=1.083, core=(1.065, 1.105), left=(1.02, 1.055),
         right=(1.115, 1.15), kinds=('emission',), group='Dust and gas',
         meaning='Helium excited by hot stars; blended with hydrogen Paschen γ at this resolution.',
         caveat='The band sits where two SPHEREx detectors meet; a small calibration step is possible.'),
    dict(id='s_iii', label='Sulphur [S III] 0.953 µm', formula='[S III]', center=0.953, core=(0.938, 0.968), left=(0.865, 0.895),
         right=(0.975, 1.0), kinds=('emission',), group='Dust and gas',
         meaning='Doubly ionised sulphur in gas photoionised by hot stars (H II regions, planetary nebulae).', caveat=''),
)


def robust_scatter(values):
    values = np.asarray(values, dtype=float)
    return float(1.4826 * np.median(np.abs(values - np.median(values)))) if values.size else 0.0


def usable(points):
    return [point for point in points if point.get('status') == 'ok' and point.get('wavelength_um') is not None]


def assign_epochs(points):
    """Label each point with a season index (runs of exposures separated by more than 20 days)."""
    dated = sorted((point for point in points if point.get('mjd') is not None), key=lambda point: point['mjd'])
    seasons, previous = [], None
    for point in dated:
        if previous is None or point['mjd'] - previous > EPOCH_GAP_DAYS:
            seasons.append({'index': len(seasons), 'start_mjd': point['mjd'], 'end_mjd': point['mjd'], 'exposures': 0, 'measured': 0})
        season = seasons[-1]
        point['epoch'] = season['index']
        season['end_mjd'] = previous = point['mjd']
        season['exposures'] += 1
        season['measured'] += point.get('status') == 'ok'
    for season in seasons:
        season['start_utc'], season['end_utc'] = mjd_to_utc(season['start_mjd']), mjd_to_utc(season['end_mjd'])
    return seasons


def binned(points):
    """Inverse-variance means in bins of half a resolution element, per detector."""
    result = []
    for detector in sorted({point['detector'] for point in points if point.get('detector') in RESOLVING_POWER}):
        items = sorted((point for point in points if point['detector'] == detector), key=lambda point: point['wavelength_um'])
        group = []
        for point in items + [None]:
            if point is not None and (not group or point['wavelength_um'] - group[0]['wavelength_um']
                                      <= group[0]['wavelength_um'] / RESOLVING_POWER[detector] / 2):
                group.append(point)
                continue
            if group:
                weights = np.array([1 / item['flux_err_mjy'] ** 2 for item in group])
                fluxes = np.array([item['flux_mjy'] for item in group])
                mean = float(np.sum(weights * fluxes) / weights.sum())
                formal = float(1 / math.sqrt(weights.sum()))
                spread = float(np.std(fluxes, ddof=1) / math.sqrt(len(group))) if len(group) > 2 else 0.0
                result.append({'wavelength_um': float(np.sum(weights * [item['wavelength_um'] for item in group]) / weights.sum()),
                               'flux_mjy': mean, 'flux_err_mjy': max(formal, spread), 'n': len(group), 'detector': detector})
            group = [point] if point is not None else []
    return result


def _window(points, low, high):
    return [point for point in points if low <= point['wavelength_um'] <= high]


def _centre(points):
    return (float(np.median([point['wavelength_um'] for point in points])),
            float(np.median([point['flux_mjy'] for point in points])))


def measure_feature(points, feature):
    """Strength of one band relative to a straight continuum through its two side windows.

    Medians are used throughout so that one contaminated exposure (a cosmic ray, or a background
    star under a moving target) cannot create or hide a band.
    """
    base = {'id': feature['id'], 'status': 'not_measurable'}
    core, left, right = (_window(points, *feature[name]) for name in ('core', 'left', 'right'))
    base['points'] = {'core': len(core), 'left': len(left), 'right': len(right)}
    if len(core) < MIN_CORE_POINTS or min(len(left), len(right)) < MIN_SIDE_POINTS or len(left) + len(right) < MIN_SIDES_TOTAL:
        return base
    (left_x, left_y), (right_x, right_y) = _centre(left), _centre(right)
    slope = (right_y - left_y) / (right_x - left_x)

    def continuum_at(wavelength):
        return left_y + slope * (wavelength - left_x)

    sides = left + right
    residuals = [point['flux_mjy'] - continuum_at(point['wavelength_um']) for point in sides]
    noise = max(robust_scatter(residuals), float(np.median([point['flux_err_mjy'] for point in core + sides])))
    if noise <= 0:
        return base
    offsets = np.array([point['flux_mjy'] - continuum_at(point['wavelength_um']) for point in core])
    difference = float(np.median(offsets))
    # 1.2533: a median is that much noisier than a mean for Gaussian errors.
    difference_err = 1.2533 * noise * math.sqrt(1 / len(core) + 1 / len(sides))
    level = float(np.median([continuum_at(point['wavelength_um']) for point in core]))
    significance = difference / difference_err
    result = {**base, 'continuum_mjy': level, 'difference_mjy': difference, 'difference_err_mjy': difference_err,
              'significance': significance, 'status': 'not_detected', 'kind': None, 'strength': None}
    well_measured_continuum = level > 3 * noise * math.sqrt(1 / len(sides))
    if well_measured_continuum:
        ratio = 1 + difference / level
        result.update(strength=abs(difference) / level, ratio=ratio,
                      equivalent_width_um=(1 - ratio) * (feature['core'][1] - feature['core'][0]))
        # A band that removes nearly all the light bottoms out in the noise: only a lower limit on
        # the optical depth can be stated, from the smallest ratio the noise allows to be measured.
        floor = max(3 * difference_err / level, 0.02)
        if ratio < floor:
            result.update(optical_depth=-math.log(floor), optical_depth_is_lower_limit=True)
        elif ratio < 1:
            result.update(optical_depth=-math.log(ratio), optical_depth_is_lower_limit=False)
    kind = 'emission' if difference > 0 else 'absorption'
    # Every core point must agree when there are few of them; three quarters otherwise.
    agreeing = float(np.mean(np.sign(offsets) * np.sign(difference) * (np.abs(offsets) > noise) > 0))
    consistent = agreeing >= (1.0 if len(core) < 4 else 0.75)
    strong = result['strength'] is None and kind == 'emission' or (result['strength'] or 0) >= MIN_STRENGTH
    # The band must stand out from BOTH side windows, not only from the line between them. Otherwise
    # an unrelated line in one side window (for example a redshifted quasar line) fakes a band.
    core_level = float(np.median([point['flux_mjy'] for point in core]))
    beyond_both = core_level > max(left_y, right_y) if kind == 'emission' else core_level < min(left_y, right_y)
    result['stands_out_from_both_sides'] = bool(beyond_both)
    if (kind in feature['kinds'] and abs(significance) >= MIN_SIGMA and strong and consistent and beyond_both
            and (kind == 'emission' or well_measured_continuum)):
        result.update(status='detected', kind=kind)
    return result


def features_for(moving):
    """A comet is tested for gas emission only: its sunlight-plus-thermal continuum dips near 3 µm
    by itself, which a straight-continuum test would misread as ice. Fixed sources are not tested
    for comet gas."""
    if moving:
        return [{**feature, 'kinds': ('emission',)} for feature in FEATURES if feature['group'] == 'Comet gas' or feature['id'] == 'co2']
    return [feature for feature in FEATURES if feature['group'] != 'Comet gas']


def measure_features(points, moving=False):
    return [measure_feature(points, feature) for feature in features_for(moving)]


def season_ratio(members, reference, detector=None):
    """Median brightness of `members` relative to `reference` points at matching wavelengths.

    SPHEREx never repeats exactly the same wavelength, so each point is compared with the reference
    season's points in the same detector within half a resolution element of its wavelength.
    """
    logs = []
    for point in members:
        if detector is not None and point['detector'] != detector:
            continue
        reach = point['wavelength_um'] / RESOLVING_POWER.get(point['detector'], 41) / 2
        near = [other for other in reference if other['detector'] == point['detector']
                and abs(other['wavelength_um'] - point['wavelength_um']) <= reach]
        if not near:
            continue
        level = float(np.mean([other['flux_mjy'] for other in near]))
        noise = float(np.mean([other['flux_err_mjy'] for other in near])) / math.sqrt(len(near))
        if level > 3 * noise and point['flux_mjy'] > 3 * point['flux_err_mjy']:
            logs.append(math.log(point['flux_mjy'] / level))
    return np.array(logs)


def variability(points, seasons):
    """Brightness of each season relative to the best-observed season, overall and per detector."""
    result = {'status': 'not_measurable', 'seasons': [], 'floor': VARIABILITY_FLOOR, 'reference': None}
    by_season = {season['index']: [point for point in points if point.get('epoch') == season['index']] for season in seasons}
    if len(seasons) < 2 or not points:
        return result
    reference_index = max(by_season, key=lambda index: len(by_season[index]))
    reference = by_season[reference_index]
    result['reference'] = reference_index
    strongest = None
    for season in seasons:
        entry = {'index': season['index'], 'start_utc': season['start_utc'], 'end_utc': season['end_utc'], 'bands': []}
        if season['index'] == reference_index:
            if len(reference) >= 8:
                result['seasons'].append({**entry, 'relative_flux': 1.0, 'relative_flux_err': 0.0, 'n': len(reference), 'reference': True})
            continue
        members = by_season[season['index']]
        for detector in [None] + sorted({point['detector'] for point in members}):
            logs = season_ratio(members, reference, detector)
            if logs.size < (8 if detector is None else 4):
                continue
            centre = float(np.median(logs))
            spread = max(robust_scatter(logs), 0.01) * 1.2533 / math.sqrt(logs.size)
            summary = {'relative_flux': math.exp(centre), 'relative_flux_err': math.exp(centre) * spread, 'n': int(logs.size)}
            if detector is None:
                entry.update(summary, log_significance=abs(centre) / spread)
            else:
                entry['bands'].append({'detector': detector, **summary})
        if 'relative_flux' in entry:
            result['seasons'].append(entry)
            if strongest is None or abs(math.log(entry['relative_flux'])) > abs(math.log(strongest['relative_flux'])):
                strongest = entry
    if strongest is None:
        return result
    change = abs(strongest['relative_flux'] - 1)
    result.update(status='variable' if change >= VARIABILITY_FLOOR and strongest['log_significance'] >= MIN_SIGMA else 'steady',
                  amplitude=change, significance=strongest['log_significance'], strongest=strongest['index'])
    return result


def scaled_to_reference(points, change):
    """Copies of the points with each season divided by its measured brightness relative to the
    reference season (the per-detector value where one was measured, else the overall value)."""
    factors = {}
    for season in change['seasons']:
        if not season.get('reference'):
            factors[(season['index'], None)] = season['relative_flux']
            factors.update({(season['index'], band['detector']): band['relative_flux'] for band in season['bands']})
    scaled = []
    for point in points:
        factor = factors.get((point.get('epoch'), point['detector']), factors.get((point.get('epoch'), None), 1.0))
        scaled.append({**point, 'flux_mjy': point['flux_mjy'] / factor, 'flux_err_mjy': point['flux_err_mjy'] / factor})
    return scaled


def summarise(points, moving=False):
    """Full analysis of the points measured so far. Mutates points only to add `epoch`."""
    seasons = assign_epochs(points)
    good = usable(points)
    counts = {}
    for point in points:
        counts[point.get('status', 'error')] = counts.get(point.get('status', 'error'), 0) + 1
    change = variability(good, seasons)
    # A source that changed between seasons has steps in its combined spectrum that are not bands.
    # Moderate changes: each season is scaled to the reference season (per detector) before the
    # bands are measured. Large changes (the spectrum itself may differ): seasons are kept apart.
    varied = change['status'] == 'variable'
    mixed = varied and change['amplitude'] >= MIXED_CHANGE
    combined = scaled_to_reference(good, change) if varied and not mixed else good
    result = {'counts': counts, 'seasons': seasons, 'binned': [] if mixed else binned(combined),
              'features': [] if mixed else measure_features(combined, moving), 'mixed_seasons': mixed,
              'seasons_scaled': varied and not mixed, 'features_by_season': [], 'variability': change}
    if len(seasons) > 1:
        for season in seasons:
            members = [point for point in good if point.get('epoch') == season['index']]
            result['features_by_season'].append({'index': season['index'], 'features': measure_features(members, moving)})
    if good:
        snr = np.array([point['flux_mjy'] / point['flux_err_mjy'] for point in good])
        result['median_snr'] = float(np.median(snr))
        result['median_flux_mjy'] = float(np.median([point['flux_mjy'] for point in good]))
        result['coverage_um'] = [min(point['wavelength_um'] for point in good), max(point['wavelength_um'] for point in good)]
    return result


def feature_catalogue():
    return [{key: (list(value) if isinstance(value, tuple) else value) for key, value in feature.items()} for feature in FEATURES]
