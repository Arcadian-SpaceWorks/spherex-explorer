export default function TimeSlider({count, index, onChange, label, playing = false, onTogglePlay = null, atEnd = false}) {
  const last = Math.max(0, count - 1);
  function move(next) {
    if (!Number.isFinite(next)) return;
    onChange(Math.min(last, Math.max(0, next)));
  }
  return <div className="time-slider">
    <div className="time-slider-nav">
      <button type="button" onClick={() => move(index - 1)} disabled={index <= 0} aria-label="Previous observation">Previous</button>
      <button type="button" onClick={() => move(index + 1)} disabled={index >= last} aria-label="Next observation">Next</button>
      {onTogglePlay && <button type="button" className="time-play" onClick={onTogglePlay} aria-pressed={playing}
        aria-label={playing ? 'Pause playback' : atEnd ? 'Replay observations from the start' : 'Play observations in time order'}>
        {playing ? 'Pause' : atEnd ? 'Replay' : 'Play'}</button>}
    </div>
    <input type="range" min={0} max={last} step={1} value={count ? index : 0} disabled={count <= 1}
      aria-label="Observation time slider" aria-valuemin={0} aria-valuemax={last} aria-valuenow={count ? index : 0}
      aria-valuetext={label || undefined} data-testid="time-slider"
      onChange={event => move(Number(event.target.value))}
      onKeyDown={event => {
        if (event.key === 'Home') {event.preventDefault(); move(0);}
        if (event.key === 'End') {event.preventDefault(); move(last);}
      }}/>
  </div>;
}
