import { defineAgent, defineDynamic } from "eve";
import { resolveModel } from "#shared/models";

// El monitor sólo lee telemetría y compara números contra umbrales: no razona
// geometría. Tier low a propósito — se despierta por cron, así que un modelo
// caro acá son ~1.440 ejecuciones por día.
//
// defaultTools: false apaga los built-in opcionales. Sin esto el monitor tiene
// `bash` y `write_file`, y un agente autónomo con bash puede hacer curl al
// mcp_server y saltearse la allowlist de solo-lectura de su connection: el
// límite dejaría de ser real. `connection_search` sigue disponible porque el
// agente tiene connections, que es lo único que necesita para ver la telemetría.
export default defineAgent({
  defaultTools: false,
  model: defineDynamic({
    events: {
      "step.started": () => resolveModel("low"),
    },
  }),
});
