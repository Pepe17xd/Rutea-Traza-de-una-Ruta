export const GENERIC_DEPLOY_ACTIONS = Object.freeze([
  'cloudformation:CreateStack', 'cloudformation:UpdateStack', 'cloudformation:DeleteStack', 'cloudformation:DescribeStacks', 'cloudformation:DescribeStackResources', 'cloudformation:CreateChangeSet', 'cloudformation:ExecuteChangeSet', 'cloudformation:DescribeChangeSet',
  'lambda:CreateFunction', 'lambda:GetFunction', 'lambda:UpdateFunctionCode', 'lambda:UpdateFunctionConfiguration', 'lambda:DeleteFunction', 'lambda:AddPermission', 'lambda:RemovePermission', 'lambda:TagResource', 'lambda:UntagResource',
  'apigateway:POST', 'apigateway:GET', 'apigateway:PATCH', 'apigateway:DELETE',
  'logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents', 'logs:PutRetentionPolicy',
  's3:CreateBucket', 's3:ListBucket', 's3:GetObject', 's3:PutObject', 's3:DeleteObject', 's3:GetBucketLocation', 's3:PutBucketTagging', 's3:GetBucketTagging',
])

export const passRoleSimulationArgs = (principalArn, roleArn, region) => [
  'iam', 'simulate-principal-policy',
  '--policy-source-arn', principalArn,
  '--action-names', 'iam:PassRole',
  '--resource-arns', roleArn,
  '--context-entries', 'ContextKeyName=iam:PassedToService,ContextKeyValues=lambda.amazonaws.com,ContextKeyType=string',
  '--region', region,
]

const tableArn = (region, accountId, tableName) => `arn:aws:dynamodb:${region}:${accountId}:table/${tableName}`

// Mirror DynamoRepository operations. Conditions are attached to Put/Update/
// Delete transaction items; it does not issue a separate ConditionCheck item.
export function dynamoRuntimeSimulationGroups(region, accountId, tableNames) {
  const missions = tableArn(region, accountId, tableNames.missions)
  const telemetry = tableArn(region, accountId, tableNames.telemetry)
  return [
    {
      label: 'DynamoDB missions table',
      actions: ['dynamodb:GetItem', 'dynamodb:PutItem', 'dynamodb:DeleteItem', 'dynamodb:Query', 'dynamodb:Scan'],
      resources: [missions],
    },
    {
      label: 'DynamoDB telemetry table',
      actions: ['dynamodb:GetItem', 'dynamodb:PutItem', 'dynamodb:UpdateItem', 'dynamodb:DeleteItem', 'dynamodb:Query'],
      resources: [telemetry],
    },
    {
      label: 'DynamoDB missions secondary index',
      actions: ['dynamodb:Query'],
      resources: [`${missions}/index/robot_created`],
    },
  ]
}

export function dynamoProvisioningSimulationGroups(region, accountId, tableNames, createTables) {
  const tables = Object.values(tableNames).map((name) => tableArn(region, accountId, name))
  const groups = [
    { label: 'DynamoDB DescribeTable', actions: ['dynamodb:DescribeTable'], resources: tables },
  ]
  if (createTables) {
    groups.push(
      { label: 'DynamoDB CreateTable', actions: ['dynamodb:CreateTable'], resources: ['*'] },
      { label: 'DynamoDB UpdateTimeToLive', actions: ['dynamodb:UpdateTimeToLive'], resources: tables },
      { label: 'DynamoDB TagResource', actions: ['dynamodb:TagResource'], resources: tables },
    )
  }
  return groups
}

export function deniedIamEvaluations(results, expectedActions) {
  const expected = new Set(expectedActions)
  const evaluations = (results || []).filter((entry) => expected.has(entry.EvalActionName))
  const found = new Set(evaluations.map((entry) => entry.EvalActionName))
  const denied = evaluations.filter((entry) => entry.EvalDecision !== 'allowed')
  for (const action of expected) {
    if (!found.has(action)) denied.push({ EvalActionName: action, EvalDecision: 'implicitDeny' })
  }
  return denied
}

export function formatIamSimulationError(error, label, actions, resources) {
  const details = error instanceof Error ? error.message : String(error)
  const context = `grupo=${label}; acciones=${actions.join(',')}; recursos=${resources.join(',')}`
  if (/InvalidInput|Invalid Input|ValidationError|MalformedInput/i.test(details)) {
    return `Solicitud IAM inválida para simulación (${context}). Revise la agrupación de acciones/ARN. Detalle: ${details}`
  }
  return `No se pudo consultar el simulador IAM (${context}); esto no equivale a una denegación de permisos. Detalle: ${details}`
}
