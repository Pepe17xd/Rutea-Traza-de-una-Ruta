// Read-only inspection. Existing unmanaged tables are never adopted or recreated.
export function planTables({ names, stage, region, createAllowed, awsJson }) {
  if (!names.missions || !names.telemetry || names.missions === names.telemetry) throw new Error('Las tablas de misiones y telemetria deben tener nombres distintos')
  const stackName = `rutea-api-${stage}`
  let stackExists = true
  try {
    const stack = awsJson(['cloudformation', 'describe-stacks', '--stack-name', stackName, '--region', region]).Stacks?.[0]
    if (!stack || !['CREATE_COMPLETE', 'UPDATE_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE'].includes(stack.StackStatus)) throw new Error(`Estado de stack no apto para actualizacion: ${stack?.StackStatus || 'desconocido'}`)
  }
  catch (error) {
    if (/ValidationError.*does not exist|Stack with id .* does not exist/i.test(error.message)) stackExists = false
    else throw new Error(`No se pudo inspeccionar ${stackName}: ${error.message}`)
  }
  const owned = new Map()
  if (stackExists) {
    const result = awsJson(['cloudformation', 'describe-stack-resources', '--stack-name', stackName, '--region', region])
    for (const entry of result.StackResources || []) {
      if (entry.ResourceStatus === 'DELETE_COMPLETE') continue
      if (['MissionsTable', 'TelemetryTable'].includes(entry.LogicalResourceId) && !/^(CREATE|UPDATE|IMPORT)_COMPLETE$/.test(entry.ResourceStatus || '')) throw new Error(`Estado no apto de ${entry.LogicalResourceId}: ${entry.ResourceStatus || 'desconocido'}`)
      owned.set(entry.LogicalResourceId, entry.PhysicalResourceId)
    }
  }
  const result = {}
  for (const [kind, logical] of [['missions', 'MissionsTable'], ['telemetry', 'TelemetryTable']]) {
    const name = names[kind]
    let exists = true
    try { awsJson(['dynamodb', 'describe-table', '--table-name', name, '--region', region]) }
    catch (error) {
      if (/ResourceNotFoundException|ResourceNotFound/.test(error.message)) exists = false
      else throw new Error(`No se pudo inspeccionar tabla ${name}: ${error.message}`)
    }
    const physical = owned.get(logical)
    if (physical && physical !== name) throw new Error(`El stack administra ${logical} como ${physical}, no ${name}; se rechaza reemplazo`)
    if (physical && !exists) throw new Error(`El stack administra ${name}, pero la tabla no existe; revise el estado antes de desplegar`)
    if (!exists && !createAllowed) throw new Error(`Falta ${name}. Configure RUTEA_CREATE_DYNAMO_TABLES=true solo si autoriza su creacion y el laboratorio permite crearla.`)
    result[kind] = { name, exists, managed: Boolean(physical), create: !exists, declare: Boolean(physical) || !exists }
  }
  return result
}
