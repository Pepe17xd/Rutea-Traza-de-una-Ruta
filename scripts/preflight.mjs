import { existsSync } from 'node:fs'
import path from 'node:path'
import { planTables } from './dynamo-plan.mjs'
import { assertFile, awsJson, isWindows, python, root, run } from './lib.mjs'
import {
  deniedIamEvaluations,
  dynamoProvisioningSimulationGroups,
  dynamoRuntimeSimulationGroups,
  formatIamSimulationError,
  GENERIC_DEPLOY_ACTIONS,
  passRoleSimulationArgs,
} from './iam-policy-simulation.mjs'

const args = process.argv.slice(2)
const dry = args.includes('--dry-run') || args.includes('--plan-only')
const region = process.env.AWS_REGION || 'us-east-1'
const stage = args.find((arg) => arg.startsWith('--stage='))?.split('=')[1] || process.env.AWS_STAGE || 'academy'
const fail = (message) => { console.error(`BLOQUEO: ${message}`); process.exit(2) }
const check = (condition, message) => { if (!condition) fail(message); console.log(`✓ ${message}`) }
const names = {
  missions: process.env.MISSIONS_TABLE || `rutea-${stage}-missions`,
  telemetry: process.env.TELEMETRY_TABLE || `rutea-${stage}-telemetry`,
}

for (const file of ['serverless-compose.yml', 'Backend/serverless.yml', 'Backend/requirements-lambda.txt', 'Frontend/package-lock.json']) assertFile(file)
if (!/^\d{12}$/.test(process.env.AWS_ACCOUNT_ID || '')) {
  if (!dry) fail('AWS_ACCOUNT_ID debe ser el numero de cuenta de 12 digitos que el usuario configura manualmente en .env')
}
if (dry) {
  run(process.execPath, [path.join(root, 'scripts', 'audit-secrets.mjs')])
  run(python(), [path.join(root, 'scripts', 'validate-config.py')], { cwd: root })
  check(Number(process.versions.node.split('.')[0]) >= 20, 'Node 20 o superior disponible')
  check(region === 'us-east-1' || /^[a-z]{2}(-gov)?-[a-z]+-\d$/.test(region), `Region valida: ${region}`)
  console.log(`Preflight seco aprobado para stage=${stage}, region=${region}. No consulto AWS ni compruebo permisos reales.`)
  process.exit(0)
}

check(!isWindows, 'Ejecucion desde Linux para empaquetado Lambda Python 3.12')
check(/^\d{12}$/.test(process.env.AWS_ACCOUNT_ID || ''), 'AWS_ACCOUNT_ID manual tiene 12 digitos')
check(/^[a-z0-9][a-z0-9-]{0,19}$/.test(stage), `Stage valido: ${stage}`)
check(region === 'us-east-1' || /^[a-z]{2}(-gov)?-[a-z]+-\d$/.test(region), `Region valida: ${region}`)
run(process.execPath, [path.join(root, 'scripts', 'audit-secrets.mjs')])
run(python(), [path.join(root, 'scripts', 'validate-config.py')], { cwd: root })
check(Number(process.versions.node.split('.')[0]) >= 20, `Node ${process.versions.node} >= 20`)
for (const [label, command, pattern] of [
  ['AWS CLI v2', 'aws', /aws-cli\/2\./], ['npm', 'npm', /\d+\.\d+/],
]) {
  const result = run(command, ['--version'], { capture: true })
  check(!result.error && result.status === 0 && pattern.test(result.stdout + result.stderr), `${label} instalado`)
}
const py = run(python(), ['--version'], { capture: true })
check(py.status === 0 && /Python 3\.12\./.test(py.stdout + py.stderr), 'Python 3.12 instalado para Lambda y dependencias')
check((process.env.HECTOR_OPERATOR_PASSWORD_HASH || '').startsWith('$argon2id$'), 'HECTOR_OPERATOR_PASSWORD_HASH Argon2id configurado fuera de Git')
check((process.env.HECTOR_SESSION_SIGNING_KEY || '').trim().length >= 32, 'HECTOR_SESSION_SIGNING_KEY configurado fuera de Git (32 caracteres mínimos)')
check((process.env.HECTOR_DEVICE_TOKEN || '').trim().length >= 24, 'HECTOR_DEVICE_TOKEN configurado fuera de Git (longitud suficiente)')
check((process.env.HECTOR_REQUIRE_AUTH || 'true').toLowerCase() === 'true', 'HECTOR_REQUIRE_AUTH permanece activo')

const sls = path.join(root, 'Backend', 'node_modules', 'serverless', 'run.js')
check(existsSync(sls), 'Serverless Framework instalado en Backend')
const framework = run(process.execPath, [sls, '--version'], { cwd: root, capture: true })
check(framework.status === 0 && /4\./.test(framework.stdout + framework.stderr), 'Serverless Framework v4 instalado')
const print = run(process.execPath, [sls, 'print', '--config', path.join(root, 'Backend', 'serverless.yml'), '--stage', stage, '--region', region], { cwd: root, capture: true, timeout: 120000 })
check(print.status === 0, 'Serverless autenticado y configuracion backend resuelta')

