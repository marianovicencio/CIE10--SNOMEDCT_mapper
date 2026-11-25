import { spawn } from 'node:child_process'
import { join } from 'node:path'
import { normalizeCode, project } from '../utils/local'

let busy = false
export default defineEventHandler(async (event) => {
  setResponseHeader(event, 'Cache-Control', 'no-store')
  const origin = getHeader(event, 'origin')
  if (origin && !['http://localhost:3000', 'http://127.0.0.1:3000'].includes(origin))
    throw createError({ statusCode: 403, message: 'La búsqueda está disponible desde la interfaz local.' })
  if (!(getHeader(event, 'content-type') || '').startsWith('application/json'))
    throw createError({ statusCode: 415, message: 'Se requiere una consulta JSON.' })
  const raw = await readRawBody(event, 'utf8')
  if (!raw || Buffer.byteLength(raw) > 20000)
    throw createError({ statusCode: 400, message: 'Consulta vacía o demasiado larga.' })
  let body: { code?: unknown, diagnostic_text?: unknown }
  try { body = JSON.parse(raw) } catch { throw createError({ statusCode: 400, message: 'Consulta inválida.' }) }
  if (!body || typeof body !== 'object' || Array.isArray(body)) throw createError({ statusCode: 400, message: 'Consulta inválida.' })
  const code = normalizeCode(body.code)
  const diagnostic = body.diagnostic_text ?? ''
  if (typeof diagnostic !== 'string' || [...diagnostic].length > 4000)
    throw createError({ statusCode: 400, message: 'El diagnóstico admite hasta 4.000 caracteres.' })
  if (busy) throw createError({ statusCode: 429, message: 'Ya hay una búsqueda en curso. Intenta nuevamente cuando termine.' })
  busy = true
  try {
    return await new Promise((resolve, reject) => {
      const child = spawn(join(project, 'infra/retrieval/.venv/bin/python'), ['scripts/web/web_retrieval.py'], {
        cwd: project, env: { ...process.env, HF_HUB_OFFLINE: '1', OPENBLAS_NUM_THREADS: '4' },
        stdio: ['pipe', 'pipe', 'ignore']
      })
      let output = ''
      let forceStop: ReturnType<typeof setTimeout> | undefined
      function stopWorker() {
        if (forceStop) return
        child.kill('SIGTERM')
        forceStop = setTimeout(() => child.kill('SIGKILL'), 5000)
      }
      const timer = setTimeout(stopWorker, 150000)
      function clearTimers() {
        clearTimeout(timer)
        clearTimeout(forceStop)
      }
      child.stdin.on('error', () => {})
      child.stdout.setEncoding('utf8').on('data', (chunk: string) => {
        output += chunk
        if (output.length > 2_000_000) stopWorker()
      })
      child.on('error', () => {
        clearTimers()
        reject(createError({ statusCode: 503, message: 'El buscador local no está disponible.' }))
      })
      child.on('close', (exit) => {
        clearTimers()
        if (exit === 0) {
          try { return resolve(JSON.parse(output)) } catch { /* respuesta incompleta */ }
        }
        reject(createError({ statusCode: 503, message: 'No se pudo completar la búsqueda local. Revisa Snowstorm y vuelve a intentar.' }))
      })
      child.stdin.end(JSON.stringify({ code, ...(diagnostic.trim() ? { diagnostic_text: diagnostic } : {}) }))
    })
  } finally {
    busy = false
  }
})
