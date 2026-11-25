import { spawn } from 'node:child_process'
import { join } from 'node:path'
import { normalizeCode, project } from '../utils/local'

let busy = false

export default defineEventHandler(async (event) => {
  setResponseHeader(event, 'Cache-Control', 'no-store')
  const origin = getHeader(event, 'origin')
  if (origin && !['http://localhost:3000', 'http://127.0.0.1:3000'].includes(origin))
    throw createError({ statusCode: 403, message: 'La revisión está disponible desde la interfaz local.' })
  if (!(getHeader(event, 'content-type') || '').startsWith('application/json'))
    throw createError({ statusCode: 415, message: 'Se requiere una consulta JSON.' })
  const raw = await readRawBody(event, 'utf8')
  if (!raw || Buffer.byteLength(raw) > 20000)
    throw createError({ statusCode: 400, message: 'Consulta vacía o demasiado larga.' })
  let body: Record<string, unknown>
  try { body = JSON.parse(raw) } catch { throw createError({ statusCode: 400, message: 'Consulta inválida.' }) }
  const fields = ['code', 'concept_ids', 'diagnostic_text', 'source_snapshot_sha256', 'target_version']
  if (!body || typeof body !== 'object' || Array.isArray(body) || Object.keys(body).some(key => !fields.includes(key)))
    throw createError({ statusCode: 400, message: 'Consulta inválida.' })
  const code = normalizeCode(body.code)
  if (!Array.isArray(body.concept_ids) || body.concept_ids.length < 1 || body.concept_ids.length > 5 || body.concept_ids.some(id => typeof id !== 'string' || !/^[0-9]{6,18}$/.test(id)) || new Set(body.concept_ids).size !== body.concept_ids.length
    || typeof body.source_snapshot_sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(body.source_snapshot_sha256)
    || body.target_version !== 'http://snomed.info/sct/449081005/version/20261110')
    throw createError({ statusCode: 400, message: 'Faltan el candidato o las versiones de la consulta. Repite la búsqueda.' })
  const diagnostic = body.diagnostic_text ?? ''
  if (typeof diagnostic !== 'string' || [...diagnostic].length > 4000)
    throw createError({ statusCode: 400, message: 'El diagnóstico admite hasta 4.000 caracteres.' })
  if (busy) throw createError({ statusCode: 429, message: 'Hay una revisión contextual en curso. Intenta de nuevo cuando termine.' })
  busy = true
  try {
    return await new Promise((resolve, reject) => {
      const child = spawn(join(project, '.venv/bin/python'), ['scripts/web/web_candidate_review.py'], {
        cwd: project, stdio: ['pipe', 'pipe', 'ignore']
      })
      let output = ''
      let forceStop: ReturnType<typeof setTimeout> | undefined
      function stopWorker() {
        if (forceStop) return
        child.kill('SIGTERM')
        forceStop = setTimeout(() => child.kill('SIGKILL'), 8000)
      }
      const timer = setTimeout(stopWorker, 120000)
      const onDisconnect = () => { if (!event.node.res.writableEnded) stopWorker() }
      event.node.res.on('close', onDisconnect)
      function clear() {
        clearTimeout(timer)
        clearTimeout(forceStop)
        event.node.res.off('close', onDisconnect)
      }
      child.stdin.on('error', () => {})
      child.stdout.setEncoding('utf8').on('data', (chunk: string) => {
        output += chunk
        if (output.length > 2_000_000) stopWorker()
      })
      child.on('error', () => {
        clear()
        reject(createError({ statusCode: 503, message: 'No se pudo iniciar el contraste contextual.' }))
      })
      child.on('close', (exit) => {
        clear()
        if (exit === 0) {
          try { return resolve(JSON.parse(output)) } catch { /* respuesta incompleta */ }
        }
        reject(createError({ statusCode: 503, message: 'El contraste contextual se interrumpió. Puedes volver a intentarlo.' }))
      })
      child.stdin.end(JSON.stringify({ ...body, code, diagnostic_text: diagnostic }))
    })
  } finally {
    busy = false
  }
})
