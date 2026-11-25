import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { join } from 'node:path'
import { project } from '../utils/local'
const execute = promisify(execFile)
export default defineEventHandler(async (event) => {
  setResponseHeader(event, 'Cache-Control', 'no-store')
  try {
    const { stdout } = await execute(join(project, '.venv/bin/python'), ['scripts/web/web_retrieval.py', '--catalog'], {
      cwd: project, timeout: 5000, maxBuffer: 100000
    })
    const data = JSON.parse(stdout)
    if (!Number.isInteger(data.concepts) || !Number.isInteger(data.aliases)) throw new Error('invalid catalog')
    return data as { name: string, concepts: number, aliases: number, version: string, coverage: string }
  } catch {
    throw createError({ statusCode: 503, message: 'No se pudo verificar el catálogo activo.' })
  }
})
