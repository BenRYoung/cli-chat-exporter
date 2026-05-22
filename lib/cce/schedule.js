export const defaultConfig = {
  source: 'all',
  format: 'both',
  output: '~/AIChatRecords',
  overwrite: false,
  schedule: {
    earliest: '00:00',
    latest: '23:00',
    interval: '1h',
    timezone: 'local',
  },
  runtime: {
    python: 'auto',
    log_dir: '~/.local/state/cce/logs',
    pid_file: '~/.local/state/cce/cce.pid',
    state_file: '~/.local/state/cce/state.json',
  },
};

export function parseInterval(value) {
  const match = /^(\d+)(m|h)$/.exec(String(value || '').trim());
  if (!match) {
    throw new Error(`Invalid interval: ${value}. Use values like 15m, 30m, 1h, or 2h.`);
  }
  const amount = Number.parseInt(match[1], 10);
  if (!Number.isSafeInteger(amount) || amount <= 0) {
    throw new Error(`Invalid interval amount: ${value}`);
  }
  return match[2] === 'h' ? amount * 60 : amount;
}

export function parseClock(value) {
  const match = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(String(value || '').trim());
  if (!match) {
    throw new Error(`Invalid clock value: ${value}. Use HH:MM.`);
  }
  return Number.parseInt(match[1], 10) * 60 + Number.parseInt(match[2], 10);
}

export function formatClock(totalMinutes) {
  const normalized = ((totalMinutes % 1440) + 1440) % 1440;
  const hour = Math.floor(normalized / 60);
  const minute = normalized % 60;
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}

export function scheduleSlots(earliest, latest, interval) {
  const start = parseClock(earliest);
  const end = parseClock(latest);
  const step = parseInterval(interval);
  const endNormalized = end >= start ? end : end + 1440;
  const slots = [];
  for (let minute = start; minute <= endNormalized; minute += step) {
    slots.push(formatClock(minute));
  }
  return slots;
}

function dateAtLocalMinutes(base, minutes, dayOffset = 0) {
  const date = new Date(base);
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() + dayOffset);
  date.setMinutes(minutes);
  return date;
}

export function nextRunAfter(afterDate, schedule) {
  const earliest = schedule.earliest ?? defaultConfig.schedule.earliest;
  const latest = schedule.latest ?? defaultConfig.schedule.latest;
  const interval = schedule.interval ?? defaultConfig.schedule.interval;
  const start = parseClock(earliest);
  const end = parseClock(latest);
  const step = parseInterval(interval);
  const crossesMidnight = end < start;
  const candidates = [];

  for (let dayOffset = -1; dayOffset <= 2; dayOffset += 1) {
    const endNormalized = crossesMidnight ? end + 1440 : end;
    for (let minute = start; minute <= endNormalized; minute += step) {
      const candidateDayOffset = dayOffset + Math.floor(minute / 1440);
      candidates.push(dateAtLocalMinutes(afterDate, minute % 1440, candidateDayOffset));
    }
  }

  const future = candidates
    .filter((candidate) => candidate.getTime() > afterDate.getTime())
    .sort((left, right) => left.getTime() - right.getTime());
  if (!future.length) {
    throw new Error('Could not compute next schedule run.');
  }
  return future[0];
}
