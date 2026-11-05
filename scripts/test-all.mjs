import path from 'node:path'
import { existsSync } from 'node:fs'
import { python, root, run } from './lib.mjs'
const pioEnv = { ...process.env, PLATFORMIO_CORE_DIR: path.join(root, 'Firmware', '.platformio-core') }
console.log('Tests unitarios de simulación IAM…')
run(process.execPath, ['--test', path.join(root, 'scripts', 'tests', 'iam-policy-simulation.test.mjs'), path.join(root, 'scripts', 'tests', 'dynamo-plan.test.mjs'), path.join(root, 'scripts', 'tests', 'cloudformation-graph.test.mjs'), path.join(root, 'scripts', 'tests', 'package-path.test.mjs')], { cwd: root })
console.log('Validando Compose, Serverless y CloudFormation localmente…')
run(python(), [path.join(root, 'scripts', 'validate-config.py')], { cwd: root })
console.log('Suite backend Python…')
const testEnv = { ...process.env, HECTOR_STORAGE: 'sqlite', HECTOR_SQLITE_PATH: path.join(root, 'Backend', '.pytest_cache', 'rutea-test-runtime.db'), HECTOR_REQUIRE_AUTH: 'true', HECTOR_OPERATOR_PASSWORD_HASH: '', HECTOR_SESSION_SIGNING_KEY: '', HECTOR_DEVICE_TOKEN: '' }
run(python(), ['-m', 'pytest', '-q'], { cwd: path.join(root, 'Backend'), env: testEnv, timeout: 15 * 60 * 1000 })
console.log('Tests nativos PlatformIO…')
run(python(), ['-m', 'platformio', 'test', '-e', 'native'], { cwd: path.join(root, 'Firmware'), env: pioEnv, timeout: 15 * 60 * 1000 })
console.log('Build TypeScript/Vite…')
if (!existsSync(path.join(root, 'Frontend', 'node_modules'))) run(process.platform === 'win32' ? 'npm.cmd' : 'npm', ['ci'], { cwd: path.join(root, 'Frontend') })
run(process.platform === 'win32' ? 'npm.cmd' : 'npm', ['run', 'build'], { cwd: path.join(root, 'Frontend'), timeout: 15 * 60 * 1000 })
console.log('Backend, PlatformIO native y build frontend aprobados.')
