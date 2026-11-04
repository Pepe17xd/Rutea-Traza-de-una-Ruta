import { createHash } from 'node:crypto'
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { python, root, run } from './lib.mjs'

const firmware = path.join(root, 'Firmware')
const pioEnv = { ...process.env, PLATFORMIO_CORE_DIR: process.env.PLATFORMIO_CORE_DIR || path.join(firmware, '.platformio-core') }
if (process.env.RUTEA_SKIP_NATIVE_TESTS !== 'true') {
  console.log('Ejecutando pruebas host Unity…')
  run(python(), ['-m', 'platformio', 'test', '-e', 'native'], { cwd: firmware, env: pioEnv, timeout: 15 * 60 * 1000 })
}
console.log('Compilando target PlatformIO esp32dev…')
run(python(), ['-m', 'platformio', 'run', '-e', 'esp32dev'], { cwd: firmware, env: pioEnv, timeout: 30 * 60 * 1000 })
const built = path.join(firmware, '.pio', 'build', 'esp32dev', 'firmware.bin')
const bytes = readFileSync(built)
const sha256 = createHash('sha256').update(bytes).digest('hex')
const version = process.env.RUTEA_FIRMWARE_VERSION || `rutea-esp32dev-${new Date().toISOString().replaceAll(':', '').replaceAll('.', '')}`
const output = path.join(root, 'artifacts', 'firmware', version)
mkdirSync(output, { recursive: true })
copyFileSync(built, path.join(output, 'firmware.bin'))
const manifest = { product: 'RUTEA', target: 'esp32dev', version, builtAt: new Date().toISOString(), sha256, bytes: bytes.length, physicalMotorControlEnabled: false, flashedAutomatically: false }
writeFileSync(path.join(output, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`)
console.log(`Artefacto: artifacts/firmware/${version}/firmware.bin`)
console.log(`SHA-256: ${sha256}`)
console.log('El firmware no fue flasheado; revisar variante física de placa/sensores antes de instalar.')
