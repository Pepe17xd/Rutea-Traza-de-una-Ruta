import readline from 'node:readline/promises'
import { stdin, stdout } from 'node:process'
import { existsSync, readFileSync, unlinkSync } from 'node:fs'
import path from 'node:path'
import { aws, awsJson, isWindows, root, run } from './lib.mjs'

const args = process.argv.slice(2)
const stage = args.find((arg) => arg.startsWith('--stage='))?.split('=')[1] || process.env.AWS_STAGE || 'academy'
const region = process.env.AWS_REGION || 'us-east-1'
const deleteData = args.includes('--delete-data')
const stackName = `rutea-api-${stage}`
if (args.includes('--dry-run') || args.includes('--plan-only')) {
  console.log(`Limpieza dry-run del único stack ${stackName} en ${region}: API Gateway + Lambda + log group declarados.`)
  console.log('DynamoDB conserva tablas y registros por DeletionPolicy=Retain. --delete-data solo considera tablas RUTEA listadas en el estado local, tras confirmación separada.')
  console.log('No se llamó AWS, no se eliminó infraestructura.')
  process.exit(0)
}
if (isWindows) throw new Error('La limpieza administrada debe ejecutarse desde VM Linux de AWS Academy.')
if (!/^rutea-api-[a-z0-9][a-z0-9-]{0,19}$/.test(stackName)) throw new Error('Nombre de stack fuera del prefijo permitido RUTEA.')
const statePath = path.join(root, '.rutea-deploy-state.json')
const state = existsSync(statePath) ? JSON.parse(readFileSync(statePath, 'utf8')) : null
if (deleteData && (!state || state.stackName !== stackName || state.region !== region || !state.missionsTable || !state.telemetryTable)) throw new Error('No hay registro de despliegue coincidente; se rechaza inferir nombres de tablas para borrar datos.')
const phrase = deleteData ? `DELETE-RUTEA-DATA-${stage}` : `REMOVE-RUTEA-${stage}`
console.warn(`Se solicita eliminar solo el stack ${stackName}. Las tablas DynamoDB se retienen${deleteData ? ' salvo solicitud explícita de borrado' : ''}.`)
if (deleteData) console.warn(`ATENCIÓN: también se eliminarán datos de ${state.missionsTable} y ${state.telemetryTable}.`)
const prompt = readline.createInterface({ input: stdin, output: stdout })
try {
  const answer = await prompt.question(`Escribe exactamente ${phrase} para continuar: `)
  if (answer !== phrase) throw new Error('Confirmación no coincide; no se llamó a AWS.')
  if (deleteData) {
    const second = await prompt.question(`Confirma pérdida permanente escribiendo exactamente DELETE-DATA-${stage}: `)
    if (second !== `DELETE-DATA-${stage}`) throw new Error('Segunda confirmación no coincide; datos conservados.')
  }
} finally { prompt.close() }
const identity = awsJson(['sts', 'get-caller-identity', '--region', region])
if (!/^\d{12}$/.test(process.env.AWS_ACCOUNT_ID || '') || identity.Account !== process.env.AWS_ACCOUNT_ID) throw new Error('Cuenta AWS activa no coincide con AWS_ACCOUNT_ID; limpieza cancelada.')
if (state && (state.account !== identity.Account || state.region !== region || state.stage !== stage)) throw new Error('Cuenta/región/stage del estado no coincide; limpieza cancelada.')
if (deleteData) {
  const allowed = [`rutea-${stage}-missions`, `rutea-${stage}-telemetry`]
  for (const table of [state.missionsTable, state.telemetryTable]) if (!allowed.includes(table)) throw new Error(`Nombre de tabla fuera del espacio RUTEA esperado: ${table}`)
}
console.log(`Identidad confirmada ${identity.Arn}; retiro de ${stackName} en curso.`)
const sls = path.join(root, 'Backend', 'node_modules', 'serverless', 'run.js')
run(process.execPath, [sls, 'remove', '--config', path.join(root, 'Backend', 'serverless.yml'), '--stage', stage, '--region', region], { cwd: root, timeout: 60 * 60 * 1000 })
if (deleteData) {
  for (const table of [state.missionsTable, state.telemetryTable]) {
    try {
      aws(['dynamodb', 'delete-table', '--table-name', table, '--region', region])
      aws(['dynamodb', 'wait', 'table-not-exists', '--table-name', table, '--region', region], { timeout: 20 * 60 * 1000 })
      console.log(`Tabla y registros eliminados: ${table}`)
    } catch (error) {
      if (/ResourceNotFoundException|ResourceNotFound/.test(error.message)) console.log(`Tabla ya inexistente: ${table}`)
      else throw new Error(`No se pudo eliminar la tabla RUTEA ${table}: ${error.message}`)
    }
  }
}
if (state && existsSync(statePath)) unlinkSync(statePath)
console.log(`Stack ${stackName} retirado. ${deleteData ? 'Tablas RUTEA eliminadas tras doble confirmación.' : 'Tablas y datos DynamoDB conservados.'}`)
