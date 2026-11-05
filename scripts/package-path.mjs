import path from 'node:path'
import { existsSync, realpathSync } from 'node:fs'

// Serverless copies its .serverless directory to --package. Its target must
// never be that directory or a descendant, including via an existing symlink.
export function assertPackageDirectory(packageDir, serverlessDir) {
  const resolved = (value) => existsSync(value) ? realpathSync(value) : path.resolve(value)
  const source = resolved(serverlessDir)
  const target = resolved(packageDir)
  const relative = path.relative(source, target)
  if (!relative || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative))) {
    throw new Error('El directorio de paquete no puede estar dentro de .serverless')
  }
  return target
}

export function packageInvocation(sls, config, stage, region, packageDir, params) {
  const common = ['--config', config, '--stage', stage, '--region', region, '--package', packageDir, ...params]
  return { packageArgs: [sls, 'package', ...common], deployArgs: [sls, 'deploy', ...common], template: path.join(packageDir, 'cloudformation-template-update-stack.json') }
}
