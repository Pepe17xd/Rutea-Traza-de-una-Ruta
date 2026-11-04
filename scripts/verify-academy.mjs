import path from 'node:path'
import { awsJson, root } from './lib.mjs'

const args = process.argv.slice(2)
if (args.includes('--dry-run') || args.includes('--plan-only')) {
  console.log('Verify dry-run: lee output HTTPS del stack RUTEA, consulta frontend, assets JS/CSS y /api/v1/health. No llama AWS ni HTTP.')
  process.exit(0)
}
const region = process.env.AWS_REGION || 'us-east-1'
const stage = args.find((arg) => arg.startsWith('--stage='))?.split('=')[1] || process.env.AWS_STAGE || 'academy'
const stackName = `rutea-api-${stage}`
const stack = awsJson(['cloudformation', 'describe-stacks', '--stack-name', stackName, '--region', region]).Stacks?.[0]
if (!stack) throw new Error(`No se encontró stack ${stackName}`)
const value = (key) => {
  const output = stack.Outputs?.find((item) => item.OutputKey === key)?.OutputValue
  if (!output) throw new Error(`El stack no publicó ${key}`)
  return output
}
const frontendUrl = value('FrontendUrl')
const apiBase = value('ApiBaseUrl')
if (!frontendUrl.startsWith('https://') || new URL(apiBase).origin !== new URL(frontendUrl).origin) throw new Error('Frontend y API deben compartir origen HTTPS.')
const get = async (url) => {
  const response = await fetch(url, { signal: AbortSignal.timeout(20000) })
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`)
  return response
}
const page = await get(frontendUrl)
const html = await page.text()
if (!html.includes('RUTEA')) throw new Error('La respuesta principal no contiene RUTEA.')
const assets = [...html.matchAll(/(?:src|href)="([^"]+\.(?:js|css))"/g)].map((match) => new URL(match[1], frontendUrl).href)
if (!assets.length) throw new Error('No hay bundles JS/CSS en la respuesta SPA.')
for (const asset of assets) {
  const response = await get(asset)
  const body = await response.text()
  if (/https?:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?/i.test(body)) throw new Error(`Asset ${asset} contiene localhost/127.0.0.1.`)
}
const health = await get(`${apiBase}/health`)
const payload = await health.json()
if (payload.status !== 'ok') throw new Error(`Health respondió contenido inesperado: ${JSON.stringify(payload)}`)
console.log('Verificación remota aprobada:')
console.log(`- Frontend RUTEA: ${frontendUrl}`)
console.log(`- Bundles servidos por HTTPS: ${assets.length}`)
console.log(`- API health: ${apiBase}/health (HTTP ${health.status})`)
console.log('- Origen único API/SPA; no requiere CORS para el cliente web.')
