import { spawnSync } from 'node:child_process'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { root, run } from './lib.mjs'

const git = spawnSync('git', ['rev-parse', '--show-toplevel'], { cwd: root, encoding: 'utf8' })
const inRepo = git.status === 0
let files
if (inRepo) {
  const listed = spawnSync('git', ['ls-files', '--cached', '--others', '--exclude-standard', '-z'], { cwd: root, encoding: 'utf8' })
  if (listed.status !== 0) throw new Error('No fue posible enumerar archivos versionados y candidatos a commit.')
  files = listed.stdout.split('\0').filter(Boolean)
} else {
  files = []
  const visit = (directory) => {
    for (const entry of readdirSync(directory)) {
      if (['.git', 'node_modules', '.venv', '.pio', 'dist', '.serverless', 'data', 'artifacts', '__pycache__'].includes(entry)) continue
      const absolute = path.join(directory, entry)
      const relative = path.relative(root, absolute)
      if (entry === '.env' || entry.startsWith('.env.')) continue
      if (statSync(absolute).isDirectory()) visit(absolute)
      else if (statSync(absolute).size < 2_000_000) files.push(relative)
    }
  }
  visit(root)
}

const sensitivePath = /(^|\/)(\.env(\.(?!example$).*)?|\.env|\.aws|secrets?\.(?!example\.)[^/]+|[^/]*credentials[^/]*)$/i
const secretPatterns = [
  /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/,
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,
  /(?:AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN|HECTOR_(?:OPERATOR|DEVICE)_TOKEN)[ \t]*[:=][ \t]*["']?([A-Za-z0-9/+=_-]{24,})/i,
]
const findings = []
for (const file of files) {
  if (!/(^|\/)(\.env\.example|secrets?\.example\.[^/]+)$/i.test(file.replaceAll('\\', '/')) && sensitivePath.test(file.replaceAll('\\', '/'))) findings.push(`${file}: ruta sensible versionada`) // no contents emitted
  try {
    const content = readFileSync(path.join(root, file), 'utf8')
    if (secretPatterns.some((pattern) => pattern.test(content))) findings.push(`${file}: posible credencial o clave privada`)
  } catch { /* binaries or unreadable files are ignored; path checks still apply */ }
}
if (findings.length) {
  console.error('BLOQUEO: revisar posibles secretos (sus valores no se muestran):')
  for (const finding of [...new Set(findings)]) console.error(`- ${finding}`)
  process.exit(2)
}
console.log(`Auditoría de contenido: sin patrones de credenciales en ${files.length} archivos.`)
if (!inRepo) console.log('Aviso: esta carpeta aún no es un repositorio Git; no se pudo auditar el índice ni el historial. No se creó un repositorio automáticamente.')
else {
  const commits = spawnSync('git', ['rev-list', '--all'], { cwd: root, encoding: 'utf8' })
  if (commits.status !== 0) console.log('Aviso: no se pudo inspeccionar el historial Git completo.')
  else {
    const revisions = commits.stdout.split(/\r?\n/).filter(Boolean)
    if (revisions.length > 500) console.log(`Aviso: ${revisions.length} commits; escaneo de blobs omitido por seguridad de tiempo. Ejecutar gitleaks antes de publicar.`)
    else {
      const pattern = "(AKIA[[:alnum:]]{16}|ASIA[[:alnum:]]{16}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----|(AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN|HECTOR_OPERATOR_TOKEN|HECTOR_DEVICE_TOKEN|HECTOR_SESSION_SIGNING_KEY)[[:space:]]*[:=][[:space:]]*['\"]?[A-Za-z0-9/+=_-]{24,}|HECTOR_OPERATOR_PASSWORD_HASH[[:space:]]*[:=][[:space:]]*['\"]?\\$argon2id\\$[[:alnum:]/+=_$-]{30,})"
      const historical = new Set()
      for (const revision of revisions) {
        const found = spawnSync('git', ['grep', '-I', '-l', '-E', pattern, revision, '--'], { cwd: root, encoding: 'utf8' })
        if (found.status === 0) for (const file of found.stdout.split(/\r?\n/).filter(Boolean)) historical.add(`${revision.slice(0, 8)}:${file.split(':').at(-1)}`)
        else if (found.status !== 1) { console.log('Aviso: una revisión no pudo escanearse; validar con gitleaks antes de publicar.'); break }
      }
      if (historical.size) {
        console.error('BLOQUEO: posibles secretos detectados en blobs históricos (sin mostrar valores):')
        for (const entry of historical) console.error(`- ${entry}`)
        process.exit(2)
      }
      console.log(`Escaneo histórico de blobs: sin patrones de credenciales en ${revisions.length} commits.`)
    }
  }
}
