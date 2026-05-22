import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import readline from 'node:readline/promises';
import { readConfig, resolveRuntimePaths, writeConfig } from './config.js';
import { defaultConfig, nextRunAfter, scheduleSlots } from './schedule.js';
import { exportScriptPath, findPython } from './python.js';

export const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

function packageInfo() {
  const raw = fs.readFileSync(path.join(projectRoot, 'package.json'), 'utf8');
  return JSON.parse(raw);
}

function printHelp() {
  console.log(`cli-chat-exporter (cce) - local AI chat history exporter

Usage:
    Export now
        cce export [--source all|codex|openclaw|cursor|auto] [--format both|html|md] [--output DIR] [--overwrite]

    Scheduled export
        cce service run
        cce service start
        cce service stop
        cce service status

    Configuration
        cce config get
        cce config init
        cce config set [--source SOURCE] [--output DIR] [--earliest HH:MM] [--latest HH:MM] [--interval 1h] [--log-dir DIR]

    Diagnostics
        cce doctor
`);
}

const exportValueFlags = new Set(['platform', 'source', 'format', 'output', 'session-file', 'session-id']);
const exportBooleanFlags = new Set(['overwrite']);
const configValueFlags = new Set(['source', 'format', 'output', 'earliest', 'latest', 'interval', 'log-dir', 'pid-file', 'state-file']);
const initBooleanFlags = new Set(['yes']);
const serviceBooleanFlags = new Set(['once']);

function parseFlags(args, valueFlags = new Set(), booleanFlags = new Set()) {
  const flags = {};
  for (let index = 0; index < args.length; index += 1) {
    const item = args[index];
    if (!item.startsWith('--')) {
      throw new Error(`Unknown argument: ${item}`);
    }
    const key = item.slice(2);
    if (booleanFlags.has(key)) {
      flags[key] = true;
      continue;
    }
    if (!valueFlags.has(key)) {
      throw new Error(`Unknown option: --${key}`);
    }
    const value = args[index + 1];
    if (value === undefined || value.startsWith('--')) {
      throw new Error(`Missing value for --${key}`);
    }
    flags[key] = value;
    index += 1;
  }
  return flags;
}

function isYes(value) {
  return /^(y|yes|true|1)$/i.test(String(value || '').trim());
}

function buildExportArgs(config, flags) {
  const args = [
    exportScriptPath(projectRoot),
    '--platform',
    flags.platform || config.platform || 'ubuntu',
    '--user',
    os.userInfo().username,
    '--source',
    flags.source || config.source || defaultConfig.source,
    '--format',
    flags.format || config.format || defaultConfig.format,
    '--output',
    flags.output || config.output || defaultConfig.output,
  ];
  if (flags['session-file']) {
    args.push('--session-file', flags['session-file']);
  }
  if (flags['session-id']) {
    args.push('--session-id', flags['session-id']);
  }
  if (flags.overwrite || config.overwrite) {
    args.push('--overwrite');
  }
  return args;
}

function buildExportEnv(config) {
  const runtime = resolveRuntimePaths(config);
  return {
    ...process.env,
    CCE_EXPORT_LOG_DIR: path.join(runtime.logDir, 'export_logs'),
    CCE_DEFAULT_OUTPUT: config.output || defaultConfig.output,
  };
}

export function runExport(args) {
  const flags = parseFlags(args, exportValueFlags, exportBooleanFlags);
  const config = readConfig();
  const python = findPython(config);
  const result = spawnSync(python.command, buildExportArgs(config, flags), {
    cwd: projectRoot,
    encoding: 'utf8',
    stdio: 'inherit',
    env: buildExportEnv(config),
  });
  return result.status ?? 1;
}

function updateConfigFromFlags(config, flags) {
  const next = structuredClone(config);
  for (const key of ['source', 'format', 'output']) {
    if (flags[key] !== undefined) {
      next[key] = flags[key];
    }
  }
  if (flags.earliest !== undefined) {
    next.schedule.earliest = flags.earliest;
  }
  if (flags.latest !== undefined) {
    next.schedule.latest = flags.latest;
  }
  if (flags.interval !== undefined) {
    next.schedule.interval = flags.interval;
  }
  if (flags['log-dir'] !== undefined) {
    next.runtime.log_dir = flags['log-dir'];
  }
  if (flags['pid-file'] !== undefined) {
    next.runtime.pid_file = flags['pid-file'];
  }
  if (flags['state-file'] !== undefined) {
    next.runtime.state_file = flags['state-file'];
  }
  return next;
}

export function runConfig(args) {
  const [action, ...rest] = args;
  const config = readConfig();
  if (!action || action === 'get') {
    console.log(JSON.stringify(config, null, 2));
    return 0;
  }
  if (action === 'init') {
    return runConfigInit(rest, config);
  }
  if (action === 'set') {
    const flags = parseFlags(rest, configValueFlags);
    const next = updateConfigFromFlags(config, flags);
    scheduleSlots(next.schedule.earliest, next.schedule.latest, next.schedule.interval);
    writeConfig(next);
    console.log(JSON.stringify(next, null, 2));
    return 0;
  }
  throw new Error(`Unknown config action: ${action}`);
}

