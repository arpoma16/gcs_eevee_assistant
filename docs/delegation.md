# Delegación y resultados asíncronos (operador → planner)

Define cómo el agente principal delega en el subagente `planner` y cómo el
resultado vuelve. Reemplaza el rebote por REST del orquestador viejo
(`request_mission_plan` MCP → `POST /chat/subagents`) por delegación nativa de
eve, conservando la semántica — que es la parte que ya funcionaba.

## Modelo: asíncrono

La delegación **no bloquea** el turno del padre:

```
Agente operador                            Subagente planner
───────────────                            ─────────────────
turno N:
  get_registered_objects, get_devices…
  request_mission_plan(schema) ─────────▶  se crea sesión hija
  ← receipt {status:"working", taskId}       recibe el briefing YA en XYZ
  text "Generando la misión…"                5 pasos + validate_mission
  [turno N termina]                                 │
                                                    │
turno N+1 (task notification):    ◀──────── resultado (éxito o error)
  show_mission_to_user(missionPlanId)      la sesión hija queda parkeada
  text "Plan listo: 2 rutas, sin colisiones…"
```

El operador puede seguir conversando entre el turno N y el N+1. eve además
instruye al modelo por su cuenta a *"acknowledge that the work started without
waiting for results"* cuando acepta una task en background.

## La tool de delegación: `request_mission_plan`

No es la tool nativa de subagente (`{message}` y nada más), sino un
**background workflow tool** propio —
[`agent/tools/request_mission_plan.ts`](../agent/tools/request_mission_plan.ts):

```ts
defineWorkflowTool({
  execution: "background",        // receipt inmediato, el padre sigue libre
  inputSchema: z.object({ … }),   // el contrato que el modelo debe cumplir
  async execute(input, ctx) {
    "use workflow";
    const briefing = await resolveBriefing(…);   // "use step": efectos afuera del body
    return await ctx.agent("planner", { message: briefing });
  },
});
```

Por qué así y no la tool nativa: **el schema es el contrato**. La tool nativa
acepta un `message` de texto libre, y nada obliga al modelo a incluir los datos
correctos. Con `inputSchema` el modelo ve los campos y eve rechaza la llamada
malformada — igual que el `requestMissionPlanSchema` del mcp_server.

| Campo | Qué lleva |
| ----- | --------- |
| `user_request` | La intención del usuario, en sus palabras. |
| `mission_strategy` | `simple` \| `circular` \| `detailed` \| `custom`. |
| `mission_strategy_description` | El briefing operacional completo, terminando con el bloque `MISSION PARAMETERS` verbatim. |
| `targets` / `targets_length` | Los elementos a inspeccionar (`id`, `name`, `type`, `group`) y su cuenta declarada, que debe coincidir. |
| `selected_devices` | Solo los drones que van a volar (`id`, `name`, `category`, `battery_level`). |

**Nada de coordenadas.** El modelo pasa ids y nombres; el paso
`resolveBriefing` llama a `POST /missions/convert/geodetic-to-xyz` del GCS, que:

1. Resuelve cada drone contra la DB por nombre y cruza `id` + `category`.
2. Resuelve cada target contra el catálogo por `id` y cruza name/group/type.
3. Calcula el origen local y convierte todo a ENU/XYZ.
4. Resuelve obstáculos del catálogo y calcula los boundaries de la misión.
5. Rechaza la misión si algún drone queda más lejos del límite de todo target.

Es el **único punto donde lo que el modelo afirma se contrasta con los datos
reales**: un id inventado se rechaza acá, y el error vuelve al padre, que sí
tiene las tools para corregirlo. El briefing XYZ resultante nunca pasa por el
contexto del padre — se arma dentro del executor y va directo al subagente, con
las secciones (`## global_origin_coordinates`, `## Elements to Inspect`,
`## obstacles Information`, `## boundaries`) codificadas en TOON, que es el
formato que el Step 1 del planner espera leer.

Ojo con un matiz del modo background: la validación de **schema** (campos
faltantes o mal tipados) rechaza al instante, pero las validaciones
**semánticas** —`targets_length` que no cuadra, un id que no existe— ocurren
dentro del executor y llegan como *fallo de la task*, no como rechazo inmediato
de la tool.

## El resultado

Cuando el planner termina —éxito, error o timeout— eve despierta al padre con
una **task notification** y le da un turno nuevo para procesarla. La semántica
que heredamos de `SubAgentManager.injectSubAgentResponse` se conserva:

1. **Se añade, nunca se reescribe.** El par tool_call/receipt de la delegación
   cerró en el turno N; el resultado llega después, en un turno nuevo. El
   historial es inmutable.
2. **El payload nunca lleva la misión.** El plan queda persistido en el GCS
   (tabla `MissionPlan`, vía `validate_mission`); el resultado solo lleva el
   `missionPlanId`, que es el único handle al plan.
3. **La entrega es garantizada.** eve gestiona la cola de notificaciones: si el
   padre está ocupado cuando el hijo termina, el resultado espera. Además
   agrupa resultados de tasks lanzadas en el mismo turno
   (*completion batching*), así N planners en vuelo despiertan al padre una vez.

El planner cierra su turno escribiendo este JSON y nada más después
(ver "REPORTING TO THE PARENT" en sus instructions):

```json
{
  "status": "valid",
  "description": "Mission plan generated and validated",
  "missionPlanId": 42,
  "validationReport": "no collisions",
  "totalCollisions": 0
}
```

`status` es `valid` o `failed` (agotó `MAX_VALIDATION_ITERATIONS` y cerró con
`is_final_attempt: true`). En ambos casos el plan está guardado y es mostrable;
en `failed` el operador debe saber que tiene conflictos sin resolver.

## Seguir el progreso del planner

El stream del padre lleva los eventos de control `subagent.called` y
`subagent.completed`. Para ver el detalle de lo que hace el planner —sus 5
pasos, sus llamadas al validador— se lee
`subagent.called.data.childSessionId` y se abre
`GET /eve/v1/session/:childSessionId/stream`. La UI del GCS puede mostrar la
planificación en vivo con eso, sin tocar el thread del operador.
