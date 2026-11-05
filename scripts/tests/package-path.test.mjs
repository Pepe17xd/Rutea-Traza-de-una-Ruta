import test from 'node:test'
import assert from 'node:assert/strict'
import path from 'node:path'
import { mkdtempSync, mkdirSync, rmSync, symlinkSync } from 'node:fs'
import os from 'node:os'
import { assertPackageDirectory, packageInvocation } from '../package-path.mjs'

test('rechaza .serverless y sus descendientes, acepta un directorio externo', () => {
  const root = path.resolve('project')
  const source = path.join(root, 'Backend', '.serverless')
  assert.throws(() => assertPackageDirectory(source, source), /dentro de .serverless/)
  assert.throws(() => assertPackageDirectory(path.join(source, 'academy-package'), source), /dentro de .serverless/)
  assert.equal(assertPackageDirectory(path.join(root, '.rutea-package-unique'), source), path.join(root, '.rutea-package-unique'))
})

test('plantilla validada y comandos package/deploy usan el mismo destino', () => {
  const target = path.resolve('project', '.rutea-package-unique')
  const calls = packageInvocation('sls', 'serverless.yml', 'academy', 'us-east-1', target, ['--param=x=true'])
  assert.equal(calls.packageArgs[calls.packageArgs.indexOf('--package') + 1], target)
  assert.equal(calls.deployArgs[calls.deployArgs.indexOf('--package') + 1], target)
  assert.equal(calls.template, path.join(target, 'cloudformation-template-update-stack.json'))
})

test('rechaza un destino que apunta mediante enlace al directorio .serverless', { skip: process.platform === 'win32' }, () => {
  const root = mkdtempSync(path.join(os.tmpdir(), 'rutea-package-test-'))
  try {
    const source = path.join(root, '.serverless')
    mkdirSync(source)
    const alias = path.join(root, 'alias')
    symlinkSync(source, alias, 'dir')
    assert.throws(() => assertPackageDirectory(alias, source), /dentro de .serverless/)
  } finally { rmSync(root, { recursive: true, force: true }) }
})
