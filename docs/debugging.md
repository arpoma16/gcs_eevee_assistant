# Debuggear una sesión en vivo

Define cómo ver lo que hace un subagente (`planner` / `planner_sandbox`)
mientras corre, y cómo revisar su sandbox sin esperar a que termine.

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

## 2. Meterse al sandbox mientras está corriendo

Ni `agent/sandbox/sandbox.ts` ni
[`agent/subagents/planner_sandbox/sandbox/sandbox.ts`](../agent/subagents/planner_sandbox/sandbox/sandbox.ts)
fijan un `backend`, así que eve usa `defaultBackend()`. En local, con Docker
alcanzable, eso resuelve a **Docker** (prioridad: Vercel Sandbox → Docker →
microsandbox → just-bash).

Cada sesión durable corre como un contenedor de larga vida que persiste
`/workspace` entre turnos — mientras la sesión del planner esté viva (así esté
a mitad del pipeline), el contenedor existe:

```bash
docker ps                       # buscá el contenedor (imagen ghcr.io/vercel/eve)
docker exec -it <container_id> bash

ls /workspace/data              # origin/devices/targets/obstacles/element_types.json
cat /workspace/data/element_types.json
ls /workspace/patterns          # ring.py + cualquier patrón custom que el modelo haya escrito
cat /workspace/data/mission.json  # si ya llegó al Step 5
```

Es lectura/escritura en vivo del mismo filesystem que ve el modelo. No le
edites archivos mientras el turno sigue corriendo — le pisarías el trabajo al
pipeline o al propio modelo.

Si el backend resuelto fuera otro:

- **microsandbox**: VM local, sin `docker exec` — no hay forma documentada de
  entrar en vivo; usar la TUI (§1) o el smoke test.
- **just-bash**: sin proceso real, filesystem virtual bajo
  `.eve/sandbox-cache/` en el host — se puede leer directo del disco.

## 3. Seguir el stream del subagente por API

Cada delegación abre su propio stream de sesión hija. El evento
`subagent.called` en el stream del padre trae `data.childSessionId`
([`docs/delegation.md`](delegation.md), sección "Seguir el progreso del
planner"):

```
GET /eve/v1/session/:childSessionId/stream
```

Es lo que usaría `client/` para mostrar la planificación en vivo en la UI del
operador, en vez de solo el resultado final vía task notification.

## 4. Correr el pipeline fuera del agente

Para reproducir un fallo del pipeline sin levantar ningún sandbox ni modelo,
ver "Correr el pipeline a mano" en [`docs/sandbox.md`](sandbox.md) — usa los
fixtures de [`examples/pipeline/`](../examples/pipeline/) y `MISSION_DATA_DIR`
para apuntar los scripts a un directorio cualquiera.
