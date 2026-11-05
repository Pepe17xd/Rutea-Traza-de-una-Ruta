import path from 'node:path'
import { cpSync, existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { assertFile, awsJson, isWindows, python, root, run } from './lib.mjs'
import { planTables } from './dynamo-plan.mjs'
import { assertPackageDirectory, packageInvocation } from './package-path.mjs'

const args = process.argv.slice(2)
const dry = args.includes('--dry-run') || args.includes('--plan-only')
const stage = args.find((arg) => arg.startsWith('--stage='))?.split('=')[1] || process.env.AWS_STAGE || 'academy'
const region = process.env.AWS_REGION || 'us-east-1'
const tableNames = {
  missions: process.env.MISSIONS_TABLE || `rutea-${stage}-missions`,
  telemetry: process.env.TELEMETRY_TABLE || `rutea-${stage}-telemetry`,
}
const plan = [
  'Instalar dependencias Node de Frontend y Backend usando lockfiles disponibles.',
  'Instalar Python y ejecutar pruebas obligatorias.',
  'Ejecutar preflight: cuenta STS contra AWS_ACCOUNT_ID, LabRole, permisos IAM y tablas DynamoDB.',
  'Compilar RUTEA con API relativa /api/v1 y polling; comprobar que el build no contiene localhost.',
  'Empaquetar el build SPA en Backend/app/frontend_dist para servirlo desde FastAPI.',
  'Empaquetar y validar el grafo CloudFormation generado.',
  'Desplegar el único servicio Serverless API: Lambda FastAPI + API Gateway HTTP API + DynamoDB.',
  'Verificar la URL HTTPS publicada, recursos estáticos y /api/v1/health.',
]
if (dry) {
  for (const file of ['serverless-compose.yml', 'Backend/serverless.yml', 'Backend/package.json', 'Backend/requirements-lambda.txt', 'Frontend/package-lock.json']) assertFile(file)
  console.log(`RUTEA dry-run (stage=${stage}, region=${region}); no instala, publica ni llama a AWS:`)
  plan.forEach((item, index) => console.log(`${index + 1}. ${item}`))
  console.log('La ejecución real requiere VM Linux, AWS_ACCOUNT_ID, credenciales vigentes, permisos verificados, Serverless autenticado y tokens privados configurados.')
  process.exit(0)
}
if (isWindows) throw new Error('El despliegue real debe ejecutarse desde VM Ubuntu/Linux de AWS Academy. En Windows use --dry-run.')
if (!/^[a-z0-9][a-z0-9-]{0,19}$/.test(stage)) throw new Error(`Stage inválido: ${stage}`)
if (!/^\d{12}$/.test(process.env.AWS_ACCOUNT_ID || '')) throw new Error('Configura el número real de cuenta AWS_ACCOUNT_ID en .env; no se infiere ni inventa.')
process.env.AWS_REGION = region
process.env.AWS_STAGE = stage
process.env.MISSIONS_TABLE = tableNames.missions
process.env.TELEMETRY_TABLE = tableNames.telemetry

const npm = 'npm'
console.log('Instalando dependencias desde lockfiles…')
run(npm, ['ci', '--prefix', path.join(root, 'Frontend'), '--no-audit', '--no-fund'])
const backendLock = path.join(root, 'Backend', 'package-lock.json')
if (existsSync(backendLock)) run(npm, ['ci', '--prefix', path.join(root, 'Backend'), '--no-audit', '--no-fund'])
else {
  console.warn('Backend/package-lock.json no está en este clon; generando lock local desde Serverless fijado exactamente en package.json.')
  run(npm, ['install', '--prefix', path.join(root, 'Backend'), '--no-audit', '--no-fund', '--save-exact'])
}

console.log('Preparando entorno Python y pruebas obligatorias...')
const venv = path.join(root, 'Backend', '.venv')
if (!existsSync(path.join(venv, 'bin', 'python'))) run('python3.12', ['-m', 'venv', venv])
run(python(), ['-m', 'pip', 'install', '-e', '.[dev,aws]', 'platformio'], { cwd: path.join(root, 'Backend'), timeout: 15 * 60 * 1000 })
run(process.execPath, [path.join(root, 'scripts', 'test-all.mjs')], { cwd: root, timeout: 30 * 60 * 1000 })

console.log('Ejecutando preflight AWS Academy en modo de solo lectura…')
run(process.execPath, [path.join(root, 'scripts', 'preflight.mjs'), `--stage=${stage}`])

const frontendEnv = {
  ...process.env,
  VITE_API_BASE: '/api/v1',
  VITE_REALTIME_TRANSPORT: 'polling',
  VITE_POLL_INTERVAL_MS: process.env.VITE_POLL_INTERVAL_MS || '15000',
  VITE_MISSION_POLL_INTERVAL_MS: process.env.VITE_MISSION_POLL_INTERVAL_MS || '15000',
  VITE_ROBOT_ID: process.env.VITE_ROBOT_ID || 'CAR_01',
}
delete frontendEnv.VITE_OPERATOR_TOKEN
console.log('Compilando frontend de producción con ruta API relativa…')
run(npm, ['run', 'build'], { cwd: path.join(root, 'Frontend'), env: frontendEnv, timeout: 10 * 60 * 1000 })
const dist = path.join(root, 'Frontend', 'dist')
if (!existsSync(path.join(dist, 'index.html'))) throw new Error('Vite no generó Frontend/dist/index.html')
const localRefs = []
const inspect = (folder) => {
  for (const entry of readdirSync(folder, { withFileTypes: true })) {
    const file = path.join(folder, entry.name)
    if (entry.isDirectory()) inspect(file)
    else if (/\.(?:html|js|css|json|svg|txt)$/i.test(entry.name)) {
      const content = readFileSync(file, 'utf8')
      if (/https?:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?/i.test(content)) localRefs.push(path.relative(dist, file))
    }
  }
}
inspect(dist)
if (localRefs.length) throw new Error(`Build de producción contiene URL local en: ${localRefs.join(', ')}`)

const staged = path.resolve(root, 'Backend', 'app', 'frontend_dist')
const expected = path.resolve(root, 'Backend', 'app') + path.sep
if (!staged.startsWith(expected)) throw new Error('Ruta de staging fuera de Backend/app; cancelado.')
rmSync(staged, { recursive: true, force: true })
cpSync(dist, staged, { recursive: true })

const sls = path.join(root, 'Backend', 'node_modules', 'serverless', 'run.js')
const tablePlan = planTables({ names: tableNames, stage, region, createAllowed: process.env.RUTEA_CREATE_DYNAMO_TABLES === 'true', awsJson })
const params = [`--param=createMissionsTable=${tablePlan.missions.declare}`, `--param=createTelemetryTable=${tablePlan.telemetry.declare}`]
const legacyPackage = path.join(root, 'Backend', '.serverless', 'academy-package')
if (existsSync(legacyPackage)) throw new Error('Existe Backend/.serverless/academy-package de un intento anterior; revíselo y retírelo del directorio .serverless antes de continuar, sin borrar configuraciones privadas.')
const packageDir = mkdtempSync(path.join(root, '.rutea-package-'))
try {
  assertPackageDirectory(packageDir, path.join(root, 'Backend', '.serverless'))
  const calls = packageInvocation(sls, path.join(root, 'Backend', 'serverless.yml'), stage, region, packageDir, params)
  console.log('Empaquetando y validando el grafo CloudFormation generado...')
  run(process.execPath, calls.packageArgs, { cwd: root, timeout: 20 * 60 * 1000 })
  run(process.execPath, [path.join(root, 'scripts', 'cloudformation-graph.mjs'), calls.template], { cwd: root })
  console.log(`Desplegando servicio RUTEA (${stage}/${region})...`)
  run(process.execPath, calls.deployArgs, { cwd: root, timeout: 45 * 60 * 1000 })
} finally {
  // Only remove the unique directory created for this invocation.
  rmSync(packageDir, { recursive: true, force: true })
}
const stackName = `rutea-api-${stage}`
const outputs = awsJson(['cloudformation', 'describe-stacks', '--stack-name', stackName, '--region', region]).Stacks?.[0]?.Outputs
const output = (key) => {
  const found = outputs?.find((item) => item.OutputKey === key)?.OutputValue
  if (!found) throw new Error(`Stack no publicó output ${key}`)
  return found
}
const frontendUrl = output('FrontendUrl')
const apiBase = output('ApiBaseUrl')
if (!frontendUrl.startsWith('https://') || !apiBase.startsWith(`${frontendUrl.replace(/\/$/, '')}/api/v1`)) throw new Error('Outputs HTTPS de API y frontend no comparten origen esperado.')
const healthUrl = `${apiBase}/health`
const check = async (url) => {
  const response = await fetch(url, { signal: AbortSignal.timeout(30000) })
  if (!response.ok) throw new Error(`${url} respondió HTTP ${response.status}`)
  return response
}
const page = await check(frontendUrl)
const html = await page.text()
if (!html.includes('RUTEA')) throw new Error('La página HTTPS no contiene el título de RUTEA.')
const assets = [...html.matchAll(/(?:src|href)="([^"]+\.(?:js|css))"/g)].map((m) => new URL(m[1], frontendUrl).href)
if (!assets.length) throw new Error('La página no referencia bundles JavaScript/CSS.')
for (const url of assets) {
  const response = await check(url)
  const content = await response.text()
  if (/https?:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?/i.test(content)) throw new Error(`Build público contiene referencia local: ${url}`)
}
const health = await check(healthUrl)
const healthData = await health.json()
if (healthData.status !== 'ok') throw new Error(`Health API inesperado: ${JSON.stringify(healthData)}`)
if (healthData.storage !== 'dynamodb') throw new Error('La API publicada no utiliza DynamoDB')
const sessionResponse = await check(`${apiBase}/auth/session`)
if ((await sessionResponse.json()).authenticated !== false) throw new Error('La sesion anonima no fue rechazada')
const protectedResponse = await fetch(`${apiBase}/missions?limit=1`, { signal: AbortSignal.timeout(30000) })
if (protectedResponse.status !== 401) throw new Error(`La API protegida sin sesion respondio HTTP ${protectedResponse.status}; se esperaba 401`)

const account = awsJson(['sts', 'get-caller-identity', '--region', region]).Account
if (account !== process.env.AWS_ACCOUNT_ID) throw new Error('La identidad cambió respecto a AWS_ACCOUNT_ID tras desplegar.')
const state = { stage, region, account, stackName, frontendUrl, apiBase, missionsTable: tableNames.missions, telemetryTable: tableNames.telemetry, recordedAt: new Date().toISOString() }
writeFileSync(path.join(root, '.rutea-deploy-state.json'), `${JSON.stringify(state, null, 2)}\n`, { flag: 'w' })
console.log('\nDESPLIEGUE COMPLETO Y VERIFICADO')
console.log(`Frontend y API: ${frontendUrl}`)
console.log(`Health: ${healthUrl} (HTTP ${health.status})`)
console.log(`Bundles HTTPS: ${assets.length}; tabla misiones: ${tableNames.missions}; tabla telemetría: ${tableNames.telemetry}`)
console.log('La respuesta API no confirma recepción física por ESP32. Movimiento y bomba permanecen sujetos a autorización local.')
