// How far an image's centre may be from the selected target. A SPHEREx detector image is about
// 3.5° wide, so "anywhere" matches images whose edge just touches the target (centres up to ~2.5° away).
// Values must stay within OFFSET_MIN_DEG..OFFSET_MAX_DEG in backend/app/irsa.py.
export const OFFSET_OPTIONS = [
  {value: '0.25', label: 'Within 0.25° of target (fewest images)'},
  {value: '0.5', label: 'Within 0.5° of target'},
  {value: '1', label: 'Within 1° of target'},
  {value: '2', label: 'Within 2° of target'},
  {value: '', label: 'Anywhere in the image (most images)'},
];
export const DEFAULT_OFFSET = '0.5';

export function offsetLabel(maxOffsetDeg) {
  return maxOffsetDeg == null ? 'image centres at any distance' : `image centres within ${Number(maxOffsetDeg)}° of the target`;
}

export default function CentreOffsetFilter({value, onChange}) {
  return <div className="wavelength-filter">
    <label htmlFor="centre-offset">Image centre <span>closer = fewer images</span></label>
    <select id="centre-offset" value={value} onChange={event => onChange(event.target.value)}>
      {OFFSET_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>
    <small>Only images centred near your point are loaded, so the target sits well inside each image instead of at its edge.</small>
  </div>;
}
