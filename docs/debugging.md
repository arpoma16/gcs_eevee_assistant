# Debuggear una sesión en vivo

Define cómo ver lo que hace un subagente (`planner` / `planner_sandbox`)
mientras corre, y cómo revisar su sandbox sin esperar a que termine.

## 0. La vía más simple: `planner_sandbox` como agente propio

`agents/planner_sandbox/` es una copia standalone del subagente (ver
[`agents/planner_sandbox/agent/AGENTS.md`](../agents/planner_sandbox/agent/AGENTS.md) para qué es y qué
no). `npm run dev:planner_sandbox` la levanta en `:2002` como agente raíz: le hablás directo, sin
delegación, sin `request_mission_plan`, sin el bug de `workflowId` (`issue2.md`). Cada script del pipeline
aparece como un tool call normal en la TUI en vez de quedar colapsado dentro del turno del padre. Para
hablarle desde `client/` en vez de la TUI: `npm run dev:client:planner_sandbox` (mismo patrón de pairing
que `dev`/`dev:assistant`, ver la tabla en el `AGENTS.md` de la raíz). Es la primera opción para reproducir
algo del pipeline en sí; recién si el problema es específico de la delegación o del turno del padre hace
falta el resto de esta guía.

## 1. Expandir la TUI de `eve dev`

Por default `eve dev` colapsa la sección de subagentes y el detalle de cada
tool call. Para verlos completos:

```bash
npx eve dev --agent assistant --subagents full --tools full --logs sandbox
```

| Flag | Qué hace |
| ---- | -------- |
| `--subagents full` | Expande el turno del subagente en el transcript: sus propios tool calls, no solo el resultado final que recibe el padre. |
| `--tools full` | Expande input/output de cada tool call — para `planner_sandbox`, la salida completa de cada `bash python3 pipeline/*.py`. |
| `--logs sandbox` | Agrega stdout/stderr del sandbox al log de la sesión (`/loglevel sandbox` también sirve una vez adentro de la TUI). |

Referencia completa de modos (`full` \| `collapsed` \| `auto-collapsed` \|
`hidden`) en `node_modules/eve/docs/reference/cli.md`, sección `eve dev`.

## 2. Leer los traces de una sesión

Los traces son los spans OTLP de la sesión (turnos, tool calls, subagentes),
persistidos en `.eve/traces/`:

```bash
npx eve traces ls
npx eve traces <traceid> --verbose
```

Si el trace es muy largo para leerlo en la terminal, redirigilo a un archivo:

```bash
npx eve traces <traceid> --agent assistant --verbose > /tmp/trace.txt
```

## 3. Leer los logs de diagnóstico

Los logs son otra cosa: stderr/stdout del proceso `eve dev` (incluye
`console.log` del sandbox, rebuilds y errores de workflow), persistidos en
`.eve/logs/`:

```bash
npx eve logs ls
npx eve logs <logid>
```

## 4. Limpiar `.eve/logs` y `.eve/traces`

Ambos directorios acumulan ruido entre corridas. Con `eve dev` parado, se
pueden borrar sin problema — se regeneran solos en la próxima sesión:

```bash
rm -rf .eve/logs .eve/traces
```

## 5. Meterse al sandbox mientras está corriendo

Ni `agent/sandbox/sandbox.ts` ni
[`agent/subagents/planner_sandbox/sandbox/sandbox.ts`](../agent/subagents/planner_sandbox/sandbox/sandbox.ts)
fijan un `backend`, así que eve usa `defaultBackend()`. En local, con Docker
alcanzable, eso resuelve a **Docker** (prioridad: Vercel Sandbox → Docker →
microsandbox → just-bash).

Cada sesión durable corre como un contenedor de larga vida que persiste
`/workspace` entre turnos — mientras la sesión del planner esté viva (así esté
a mitad del pipeline), el contenedor existe:

docker ps --filter "label=eve.sandbox.tag.sessionId=<sessionId>" --format "{{.ID}}" 
# 1. Solo los contenedores de eve (lo que pediste)
docker rm $(docker ps -a --filter "name=eve-sbx-" --filter "status=exited" -q)


