import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { main } from '../lib/cce/commands.js';

const testRoot = path.resolve('tests/tmp');
fs.rmSync(testRoot, { recursive: true, force: true });
fs.mkdirSync(testRoot, { recursive: true });

async function captureStdout(callback) {
  const originalLog = console.log;
  const lines = [];
  console.log = (message = '') => {
    lines.push(String(message));
  };
  try {
    const code = await callback();
    return { code, stdout: `${lines.join('\n')}\n` };
  } finally {
    console.log = originalLog;
  }
}

const help = await captureStdout(() => main(['--help']));
assert.equal(help.code, 0);
assert.match(help.stdout, /cli-chat-exporter/);
assert.match(help.stdout, /Usage:/);
assert.match(help.stdout, /export/);
assert.match(help.stdout, /service/);
assert.match(help.stdout, /doctor/);
assert.doesNotMatch(help.stdout, /--user/);
assert.doesNotMatch(help.stdout, /sudo/i);

const helpAlias = await captureStdout(() => main(['help']));
assert.equal(helpAlias.code, 0);
assert.equal(helpAlias.stdout, help.stdout);

const version = await captureStdout(() => main(['--version']));
assert.equal(version.code, 0);
assert.match(version.stdout, /@benryoung\/cli-chat-exporter 0\.2\.2/);

const staleConfigPath = path.join(testRoot, 'stale-config.json');
fs.writeFileSync(
  staleConfigPath,
  JSON.stringify({
    user: 'all',
    output: '/tmp/cce-legacy-output',
    schedule: { earliest: '00:00', latest: '01:00', interval: '1h' },
    runtime: {
      log_dir: path.join(testRoot, 'logs'),
      pid_file: path.join(testRoot, 'cce.pid'),
      state_file: path.join(testRoot, 'state.json'),
    },
  }, null, 2),
  'utf8',
);

process.env.CCE_CONFIG = staleConfigPath;
const config = await captureStdout(() => main(['config', 'get']));
assert.equal(config.code, 0);
const parsed = JSON.parse(config.stdout);
assert.equal(Object.hasOwn(parsed, 'user'), false);
assert.equal(parsed.source, 'all');

await assert.rejects(
  () => main(['config', 'set', '--user', 'all']),
  /Unknown option: --user/,
);

await assert.rejects(
  () => main(['config', 'init', '--yes', '--user', 'all']),
  /Unknown option: --user/,
);

await assert.rejects(
  () => main(['export', '--user', 'all']),
  /Unknown option: --user/,
);

await assert.rejects(
  () => main(['export', 'all']),
  /Unknown argument: all/,
);

const setConfig = await captureStdout(() => main(['config', 'set', '--output', '/tmp/cce-next-output']));
assert.equal(setConfig.code, 0);
const setParsed = JSON.parse(setConfig.stdout);
assert.equal(Object.hasOwn(setParsed, 'user'), false);
assert.equal(setParsed.output, '/tmp/cce-next-output');

const initConfigPath = path.join(testRoot, 'init-config.json');
process.env.CCE_CONFIG = initConfigPath;
const initConfig = await captureStdout(() => main(['config', 'init', '--yes']));
assert.equal(initConfig.code, 0);
assert.equal(Object.hasOwn(JSON.parse(initConfig.stdout), 'user'), false);

const commandSource = fs.readFileSync('lib/cce/commands.js', 'utf8');
assert.doesNotMatch(commandSource, /sudo/i);
assert.doesNotMatch(commandSource, /rejectUserScopeFlag/);
assert.doesNotMatch(commandSource, /current local user/);

console.log('node cli tests passed');