export async function runConfigInit(args, config = readConfig()) {
  const flags = parseFlags(args, configValueFlags, initBooleanFlags);
  const defaults = updateConfigFromFlags(structuredClone(config), flags);
  if (flags.yes) {
    scheduleSlots(defaults.schedule.earliest, defaults.schedule.latest, defaults.schedule.interval);
    writeConfig(defaults);
    console.log(JSON.stringify(defaults, null, 2));
    return 0;
  }

  const terminal = process.stdin.isTTY
    ? readline.createInterface({ input: process.stdin, output: process.stdout })
    : null;
  const pipedAnswers = terminal ? null : fs.readFileSync(0, 'utf8').split(/\r?\n/);
  const ask = async (label, current) => {
    if (pipedAnswers) {
      const answer = pipedAnswers.shift() ?? '';
      process.stdout.write(`${label} [${current}]: ${answer}\n`);
      return answer.trim() || current;
    }
    const answer = await terminal.question(`${label} [${current}]: `);
    return answer.trim() || current;
  };
  const askYesNo = async (label, current = 'n') => {
    const answer = await ask(label, current);
    return isYes(answer);
  };

  try {
    const next = structuredClone(defaults);
    next.output = await ask('Output directory', next.output);
    next.source = await ask('Source', next.source);
    next.schedule.earliest = await ask('Earliest run time', next.schedule.earliest);
    next.schedule.latest = await ask('Latest run time', next.schedule.latest);
    next.schedule.interval = await ask('Run interval', next.schedule.interval);
    next.runtime.log_dir = await ask('Log directory', next.runtime.log_dir);
    scheduleSlots(next.schedule.earliest, next.schedule.latest, next.schedule.interval);
    writeConfig(next);
    console.log(JSON.stringify(next, null, 2));
    const startNow = await askYesNo('Start the scheduled service now', 'n');
    if (startNow) {
      const code = serviceStart();
      if (code !== 0) {
        return code;
      }
    }
    return 0;
  } finally {
    terminal?.close();
  }
}

function writeState(config, patch) {
  const runtime = resolveRuntimePaths(config);
  fs.mkdirSync(path.dirname(runtime.stateFile), { recursive: true });
  const current = fs.existsSync(runtime.stateFile)
    ? JSON.parse(fs.readFileSync(runtime.stateFile, 'utf8'))
    : {};
  fs.writeFileSync(runtime.stateFile, `${JSON.stringify({ ...current, ...patch }, null, 2)}\n`, 'utf8');
}

function readState(config) {
  const runtime = resolveRuntimePaths(config);
  if (!fs.existsSync(runtime.stateFile)) {
    return {};
  }
  return JSON.parse(fs.readFileSync(runtime.stateFile, 'utf8'));
}

function isProcessAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

export async function serviceRun(args) {
  const flags = parseFlags(args, new Set(), serviceBooleanFlags);
  const config = readConfig();
  const runtime = resolveRuntimePaths(config);
  fs.mkdirSync(runtime.logDir, { recursive: true });
  fs.mkdirSync(path.dirname(runtime.pidFile), { recursive: true });
  fs.writeFileSync(runtime.pidFile, `${process.pid}\n`, 'utf8');
  const cleanupPidFile = () => {
    try {
      if (fs.existsSync(runtime.pidFile)) {
        const pid = Number.parseInt(fs.readFileSync(runtime.pidFile, 'utf8'), 10);
        if (pid === process.pid) {
          fs.rmSync(runtime.pidFile, { force: true });
        }
      }
    } catch {
      // ignore cleanup errors during process shutdown
    }
  };
  process.once('exit', cleanupPidFile);
  process.once('SIGTERM', () => {
    cleanupPidFile();
    process.exit(0);
  });
  process.once('SIGINT', () => {
    cleanupPidFile();
    process.exit(0);
  });
  let running = false;

  const executeOnce = () => {
    if (running) {
      writeState(config, {
        last_skip_at: new Date().toISOString(),
        last_skip_reason: 'previous export still running',
      });
      return;
    }
    running = true;
    const startedAt = new Date();
    const python = findPython(config);
    const child = spawn(python.command, buildExportArgs(config, {}), {
      cwd: projectRoot,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: buildExportEnv(config),
    });
    const logFile = path.join(runtime.logDir, `export_${startedAt.toISOString().replace(/[:.]/g, '-')}.log`);
    const stream = fs.createWriteStream(logFile, { flags: 'a' });
    child.stdout.pipe(stream);
    child.stderr.pipe(stream);
    child.on('close', (code) => {
      running = false;
      writeState(config, {
        last_run_at: startedAt.toISOString(),
        last_exit_code: code,
        last_log: logFile,
        next_run_at: nextRunAfter(new Date(), config.schedule).toISOString(),
      });
      stream.end();
    });
  };

  writeState(config, {
    pid: process.pid,
    started_at: new Date().toISOString(),
    next_run_at: nextRunAfter(new Date(), config.schedule).toISOString(),
  });

  if (flags.once) {
    executeOnce();
    await new Promise((resolve) => {
      const timer = setInterval(() => {
        if (!running) {
          clearInterval(timer);
          resolve();
        }
      }, 100);
    });
    cleanupPidFile();
    return 0;
  }

  const tick = () => {
    const now = new Date();
    const state = readState(config);
    const next = state.next_run_at ? new Date(state.next_run_at) : nextRunAfter(now, config.schedule);
    if (now.getTime() >= next.getTime()) {
      executeOnce();
    }
  };
  setInterval(tick, 30_000);
  console.log(`cce service running; pid=${process.pid}; state=${runtime.stateFile}`);
  return new Promise(() => {});
}

