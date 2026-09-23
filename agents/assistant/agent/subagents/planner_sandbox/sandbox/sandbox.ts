import { DefaultSandbox, defineSandbox } from "eve/sandbox";

// Layout de carpeta: eve siembra sandbox/workspace/** en /workspace.
//   /workspace/pipeline  scripts deterministas de los pasos 2, 4 y 5
//   /workspace/data      briefing de entrada y salidas del pipeline
export const environment = DefaultSandbox.environment();
export default defineSandbox(() => environment.open());
