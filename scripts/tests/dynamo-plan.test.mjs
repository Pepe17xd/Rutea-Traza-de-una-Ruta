import test from 'node:test'
import assert from 'node:assert/strict'
import { planTables } from '../dynamo-plan.mjs'
const names = { missions: 'm', telemetry: 't' }
function aws(existing, owned = []) {
  return (args) => {
    if (args[1] === 'describe-stacks') return { Stacks: [{ StackStatus: 'UPDATE_COMPLETE' }] }
    if (args[1] === 'describe-stack-resources') return { StackResources: owned.map((item) => ({ ResourceStatus: 'CREATE_COMPLETE', ...item })) }
    if (args[1] === 'describe-table') {
      if (!existing.includes(args[args.indexOf('--table-name') + 1])) throw new Error('ResourceNotFoundException')
      return { Table: {} }
    }
    throw new Error('unexpected call')
  }
}
test('conserva tabla externa y crea solo la ausente autorizada', () => {
  const plan = planTables({ names, stage: 'academy', region: 'us-east-1', createAllowed: true, awsJson: aws(['m']) })
  assert.equal(plan.missions.declare, false)
  assert.equal(plan.telemetry.create, true)
})
test('mantiene declarada la tabla que ya administra el stack', () => {
  const plan = planTables({ names, stage: 'academy', region: 'us-east-1', createAllowed: true, awsJson: aws(['m'], [{ LogicalResourceId: 'MissionsTable', PhysicalResourceId: 'm' }]) })
  assert.equal(plan.missions.managed, true)
  assert.equal(plan.missions.declare, true)
})
test('rechaza tabla ausente sin autorizacion o cambio de nombre administrado', () => {
  assert.throws(() => planTables({ names, stage: 'academy', region: 'us-east-1', createAllowed: false, awsJson: aws(['m']) }), /Falta t/)
  assert.throws(() => planTables({ names, stage: 'academy', region: 'us-east-1', createAllowed: true, awsJson: aws(['m'], [{ LogicalResourceId: 'MissionsTable', PhysicalResourceId: 'other' }]) }), /reemplazo/)
})
