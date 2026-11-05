import test from 'node:test'
import assert from 'node:assert/strict'
import { validateGraph } from '../cloudformation-graph.mjs'

test('detecta ciclo entre log group y funcion mediante DependsOn y Sub', () => {
  assert.throws(() => validateGraph({ Resources: {
    ApiLambdaFunction: { DependsOn: 'ApiLogGroup' },
    ApiLogGroup: { Properties: { LogGroupName: { 'Fn::Sub': '/aws/lambda/${ApiLambdaFunction}' } } },
  } }), /Dependencia circular/)
})
test('admite log group nombrado sin referencia a funcion', () => {
  assert.doesNotThrow(() => validateGraph({ Resources: {
    ApiLambdaFunction: { DependsOn: 'ApiLogGroup' },
    ApiLogGroup: { Properties: { LogGroupName: '/aws/lambda/rutea-api-academy-api' } },
  } }))
})
test('detecta ciclos con Ref y GetAtt', () => {
  assert.throws(() => validateGraph({ Resources: { A: { Properties: { Value: { Ref: 'B' } } }, B: { Properties: { Value: { 'Fn::GetAtt': ['A', 'Arn'] } } } } }), /circular/)
})
