"""Resumen del modelo caracterizado de cada tipo de elemento: lo que el LLM lee.

Por cada tipo de data/element_types.json muestra sus partes (clase, semántica,
primitivas, caja envolvente), superficies inspeccionables con su patrón, zonas,
features, parámetros fijos, derivados y estado, más los TARGETS de ese tipo con
SU estado. Las coordenadas son relativas a la base del elemento: nunca hay una
posición absoluta en esta salida.

Solo cubre targets. Un obstáculo no se inspecciona: se esquiva con la geometría
simple del catálogo (`geometry` en element_types.json), orientada por su
azimFront, así que su modelo y su estado no importan.

    python3 tools/describe.py                      # todos los tipos, estado por defecto del modelo
    python3 tools/describe.py --type "Wind Turbine"
    python3 tools/describe.py --target A3          # estado y azimFront de ESA instancia
    python3 tools/describe.py --target A3 --part 'blade_*'
"""
import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

import yaml  # noqa: E402

from lib.model import Model  # noqa: E402


class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def _repr_list(dumper, data):
    flow = len(data) <= 6 and all(isinstance(x, (int, float, str)) and len(str(x)) < 25 for x in data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)


_Dumper.add_representer(list, _repr_list)


def ydump(o):
    return yaml.dump(o, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=110)


def load_json(path):
    return json.loads(Path(path).read_text())


def resolve_model_file(model_file, data_dir):
    path = Path(model_file)
    return path if path.is_absolute() else data_dir.parent / path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--type", help="solo este tipo (nombre exacto de element_types.json)")
    parser.add_argument("--target", help="nombre de un target: usa su estado (attributes) y su azimFront")
    parser.add_argument("--part", help="glob de partes, p.ej. 'blade_*'")
    parser.add_argument("--json", action="store_true", help="salida JSON en vez de YAML")
    parser.add_argument("--data", type=Path, default=WORKSPACE / "data")
    args = parser.parse_args()

    types = load_json(args.data / "element_types.json")
    targets = load_json(args.data / "targets.json")
    by_name = {t["name"]: t for t in targets}
    target_types = {t["type"] for t in targets}

    instance = None
    if args.target:
        instance = by_name.get(args.target)
        if instance is None:
            sys.exit(f"{args.target!r} no es un target de la misión. Targets: {', '.join(sorted(by_name))}")
        args.type = instance["type"]

    selected = [t for t in types if t["type"] in target_types and args.type in (None, t["type"])]
    if not selected:
        sys.exit(f"{args.type!r} no es el tipo de ningún target. Tipos de targets: {', '.join(sorted(target_types))}")

    out = []
    for entry in selected:
        if not entry.get("model_file"):
            out.append({"type": entry["type"], "error": "sin model_file: prepare_mission_input no lo generó"})
            continue
        model = Model(
            resolve_model_file(entry["model_file"], args.data),
            state=(instance or {}).get("attributes"),
            azim_front=(instance or {}).get("azimFront", 0.0),
        )
        summary = {"type": entry["type"], "model_file": entry["model_file"]}
        if instance:
            summary["instance"] = instance["name"]
        else:
            # Qué varía entre instancias: el estado y la orientación, nunca los parámetros.
            summary["instances"] = [
                {"name": e["name"], "azimFront": e.get("azimFront", 0), "state": e.get("attributes") or {}}
                for e in targets if e["type"] == entry["type"]
            ]
        summary.update(model.describe(args.part))
        out.append(summary)

    print(json.dumps(out, indent=1, ensure_ascii=False) if args.json else ydump(out))


if __name__ == "__main__":
    main()
