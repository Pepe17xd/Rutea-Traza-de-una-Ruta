export const GENERIC_DEPLOY_ACTIONS = Object.freeze([
  'cloudformation:CreateStack', 'cloudformation:UpdateStack', 'cloudformation:DeleteStack', 'cloudformation:DescribeStacks', 'cloudformation:CreateChangeSet', 'cloudformation:ExecuteChangeSet', 'cloudformation:DescribeChangeSet',
  'lambda:CreateFunction', 'lambda:GetFunction', 'lambda:UpdateFunctionCode', 'lambda:UpdateFunctionConfiguration', 'lambda:DeleteFunction', 'lambda:AddPermission', 'lambda:RemovePermission', 'lambda:TagResource', 'lambda:UntagResource',
  'apigateway:POST', 'apigateway:GET', 'apigateway:PATCH', 'apigateway:DELETE',
  'logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents', 'logs:PutRetentionPolicy',
  's3:CreateBucket', 's3:ListBucket', 's3:GetObject', 's3:PutObject', 's3:DeleteObject', 's3:GetBucketLocation', 's3:PutBucketTagging', 's3:GetBucketTagging',
  'dynamodb:DescribeTable', 'dynamodb:GetItem', 'dynamodb:PutItem', 'dynamodb:UpdateItem', 'dynamodb:DeleteItem', 'dynamodb:Query', 'dynamodb:Scan', 'dynamodb:TransactWriteItems',
])

export const passRoleSimulationArgs = (principalArn, roleArn, region) => [
  'iam', 'simulate-principal-policy',
  '--policy-source-arn', principalArn,
  '--action-names', 'iam:PassRole',
  '--resource-arns', roleArn,
  '--context-entries', 'ContextKeyName=iam:PassedToService,ContextKeyValues=lambda.amazonaws.com,ContextKeyType=string',
  '--region', region,
]

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