```bash
docker ps --filter "name=eve-sbx"   # contenedores eve-sbx-<hash> vivos

# cada uno trae el sessionId (wrun_...) como label — mapealos todos de una:
for id in $(docker ps -q --filter "name=eve-sbx"); do
  sid=$(docker inspect "$id" --format '{{index .Config.Labels "eve.sandbox.tag.sessionId"}}')
  echo "$id -> $sid"
done

docker exec -it <container_id> bash

ls /workspace/data              # origin/devices/targets/obstacles/element_types.json
cat /workspace/data/element_types.json
ls /workspace/patterns          # ring.py + cualquier patrón custom que el modelo haya escrito
cat /workspace/data/mission.json  # si ya llegó al Step 5
```

El `sessionId` del label es el mismo `childSessionId` que ves en el panel del
subagente (`client/`) o en `eve traces` — así cruzás cuál contenedor
corresponde a la sesión que estás mirando sin adivinar por el `Up N minutes`.

Es lectura/escritura en vivo del mismo filesystem que ve el modelo. No le
edites archivos mientras el turno sigue corriendo — le pisarías el trabajo al
pipeline o al propio modelo.

Si el backend resuelto fuera otro:

- **microsandbox**: VM local, sin `docker exec` — no hay forma documentada de
  entrar en vivo; usar la TUI (§1) o el smoke test.
- **just-bash**: sin proceso real, filesystem virtual bajo
  `.eve/sandbox-cache/` en el host — se puede leer directo del disco.

## 6. Seguir el stream del subagente por API

Cada delegación abre su propio stream de sesión hija. El evento
`subagent.called` en el stream del padre trae `data.childSessionId`
([`docs/delegation.md`](delegation.md), sección "Seguir el progreso del
planner"):

```
GET /eve/v1/session/:childSessionId/stream
```

Es lo que usaría `client/` para mostrar la planificación en vivo en la UI del
operador, en vez de solo el resultado final vía task notification.

## 7. Correr el pipeline fuera del agente

Para reproducir un fallo del pipeline sin levantar ningún sandbox ni modelo,
ver "Correr el pipeline a mano" en [`docs/sandbox.md`](sandbox.md) — usa los
fixtures de [`examples/pipeline/`](../examples/pipeline/) y `MISSION_DATA_DIR`
para apuntar los scripts a un directorio cualquiera.

## 8. Cancelar el turno no mata el sandbox

Cancelar el turno de una sesión (`agent.cancel()` → `POST
/eve/v1/session/:sessionId/cancel`) **no** destruye su sandbox. El sandbox
está atado al ciclo de vida de la *sesión*, no del turno —
`node_modules/eve/docs/sandbox/index.mdx` ("## Lifecycle"): *"Session-owned
sandboxes persist across turns and deployments while their provider state
remains available."* El código de cancelación de turno
(`harness/turn-cancellation.js`, `execution/cancel-descendant-turns-step.js`,
etc.) nunca toca el sandbox; solo `sandbox.stop()`/`sandbox.delete()` lo
hacen, y ninguno de los dos corre en ese path.

En la práctica: si `planner_sandbox` se va por las ramas o está tirando
tokens de más, cancelá su turno con confianza — el contenedor y
`/workspace/data`/`/workspace/pipeline` quedan intactos para seguir
inspeccionándolos (§5) o para mandarle un turno nuevo a la misma sesión. Lo
único que se pierde al cancelar es la generación en curso y el turno del
padre que delegó (ver [`delegation.md`](delegation.md) — cancelar al hijo
resuelve el `await ctx.agent(...)` del padre, así que también termina su
turno; es el diseño de eve, no un efecto secundario del sandbox).

El cliente de test (`client/src/SubagentPanel.tsx`) ya se adjunta a la
sesión hija por su `sessionId` y tiene un botón "Ver archivos del sandbox"
que le pide al propio `planner_sandbox` que liste/lea sus archivos — sirve
igual antes o después de cancelar.
