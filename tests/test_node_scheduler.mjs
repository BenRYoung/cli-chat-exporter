import assert from 'node:assert/strict';
import {
  defaultConfig,
  parseInterval,
  scheduleSlots,
  nextRunAfter,
} from '../lib/cce/schedule.js';

assert.equal(defaultConfig.schedule.earliest, '00:00');
assert.equal(defaultConfig.schedule.latest, '23:00');
assert.equal(defaultConfig.schedule.interval, '1h');
assert.equal(parseInterval('15m'), 15);
assert.equal(parseInterval('2h'), 120);

assert.deepEqual(scheduleSlots('08:00', '12:00', '2h'), [
  '08:00',
  '10:00',
  '12:00',
]);

assert.deepEqual(scheduleSlots('21:00', '02:00', '1h'), [
  '21:00',
  '22:00',
  '23:00',
  '00:00',
  '01:00',
  '02:00',
]);

const base = new Date('2026-05-11T07:30:00+08:00');
assert.equal(
  nextRunAfter(base, { earliest: '08:00', latest: '10:00', interval: '1h' }).toISOString(),
  new Date('2026-05-11T08:00:00+08:00').toISOString(),
);

const afterWindow = new Date('2026-05-11T11:00:00+08:00');
assert.equal(
  nextRunAfter(afterWindow, { earliest: '08:00', latest: '10:00', interval: '1h' }).toISOString(),
  new Date('2026-05-12T08:00:00+08:00').toISOString(),
);

console.log('node scheduler tests passed');
