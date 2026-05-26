import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

export function candidatePythons(config) {
  const candidates = [];
  if (process.env.CCE_PYTHON) {
    candidates.push(process.env.CCE_PYTHON);
  }
  if (config.runtime?.python && config.runtime.python !== 'auto') {
    candidates.push(config.runtime.python);
  }
  candidates.push('python3', 'python');
  return [...new Set(candidates)];
}

export function findPython(config) {
  const failures = [];
  for (const candidate of candidatePythons(config)) {
    const result = spawnSync(candidate, ['--version'], { encoding: 'utf8', windowsHide: true });
    if (result.status === 0) {
      return {
        command: candidate,
        version: (result.stdout || result.stderr).trim(),
      };
    }
    failures.push(`${candidate}: ${(result.stderr || result.error?.message || 'not executable').trim()}`);
  }
  throw new Error(`No usable Python interpreter found. Tried: ${failures.join('; ')}`);
}

export function exportScriptPath(projectRoot) {
  const scriptPath = path.join(projectRoot, 'export_session.py');
  if (!fs.existsSync(scriptPath)) {
    throw new Error(`Export script not found: ${scriptPath}`);
  }
  return scriptPath;
}
