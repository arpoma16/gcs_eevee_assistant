import { DefaultSandbox, defineSandbox } from "eve/sandbox";

import { GATE_DIR } from "../lib/gate";

// Layout de carpeta: eve siembra sandbox/workspace/** en /workspace.
//   /workspace/lib             librería fija: modelo INSEM, patrones, mundo, formato de misión
//   /workspace/tools           CLIs fijas: describe, assign, build_mission, validate
//   /workspace/examples        script de inspección de ejemplo
//   /workspace/data            briefing de entrada y salidas del pipeline
//   /workspace/requirements.txt  dependencias Python
//
// `prepare` corre una vez por generación del entorno, no por sesión: las sesiones heredan
// las dependencias ya instaladas. Van en el Python del sistema (sin venv: el sandbox es
// descartable). Para agregar una dependencia, editá requirements.txt.
//
// También deja en GATE_DIR la copia del validador que usa validate_and_persist
// (ver lib/gate.ts: por qué existe y qué protege).
export const environment = DefaultSandbox.environment({
  prepare: async (sandbox) => {
    const commands = [
      "sudo apt-get update && sudo apt-get install -y python3 python3-pip",
      "sudo python3 -m pip install --break-system-packages --root-user-action=ignore -r /workspace/requirements.txt",
      "python3 -c \"import yaml, numpy; print('Pipeline dependencies ready')\"",
      `sudo rm -rf ${GATE_DIR} && sudo mkdir -p ${GATE_DIR}/tools`,
      `sudo cp -r /workspace/lib ${GATE_DIR}/lib && sudo cp /workspace/tools/validate.py ${GATE_DIR}/tools/`,
      `sudo find ${GATE_DIR} -name __pycache__ -prune -exec rm -rf {} + ; sudo chmod -R a-w ${GATE_DIR}`,
      `PYTHONDONTWRITEBYTECODE=1 python3 ${GATE_DIR}/tools/validate.py --help > /dev/null && echo 'Gate ready'`,
    ];
    for (const command of commands) {
      const result = await sandbox.run({ command });
      if (result.exitCode !== 0) {
        throw new Error(`Sandbox setup failed (exit ${result.exitCode}): ${result.stderr || result.stdout}`);
      }
    }
  },
});

export default defineSandbox(() => environment.open());
