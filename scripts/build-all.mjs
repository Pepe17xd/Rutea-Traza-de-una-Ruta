import path from 'node:path'
import { root, run } from './lib.mjs'
run(process.execPath, [path.join(root, 'scripts', 'test-all.mjs')])
run(process.execPath, [path.join(root, 'scripts', 'build-firmware.mjs')], { env: { ...process.env, RUTEA_SKIP_NATIVE_TESTS: 'true' } })
