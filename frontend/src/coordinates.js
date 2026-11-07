export function validCoordinates(ra, dec) {
  return String(ra).trim() !== '' && String(dec).trim() !== '' &&
    Number.isFinite(Number(ra)) && Number.isFinite(Number(dec)) &&
    Number(ra) >= 0 && Number(ra) < 360 && Number(dec) >= -90 && Number(dec) <= 90;
}
export function selectedFromClick(event) {
  if (event.isDragging || !validCoordinates(event.ra, event.dec)) return null;
  return {ra: event.ra, dec: event.dec};
}
