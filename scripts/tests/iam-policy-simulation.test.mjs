import assert from 'node:assert/strict'
import test from 'node:test'
import {
  deniedIamEvaluations,
  dynamoProvisioningSimulationGroups,
  dynamoRuntimeSimulationGroups,
  formatIamSimulationError,
  GENERIC_DEPLOY_ACTIONS,
  passRoleSimulationArgs,
} from '../iam-policy-simulation.mjs'

test('a PassRole result of allowed clears the preflight check', () => {
  assert.deepEqual(deniedIamEvaluations([
    { EvalActionName: 'iam:PassRole', EvalDecision: 'allowed', MissingContextValues: [] },
  ], ['iam:PassRole']), [])
})

test('implicitDeny remains a blocking permission result', () => {
  assert.deepEqual(deniedIamEvaluations([
    { EvalActionName: 'iam:PassRole', EvalDecision: 'implicitDeny', MissingContextValues: [] },
  ], ['iam:PassRole']).map(({ EvalDecision }) => EvalDecision), ['implicitDeny'])
})

test('explicitDeny remains a blocking permission result', () => {
  assert.deepEqual(deniedIamEvaluations([
    { EvalActionName: 'iam:PassRole', EvalDecision: 'explicitDeny', MissingContextValues: [] },
  ], ['iam:PassRole']).map(({ EvalDecision }) => EvalDecision), ['explicitDeny'])
})

test('generic deploy simulation excludes PassRole', () => {
  assert.equal(GENERIC_DEPLOY_ACTIONS.includes('iam:PassRole'), false)
  assert.equal(GENERIC_DEPLOY_ACTIONS.some((action) => action.startsWith('dynamodb:')), false)
})

test('PassRole simulation uses exact LabRole ARN and Lambda service context', () => {
  const args = passRoleSimulationArgs(
    'arn:aws:iam::521119692025:role/voclabs',
    'arn:aws:iam::521119692025:role/LabRole',
    'us-east-1',
  )
  assert.deepEqual(args, [
    'iam', 'simulate-principal-policy',
    '--policy-source-arn', 'arn:aws:iam::521119692025:role/voclabs',
    '--action-names', 'iam:PassRole',
    '--resource-arns', 'arn:aws:iam::521119692025:role/LabRole',
    '--context-entries', 'ContextKeyName=iam:PassedToService,ContextKeyValues=lambda.amazonaws.com,ContextKeyType=string',
    '--region', 'us-east-1',
  ])
})

const tableNames = { missions: 'rutea-academy-missions', telemetry: 'rutea-academy-telemetry' }
const missionsArn = 'arn:aws:dynamodb:us-east-1:521119692025:table/rutea-academy-missions'
const telemetryArn = 'arn:aws:dynamodb:us-east-1:521119692025:table/rutea-academy-telemetry'

test('runtime DynamoDB actions are grouped by exact table resource', () => {
  const groups = dynamoRuntimeSimulationGroups('us-east-1', '521119692025', tableNames)
  assert.deepEqual(groups[0], {
    label: 'DynamoDB missions table',
    actions: ['dynamodb:GetItem', 'dynamodb:PutItem', 'dynamodb:DeleteItem', 'dynamodb:Query', 'dynamodb:Scan'],
    resources: [missionsArn],
  })
  assert.deepEqual(groups[1], {
    label: 'DynamoDB telemetry table',
    actions: ['dynamodb:GetItem', 'dynamodb:PutItem', 'dynamodb:UpdateItem', 'dynamodb:DeleteItem', 'dynamodb:Query'],
    resources: [telemetryArn],
  })
})

test('secondary index query is simulated separately against its exact index ARN', () => {
  const groups = dynamoRuntimeSimulationGroups('us-east-1', '521119692025', tableNames)
  assert.deepEqual(groups[2], {
    label: 'DynamoDB missions secondary index',
    actions: ['dynamodb:Query'],
    resources: [`${missionsArn}/index/robot_created`],
  })
})

test('runtime policy does not request unsupported transaction or unused ConditionCheck actions', () => {
  const actions = dynamoRuntimeSimulationGroups('us-east-1', '521119692025', tableNames).flatMap((group) => group.actions)
  assert.equal(actions.includes('dynamodb:TransactWriteItems'), false)
  assert.equal(actions.includes('dynamodb:ConditionCheckItem'), false)
})

test('table provisioning actions use separate resource groups', () => {
  const groups = dynamoProvisioningSimulationGroups('us-east-1', '521119692025', tableNames, true)
  assert.deepEqual(groups, [
    { label: 'DynamoDB DescribeTable', actions: ['dynamodb:DescribeTable'], resources: [missionsArn, telemetryArn] },
    { label: 'DynamoDB CreateTable', actions: ['dynamodb:CreateTable'], resources: ['*'] },
    { label: 'DynamoDB UpdateTimeToLive', actions: ['dynamodb:UpdateTimeToLive'], resources: [missionsArn, telemetryArn] },
    { label: 'DynamoDB TagResource', actions: ['dynamodb:TagResource'], resources: [missionsArn, telemetryArn] },
  ])
  assert.deepEqual(dynamoProvisioningSimulationGroups('us-east-1', '521119692025', tableNames, false), [groups[0]])
})

test('invalid simulator requests are distinguished from permission denials', () => {
  const invalid = formatIamSimulationError(new Error('InvalidInput: Invalid Input Actions'), 'DynamoDB table', ['dynamodb:GetItem'], [missionsArn])
  const unavailable = formatIamSimulationError(new Error('AccessDenied'), 'DynamoDB table', ['dynamodb:GetItem'], [missionsArn])
  assert.match(invalid, /Solicitud IAM inválida/)
  assert.match(unavailable, /no equivale a una denegación/)
})
