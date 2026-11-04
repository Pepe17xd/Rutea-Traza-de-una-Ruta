import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
export const isWindows = process.platform === 'win32'
const rootEnvFile = path.join(root, '.env')
if (existsSync(rootEnvFile)) {
  for (const line of readFileSync(rootEnvFile, 'utf8').split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/)
    if (!match || process.env[match[1]] !== undefined) continue
    let value = match[2]
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1)
    process.env[match[1]] = value
  }
}
export const python = () => {
  if (process.env.PYTHON) return process.env.PYTHON
  const venvPython = path.join(root, 'Backend', '.venv', isWindows ? 'Scripts/python.exe' : 'bin/python')
  return existsSync(venvPython) ? venvPython : (isWindows ? 'python' : 'python3')
}
export const run = (command, args = [], options = {}) => {
  let executable = command
  let childArgs = args
  if (isWindows && /^npm(?:\.cmd)?$/i.test(command)) {
    executable = process.execPath
    childArgs = [path.join(path.dirname(process.execPath), 'node_modules', 'npm', 'bin', 'npm-cli.js'), ...args]
  }
  const result = spawnSync(executable, childArgs, {
    cwd: options.cwd ?? root,
    env: options.env ?? process.env,
    encoding: 'utf8',
    shell: false,
    stdio: options.capture ? ['ignore', 'pipe', 'pipe'] : 'inherit',
    timeout: options.timeout ?? 0,
  })
  if (options.capture) return result
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(`${command} terminó con código ${result.status ?? 'desconocido'}`)
  return result
}
export const assertFile = (relative) => {
  const full = path.join(root, relative)
  if (!existsSync(full)) throw new Error(`Falta archivo requerido: ${relative}`)
  return full
}
export const aws = (args, options = {}) => run('aws', args, options)
export function awsJson(args) {
  const r = aws([...args, '--output', 'json'], { capture: true })
  if (r.error || r.status !== 0) throw new Error((r.stderr || r.stdout || 'AWS CLI falló').trim())
  return JSON.parse(r.stdout)
}
export function outputValue(outputs, key) {
  const value = outputs?.find((entry) => entry.OutputKey === key)?.OutputValue
  if (!value) throw new Error(`El stack no publicó el output ${key}`)
  return value
}
