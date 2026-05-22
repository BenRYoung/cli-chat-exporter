import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { defaultConfig } from './schedule.js';

export function expandHome(rawPath) {
  if (!rawPath) {
    return rawPath;
  }
  if (rawPath === '~') {
    return os.homedir();
  }
  if (rawPath.startsWith('~/')) {
    return path.join(os.homedir(), rawPath.slice(2));
  }
  return rawPath;
}

export function defaultConfigPath() {
  return process.env.CCE_CONFIG || path.join(os.homedir(), '.config', 'cce', 'config.json');
}

function mergeObject(base, override) {
  const result = { ...base };
  for (const [key, value] of Object.entries(override || {})) {
    if (
      value
      && typeof value === 'object'
      && !Array.isArray(value)
      && typeof result[key] === 'object'
      && !Array.isArray(result[key])
    ) {
      result[key] = mergeObject(result[key], value);
    } else {
      result[key] = value;
    }
  }
  return result;
}

function stripUserScope(config) {
  const { user, ...rest } = config;
  return rest;
}

export function readConfig(configPath = defaultConfigPath()) {
  const config = fs.existsSync(configPath)
    ? mergeObject(defaultConfig, JSON.parse(fs.readFileSync(configPath, 'utf8')))
    : structuredClone(defaultConfig);
  return stripUserScope(config);
}

export function writeConfig(config, configPath = defaultConfigPath()) {
  fs.mkdirSync(path.dirname(configPath), { recursive: true });
  fs.writeFileSync(configPath, `${JSON.stringify(stripUserScope(config), null, 2)}\n`, 'utf8');
}

export function resolveRuntimePaths(config) {
  return {
    logDir: expandHome(config.runtime?.log_dir || defaultConfig.runtime.log_dir),
    pidFile: expandHome(config.runtime?.pid_file || defaultConfig.runtime.pid_file),
    stateFile: expandHome(config.runtime?.state_file || defaultConfig.runtime.state_file),
  };
}