export function serviceStart() {
  const config = readConfig();
  const runtime = resolveRuntimePaths(config);
  if (fs.existsSync(runtime.pidFile)) {
    const pid = Number.parseInt(fs.readFileSync(runtime.pidFile, 'utf8'), 10);
    if (pid && isProcessAlive(pid)) {
      console.error(`cce service already running with pid ${pid}`);
      return 1;
    }
  }
  fs.mkdirSync(runtime.logDir, { recursive: true });
  const logPath = path.join(runtime.logDir, 'service.log');
  const out = fs.openSync(logPath, 'a');
  const child = spawn(process.execPath, [path.join(projectRoot, 'bin', 'cce.js'), 'service', 'run'], {
    cwd: projectRoot,
    detached: true,
    stdio: ['ignore', out, out],
  });
  child.unref();
  console.log(`cce service started; pid=${child.pid}; log=${logPath}`);
  return 0;
}

export function serviceStop() {
  const config = readConfig();
  const runtime = resolveRuntimePaths(config);
  if (!fs.existsSync(runtime.pidFile)) {
    console.log('cce service is not running');
    return 0;
  }
  const pid = Number.parseInt(fs.readFileSync(runtime.pidFile, 'utf8'), 10);
  if (!pid || !isProcessAlive(pid)) {
    fs.rmSync(runtime.pidFile, { force: true });
    console.log('removed stale cce pid file');
    return 0;
  }
  process.kill(pid, 'SIGTERM');
  fs.rmSync(runtime.pidFile, { force: true });
  console.log(`stopped cce service pid ${pid}`);
  return 0;
}

export function serviceStatus() {
  const config = readConfig();
  const runtime = resolveRuntimePaths(config);
  const state = readState(config);
  let running = false;
  let pid = state.pid;
  if (fs.existsSync(runtime.pidFile)) {
    pid = Number.parseInt(fs.readFileSync(runtime.pidFile, 'utf8'), 10);
    running = Boolean(pid && isProcessAlive(pid));
  }
  console.log(JSON.stringify({
    ...state,
    running,
    pid: running ? pid : null,
    config: process.env.CCE_CONFIG || path.join(os.homedir(), '.config', 'cce', 'config.json'),
    state_file: runtime.stateFile,
  }, null, 2));
  return 0;
}

export async function runService(args) {
  const [action = 'status', ...rest] = args;
  if (action === 'run') {
    return serviceRun(rest);
  }
  if (action === 'start') {
    return serviceStart();
  }
  if (action === 'stop') {
    return serviceStop();
  }
  if (action === 'status') {
    return serviceStatus();
  }
  throw new Error(`Unknown service action: ${action}`);
}

export function runVersion() {
  const info = packageInfo();
  console.log(`${info.name} ${info.version}`);
  return 0;
}

export function runDoctor() {
  const config = readConfig();
  const python = findPython(config);
  const script = exportScriptPath(projectRoot);
  const runtime = resolveRuntimePaths(config);
  const info = packageInfo();
  console.log(JSON.stringify({
    ok: true,
    package: info.name,
    version: info.version,
    node: process.version,
    python: python.version,
    python_command: python.command,
    export_script: script,
    config_path: process.env.CCE_CONFIG || path.join(os.homedir(), '.config', 'cce', 'config.json'),
    output: config.output,
    schedule_slots: scheduleSlots(config.schedule.earliest, config.schedule.latest, config.schedule.interval),
    runtime,
  }, null, 2));
  return 0;
}

export async function main(argv) {
  const [command, ...args] = argv;
  if (command === '--version' || command === '-v' || command === 'version') {
    return runVersion();
  }
  if (!command || command === '--help' || command === '-h' || command === 'help') {
    printHelp();
    return 0;
  }
  if (command === 'export') {
    return runExport(args);
  }
  if (command === 'config') {
    return await runConfig(args);
  }
  if (command === 'service') {
    return runService(args);
  }
  if (command === 'doctor') {
    return runDoctor();
  }
  throw new Error(`Unknown command: ${command}`);
}
