import test from 'node:test';
import assert from 'node:assert/strict';
import { validCoordinates, selectedFromClick } from '../src/coordinates.js';
test('accepts poles and zero, rejects blank, nonfinite and out-of-range coordinates', () => {
  for (const pair of [[0,0],[359.99,90],[180,-90]]) assert.ok(validCoordinates(...pair));
  for (const pair of [['',0],[' ',0],[360,0],[-1,0],[0,91],[NaN,0],[0,Infinity],['x',0]]) assert.ok(!validCoordinates(...pair));
});
test('uses the official ICRS click payload and ignores drag releases', () => {
  assert.deepEqual(selectedFromClick({ra:12.3,dec:-4.5,isDragging:false}), {ra:12.3,dec:-4.5});
  assert.equal(selectedFromClick({ra:12,dec:1,isDragging:true}), null);
});
