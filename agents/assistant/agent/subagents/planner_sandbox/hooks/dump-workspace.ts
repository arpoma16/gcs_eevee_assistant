import { execFile } from "node:child_process";
import { mkdir, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { promisify } from "node:util";

import { defineHook, type HookContext } from "eve/hooks";

// eve borra el contenedor del sandbox (`docker rm -f`) cuando termina la sesión del planner, y no
// hay opción para retenerlo. Este hook copia /workspace al host al cerrar cada turno — también si
// falló o se canceló, que es cuando más hace falta ver qué dejó el modelo — para revisar los
// scripts, request.md y data/ después. No depende del provider: funciona igual con Docker o Vercel.
//
// Destino: <PLANNER_SANDBOX_DUMP_DIR o .eve/sandbox-dumps>/<sessionId>/, relativo al cwd del proceso
// (la app root del assistant bajo `eve dev`). Cada turno sobrescribe el dump de su sesión.
const DUMP_ROOT = resolve(process.env.PLANNER_SANDBOX_DUMP_DIR ?? ".eve/sandbox-dumps");
const ARCHIVE = "/tmp/planner-workspace.tar.gz";

const run = promisify(execFile);

async function dumpWorkspace(ctx: HookContext) {
  const sandbox = await ctx.getSandbox();
  // .eve/attachments son copias de adjuntos que eve ya guarda en el historial de la sesión.
  const pack = await sandbox.run({
    command: `tar -czf ${ARCHIVE} -C /workspace --exclude=./.eve --exclude=__pycache__ .`,
  });
  if (pack.exitCode !== 0) {
    throw new Error(`No se pudo empaquetar /workspace (exit ${pack.exitCode}): ${pack.stderr || pack.stdout}`);
  }
  const bytes = await sandbox.readBinaryFile({ path: ARCHIVE });
  if (bytes === null) throw new Error(`El sandbox no devolvió ${ARCHIVE}`);

  const dir = resolve(DUMP_ROOT, ctx.session.id);
  await rm(dir, { recursive: true, force: true });
  await mkdir(dir, { recursive: true });
  const archive = resolve(dir, "workspace.tar.gz");
  await writeFile(archive, bytes);
  await run("tar", ["-xzf", archive, "-C", dir]);
  console.info(`[planner_sandbox] workspace copiado a ${dir}`);
}

export default defineHook({
  events: {
    "turn.completed": (_event, ctx) => dumpWorkspace(ctx),
    "turn.failed": (_event, ctx) => dumpWorkspace(ctx),
    "turn.cancelled": (_event, ctx) => dumpWorkspace(ctx),
  },
});