let identity
try { identity = awsJson(['sts', 'get-caller-identity', '--region', region]) }
catch (error) { fail(`STS no valida credenciales temporales activas de Learner Lab: ${error.message}`) }
check(identity.Account === process.env.AWS_ACCOUNT_ID, `STS confirma la cuenta configurada ${identity.Account}`)
check(identity.Arn.includes(':assumed-role/'), 'Identidad temporal basada en rol AWS Academy')
let role
try { role = awsJson(['iam', 'get-role', '--role-name', 'LabRole', '--region', region]).Role }
catch (error) { fail(`No se pudo leer LabRole preexistente (sin crear ni modificar roles): ${error.message}`) }
const roleArn = `arn:aws:iam::${process.env.AWS_ACCOUNT_ID}:role/LabRole`
check(role.Arn === roleArn, `LabRole coincide con ARN dinamico ${roleArn}`)
const trusted = role.AssumeRolePolicyDocument?.Statement?.flatMap((s) => Array.isArray(s.Principal?.Service) ? s.Principal.Service : [s.Principal?.Service]).filter(Boolean) ?? []
check(trusted.includes('lambda.amazonaws.com'), 'LabRole existente permite ser asumido por Lambda')

let callerArn = identity.Arn
const assumed = callerArn.match(/^arn:aws:sts::(\d{12}):assumed-role\/(.+)\/[^/]+$/)
if (assumed) callerArn = `arn:aws:iam::${assumed[1]}:role/${assumed[2]}`
const simulate = (principal, actions, resources, label = 'permisos de despliegue') => {
  let result
  try { result = awsJson(['iam', 'simulate-principal-policy', '--policy-source-arn', principal, '--action-names', ...actions, '--resource-arns', ...resources, '--region', region]) }
  catch (error) { fail(formatIamSimulationError(error, label, actions, resources)) }
  const blocked = deniedIamEvaluations(result.EvaluationResults, actions)
  if (blocked.length) fail(`Denegacion IAM para ${label} (${principal}): ${blocked.map((entry) => `${entry.EvalActionName}=${entry.EvalDecision}`).join(', ')}`)
  console.log(`[OK] Permisos IAM confirmados para ${label} (${principal}): ${actions.length} acciones`)
}
simulate(callerArn, GENERIC_DEPLOY_ACTIONS, ['*'], 'acciones generales de despliegue')
let passRoleResult
try { passRoleResult = awsJson(passRoleSimulationArgs(callerArn, roleArn, region)) }
catch (error) { fail(formatIamSimulationError(error, 'iam:PassRole para Lambda', ['iam:PassRole'], [roleArn])) }
const passRoleBlocked = deniedIamEvaluations(passRoleResult.EvaluationResults, ['iam:PassRole'])
if (passRoleBlocked.length) fail(`Denegacion IAM para iam:PassRole (${callerArn} -> ${roleArn}): ${passRoleBlocked.map((entry) => `${entry.EvalDecision}${entry.MissingContextValues?.length ? ` (contexto faltante: ${entry.MissingContextValues.join(', ')})` : ''}`).join(', ')}`)
console.log(`[OK] iam:PassRole permitido para ${callerArn} sobre ${roleArn} con iam:PassedToService=lambda.amazonaws.com`)
for (const group of dynamoRuntimeSimulationGroups(region, identity.Account, names)) {
  simulate(roleArn, group.actions, group.resources, group.label)
}
simulate(roleArn, ['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents'], ['*'], 'CloudWatch Logs de ejecucion')

for (const group of dynamoProvisioningSimulationGroups(region, identity.Account, names, false)) {
  simulate(callerArn, group.actions, group.resources, group.label)
}
let tablePlan
try { tablePlan = planTables({ names, stage, region, createAllowed: process.env.RUTEA_CREATE_DYNAMO_TABLES === 'true', awsJson }) }
catch (error) { fail(error.message) }
const missingNames = Object.fromEntries(Object.entries(tablePlan).filter(([, table]) => table.create).map(([kind, table]) => [kind, table.name]))
if (Object.keys(missingNames).length) {
  for (const group of dynamoProvisioningSimulationGroups(region, identity.Account, missingNames, true).slice(1)) {
    simulate(callerArn, group.actions, group.resources, group.label)
  }
}
for (const table of Object.values(tablePlan)) console.log(`Tabla ${table.name}: ${table.create ? 'creacion autorizada, pendiente de despliegue' : table.managed ? 'existente administrada por el stack' : 'existente externa, conservada'}`)

for (const [service, args] of [
  ['CloudFormation', ['cloudformation', 'describe-account-limits', '--region', region]],
  ['Lambda', ['lambda', 'get-account-settings', '--region', region]],
  ['API Gateway HTTP API', ['apigatewayv2', 'get-apis', '--max-results', '1', '--region', region]],
]) {
  try { awsJson(args); console.log(`✓ ${service}: lectura y cuota disponibles`) }
  catch (error) { fail(`${service}: permiso/cuota no verificable: ${error.message}`) }
}
for (const url of ['https://registry.npmjs.org/-/ping', 'https://pypi.org/simple/']) {
  try { const response = await fetch(url, { signal: AbortSignal.timeout(10000) }); check(response.ok, `Registro accesible: ${new URL(url).host}`) }
  catch { fail(`No hay conectividad al registro ${new URL(url).host}`) }
}
console.log('Presupuesto y restricciones restantes: confirmar saldo/cuotas en Learner Lab; no hay API universal para el saldo Academy.')
console.log('Preflight completado. No se crearon ni modificaron recursos AWS.')
