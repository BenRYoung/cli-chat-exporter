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

function localDate(year, month, day, hour, minute = 0) {
  return new Date(year, month - 1, day, hour, minute, 0, 0);
}

function assertLocalDateParts(date, expected) {
  assert.equal(date.getFullYear(), expected.year);
  assert.equal(date.getMonth() + 1, expected.month);
  assert.equal(date.getDate(), expected.day);
  assert.equal(date.getHours(), expected.hour);
  assert.equal(date.getMinutes(), expected.minute);
}

function assertSchedulerInCurrentTimezone() {
  const beforeWindow = localDate(2026, 5, 11, 7, 30);
  assertLocalDateParts(
    nextRunAfter(beforeWindow, { earliest: '08:00', latest: '10:00', interval: '1h' }),
    { year: 2026, month: 5, day: 11, hour: 8, minute: 0 },
  );

  const afterWindow = localDate(2026, 5, 11, 11, 0);
  assertLocalDateParts(
    nextRunAfter(afterWindow, { earliest: '08:00', latest: '10:00', interval: '1h' }),
    { year: 2026, month: 5, day: 12, hour: 8, minute: 0 },
  );

  const beforeMidnightSlot = localDate(2026, 5, 11, 23, 30);
  assertLocalDateParts(
    nextRunAfter(beforeMidnightSlot, { earliest: '21:00', latest: '02:00', interval: '1h' }),
    { year: 2026, month: 5, day: 12, hour: 0, minute: 0 },
  );
}

for (const timezone of [undefined, 'UTC', 'Asia/Shanghai', 'America/New_York']) {
  if (timezone) {
    process.env.TZ = timezone;
  } else {
    delete process.env.TZ;
  }
  assertSchedulerInCurrentTimezone();
}

console.log('node scheduler tests passed');
