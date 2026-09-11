import { defineInstrumentation } from "eve/instrumentation";

// Sin exporter configurado: en dev la telemetría local es automática.
// Para exportar a un backend OTel, registrar el provider en `setup`.
export default defineInstrumentation({});
