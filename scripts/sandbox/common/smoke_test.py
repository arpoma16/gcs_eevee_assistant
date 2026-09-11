"""Smoke test del sandbox: verifica que el entorno mínimo del pipeline funciona."""

import json
import math
import sys
import tempfile
from pathlib import Path

DATA_DIR = Path("/workspace/data")


def check(name, ok, detail=""):
    status = "ok" if ok else "FAIL"
    print(f"[{status}] {name}{f' — {detail}' if detail else ''}")
    return ok


def main():
    results = []

    results.append(
        check("python >= 3.12", sys.version_info >= (3, 12), sys.version.split()[0])
    )

    writable_dir = DATA_DIR if DATA_DIR.is_dir() else Path(tempfile.gettempdir())
    if writable_dir is not DATA_DIR:
        print(f"[warn] /workspace/data no existe, probando escritura en {writable_dir}")
    probe = writable_dir / "smoke_probe.json"
    payload = {"pi": math.pi, "targets": ["A1", "B2"]}
    try:
        probe.write_text(json.dumps(payload))
        roundtrip = json.loads(probe.read_text())
        probe.unlink()
        results.append(check("escritura + roundtrip JSON", roundtrip == payload, str(writable_dir)))
    except OSError as err:
        results.append(check("escritura + roundtrip JSON", False, str(err)))

    yaw = math.degrees(math.atan2(1.0, 1.0))
    results.append(check("stdlib matemática (atan2)", abs(yaw - 45.0) < 1e-9))

    if all(results):
        print("SMOKE TEST OK")
        return 0
    print("SMOKE TEST FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
