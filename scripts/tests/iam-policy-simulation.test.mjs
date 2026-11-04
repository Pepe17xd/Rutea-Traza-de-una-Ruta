import assert from 'node:assert/strict'
import test from 'node:test'
import {
  deniedIamEvaluations,
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
