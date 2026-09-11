import { defineSandbox } from "eve/sandbox";

// Layout de carpeta: eve siembra agent/sandbox/workspace/** en /workspace.
//   /workspace/tools     smoke test y utilidades comunes
//   /workspace/pipeline  pipeline determinista de planificación (steps 2, 4 y 5)
//   /workspace/data      entrada/salida de la misión en curso (lo crean los scripts)
export default defineSandbox({});
