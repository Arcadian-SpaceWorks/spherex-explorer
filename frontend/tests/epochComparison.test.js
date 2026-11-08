import assert from 'node:assert/strict';
import {previousEpoch} from '../src/compareAdapter.js';
const row=(time,band='SPHEREx-D1',collection='qr2')=>({obs_id:time,access_url:'https://example.org/'+time,observed_at_utc:time,energy_bandpassname:band,obs_collection:collection});
const a=row('2025-01-01T00:00:00Z'), b=row('2026-01-01T00:00:00Z');
assert.equal(previousEpoch([a,b],1),a);
assert.equal(previousEpoch([a,{...b,energy_bandpassname:'SPHEREx-D4'}],1),null);
assert.equal(previousEpoch([a,{...b,obs_collection:'qr3'}],1),null);
assert.equal(previousEpoch([a,row('2025-01-01T00:05:00Z')],1),null);
assert.equal(previousEpoch([a,{...b,observed_at_utc:null}],1),null);
assert.equal(previousEpoch([{...a,access_url:'https://irsa.ipac.caltech.edu/datalink?ID=spherex_qr2/a'},
                            {...b,access_url:'https://irsa.ipac.caltech.edu/datalink?ID=spherex_qr3/b'}],1),null);
