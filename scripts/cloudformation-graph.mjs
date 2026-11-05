import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

export function validateGraph(template) {
  const resources = template.Resources || {}
  const graph = new Map(Object.keys(resources).map((id) => [id, new Set()]))
  const visit = (value, edges) => {
    if (Array.isArray(value)) { value.forEach((item) => visit(item, edges)); return }
    if (!value || typeof value !== 'object') return
    if (typeof value.Ref === 'string' && graph.has(value.Ref)) edges.add(value.Ref)
    const getAtt = value['Fn::GetAtt']
    const target = Array.isArray(getAtt) ? getAtt[0] : typeof getAtt === 'string' ? getAtt.split('.')[0] : null
    if (graph.has(target)) edges.add(target)
    const sub = value['Fn::Sub']
    const text = Array.isArray(sub) ? sub[0] : sub
    const overrides = Array.isArray(sub) ? sub[1] || {} : {}
    if (typeof text === 'string') for (const match of text.matchAll(/\$\{([^}]+)\}/g)) {
      const name = match[1].split('.')[0]
      if (!match[1].startsWith('!') && !(name in overrides) && graph.has(name)) edges.add(name)
    }
    Object.values(value).forEach((item) => visit(item, edges))
  }
  for (const [id, resource] of Object.entries(resources)) {
    const edges = graph.get(id)
    for (const dep of [resource.DependsOn].flat().filter(Boolean)) if (graph.has(dep)) edges.add(dep)
    visit(resource.Properties, edges)
    visit(resource.Metadata, edges)
    visit(resource.CreationPolicy, edges)
    visit(resource.UpdatePolicy, edges)
  }
  const active = new Set(), done = new Set(), stack = []
  const walk = (id) => {
    if (active.has(id)) throw new Error(`Dependencia circular CloudFormation: ${[...stack, id].join(' -> ')}`)
    if (done.has(id)) return
    active.add(id); stack.push(id)
    for (const dep of graph.get(id)) walk(dep)
    stack.pop(); active.delete(id); done.add(id)
  }
  for (const id of graph.keys()) walk(id)
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (!process.argv[2]) throw new Error('Indique el archivo JSON CloudFormation generado por Serverless')
  validateGraph(JSON.parse(readFileSync(process.argv[2], 'utf8')))
  console.log('Grafo CloudFormation generado: sin ciclos detectados.')
}
