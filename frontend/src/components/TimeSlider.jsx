export default function TimeSlider({count, index, onChange, label, isPlaying = false, onTogglePlay}) {
  const last = Math.max(0, count - 1);
  function move(next) {
    if (!Number.isFinite(next)) return;
    onChange(Math.min(last, Math.max(0, next)));
  }
  return <div className="time-slider">
    <div className="time-slider-nav">
      {onTogglePlay && (
        <button
          type="button"
          data-testid="time-slider-play"
          className={`play-btn ${isPlaying ? 'playing' : ''}`}
          onClick={onTogglePlay}
          disabled={count <= 1}
          aria-label={isPlaying ? 'Pause observation playback' : 'Play observation playback'}
        >
          {isPlaying ? '⏸ Pause' : '▶ Play'}
        </button>
      )}
      <button type="button" onClick={() => move(index - 1)} disabled={index <= 0} aria-label="Previous observation">◀ Previous</button>
      <button type="button" onClick={() => move(index + 1)} disabled={index >= last} aria-label="Next observation">Next ▶</button>
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
