"""Tests offline del workspace de planner_sandbox (lib/ + tools/), sin GCS ni eve.

Cada test arma un /workspace temporal: la semilla del sandbox
(agents/planner_sandbox/agent/sandbox/workspace) más los datos de test/workspace/data,
y corre los comandos tal como los corre el modelo.

    python3 -m unittest discover -s test/python -v
"""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
SEED = REPO / "agents/planner_sandbox/agent/sandbox/workspace"
TEST_DATA = REPO / "test/workspace/data"
INSEM_DIR = Path("/home/grvc/work/px4/wtsem/insem")   # referencia; los tests que la usan se saltean si no está

sys.path.insert(0, str(SEED))
sys.dont_write_bytecode = True

from lib.model import Model  # noqa: E402
from lib.regulation import altitude_ceiling  # noqa: E402
from lib.views import Safety  # noqa: E402
from lib.world import SimpleObject, World  # noqa: E402


def make_workspace(tmp, mutate=None):
    """Copia de la semilla + datos de test en `tmp`; `mutate(data_dir)` ajusta el escenario."""
    ws = Path(tmp) / "workspace"
    shutil.copytree(SEED, ws, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(TEST_DATA, ws / "data", dirs_exist_ok=True)
    if mutate:
        mutate(ws / "data")
    return ws


def run(ws, *cmd, check=True):
    env = {"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, *cmd], cwd=ws, capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        raise AssertionError(f"{' '.join(cmd)} -> exit {r.returncode}\n{r.stdout}\n{r.stderr}")
    return r


def edit_json(path, fn):
    data = json.loads(path.read_text())
    path.write_text(json.dumps(fn(data)))


def full_pipeline(ws):
    """Los pasos 3-6 del prompt, con el ejemplo como script de inspección."""
    (ws / "scripts").mkdir(exist_ok=True)
    shutil.copy(ws / "examples/inspect_example.py", ws / "scripts/inspection.py")
    run(ws, "scripts/inspection.py")
    run(ws, "tools/assign.py")
    run(ws, "tools/build_mission.py", "--speed", "5")
    return run(ws, "tools/validate.py", check=False)


# ---------------------------------------------------------------------------
class RegulationTest(unittest.TestCase):
    """UE 2019/947 UAS.OPEN.010: 120 m, o hasta +15 m junto (<50 m) a un elemento de más de 105 m."""

    def tower(self, height):
        return SimpleObject.from_catalog({"name": f"T{height}", "type": "x", "position": {"x": 0, "y": 0, "z": 0}},
                                         {"geometry_type": "circle", "dimensions": {"radius": 5, "height": height}})

    def ceiling(self, pos, height, **safety):
        return altitude_ceiling(np.array(pos, float), Safety(**safety), others=[self.tower(height)])

    def test_raised_within_50m_of_tall_element(self):
        self.assertEqual(self.ceiling([45, 0, 140], 130), (145.0, "T130"))

    def test_not_raised_beyond_50m(self):
        self.assertEqual(self.ceiling([65, 0, 140], 130), (120.0, None))

    def test_not_raised_for_element_up_to_105m(self):
        self.assertEqual(self.ceiling([45, 0, 125], 100), (120.0, None))

    def test_exception_can_be_disabled(self):
        self.assertEqual(self.ceiling([45, 0, 140], 130, tall_obstacle_exception=False), (120.0, None))


class SimpleGeometryTest(unittest.TestCase):
    def test_rectangle_rotated_by_azim_front(self):
        # 20 (x) x 40 (y) x 30: con azimFront 90 el lado largo queda sobre x
        r = SimpleObject.from_catalog({"name": "R", "type": "b", "position": {"x": 0, "y": 0, "z": 0},
                                       "azimFront": 90},
                                      {"geometry_type": "rectangle",
                                       "dimensions": {"width": 20, "length": 40, "height": 30}})
        d = r.sdf(np.array([[25, 0, 10], [0, 15, 10], [0, 0, 40], [0, 0, 10]]))
        np.testing.assert_allclose(d, [5, 5, 10, -10])

    def test_circle(self):
        c = SimpleObject.from_catalog({"name": "C", "type": "t", "position": {"x": 0, "y": 0, "z": 0}},
                                      {"geometry_type": "circle", "dimensions": {"radius": 28, "height": 108}})
        np.testing.assert_allclose(c.sdf(np.array([[40, 0, 50], [0, 0, 120], [10, 0, 50]])), [12, 12, -18])


class ModelTest(unittest.TestCase):
    MODEL = TEST_DATA / "models/wind_turbine.insem.yaml"

    def test_only_declared_state_is_per_instance(self):
        m = Model(self.MODEL, state={"rotor_azimuth_deg": 0, "hub_height": 80})
        self.assertEqual(m.state["rotor_azimuth_deg"], 0)
        self.assertEqual(m.params["hub_height"], 90.0)   # los parámetros son del tipo
        self.assertEqual(m.ignored_state, {"hub_height": 80})

    def test_instance_pose_is_a_rigid_transform(self):
        P = np.random.default_rng(0).uniform([-70, -70, 0], [70, 70, 160], (2000, 3))
        base = Model(self.MODEL)
        origin, az = np.array([-998.65, 87.79, 0]), 35.0
        posed = Model(self.MODEL, origin=origin, azim_front=az)
        t = np.radians(-az)
        R = np.array([[np.cos(t), -np.sin(t), 0], [np.sin(t), np.cos(t), 0], [0, 0, 1]])
        np.testing.assert_allclose(base.sdf_all(P)[0], posed.sdf_all(P @ R.T + origin)[0], atol=1e-9)

    @unittest.skipUnless((INSEM_DIR / "insem.py").exists(), "insem de referencia no disponible")
    def test_same_views_as_insem(self):
        sys.path.insert(0, str(INSEM_DIR))
        import insem
        from lib.patterns import inspect
        from lib.views import Camera, solve
        world = World.load(TEST_DATA)
        world.boundaries = None
        t = world.target("A3")
        safety = Safety(min_clearance_m=6, min_altitude_m=10, max_altitude_m=160, max_standoff_m=18,
                        transit_clearance_m=0, tall_obstacle_exception=False)
        tasks = [{"target": {"class": "rotor_blade"}, "zones": ["tip"], "surfaces": ["leading_edge"], "gsd_mm": 1.0},
                 {"target": "tower", "gsd_mm": 2.0}, {"target": "nacelle"},
                 {"target": "*", "features": ["lightning_receptor", "anemometer_vane"], "gsd_mm": 1.5}]
        ref = insem.Planner(insem.Model(t.model_file, t.attributes),
                            {"safety": {"min_clearance_m": 6, "min_altitude_m": 10, "max_altitude_m": 160,
                                        "max_standoff_m": 18}, "tasks": tasks})
        for task in tasks:
            with self.subTest(task=task):
                ref._flip = False
                rs = [ref.solve(c) for c in ref.gen(task)]
                kw = copy.deepcopy(task)
                ms = [solve(c, t, world, Camera(), safety, others=[])
                      for c in inspect(t.model, Camera(), kw.pop("target"), safety=safety, **kw)]
                self.assertEqual([r["ok"] for r in rs], [m["ok"] for m in ms])
                for r, m in zip(rs, ms):
                    if r["ok"]:
                        np.testing.assert_allclose(r["position"], m["position"] - t.position, atol=1e-6)


# ---------------------------------------------------------------------------
class PipelineTest(unittest.TestCase):
    """El flujo del prompt de punta a punta, y que el validador detecte lo que tiene que detectar."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_describe_only_covers_targets(self):
        ws = make_workspace(self.tmp.name)
        self.assertIn("instance: A3", run(ws, "tools/describe.py", "--target", "A3").stdout)
        r = run(ws, "tools/describe.py", "--target", "A2", check=False)   # A2 es obstáculo
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no es un target", r.stderr)

    def test_example_mission_is_valid(self):
        ws = make_workspace(self.tmp.name)
        result = full_pipeline(ws)
        self.assertEqual(result.returncode, 0, result.stdout)
        mission = json.loads((ws / "data/mission.json").read_text())
        self.assertEqual(mission["version"], "4")
        self.assertIn("global_origin", mission)
        self.assertNotIn("route", mission)
        task = mission["tasks"][0]
        self.assertEqual((task["task_id"], task["device"], task["depends_on"]), ("T1", "uav_1", []))
        self.assertIn("max_vel", task["params"])
        self.assertNotIn("attributes", task)
        self.assertEqual([task["wp"][0]["type"], task["wp"][-1]["type"]], ["takeoff", "landing"])
        self.assertEqual(task["wp"][0]["pos"][2], 10.0)
        self.assertEqual(task["wp"][-1]["pos"][2], 10.0)
        self.assertTrue(any(w["type"] == "transit" for w in task["wp"]), "se esperaban desvíos insertados")
        inspection = [w for w in task["wp"] if w["type"] == "inspection"]
        self.assertTrue(all(w["target"] == "A3" and w["tag"] for w in inspection))

    def test_rejections_explain_the_blocking_cause(self):
        ws = make_workspace(self.tmp.name)
        (ws / "scripts").mkdir()
        shutil.copy(ws / "examples/inspect_example.py", ws / "scripts/inspection.py")
        run(ws, "scripts/inspection.py")
        rejected = json.loads((ws / "data/views.json").read_text()).get("rejected", [])
        self.assertTrue(rejected)
        for r in rejected:
            self.assertTrue(r["blocking"], r)
            self.assertEqual(set(r["hints"]), set(r["blocking"]))

    def test_unavoidable_transit_is_reported(self):
        # la base del dron queda dentro de la zona de seguridad de A2: no hay salida limpia
        def move_home(data):
            edit_json(data / "devices.json", lambda d: [{**d[0], "position": {"x": -996, "y": -140, "z": 0}}])
        ws = make_workspace(self.tmp.name, move_home)
        result = full_pipeline(ws)
        self.assertEqual(result.returncode, 1)
        report = json.loads((ws / "data/validation.json").read_text())
        self.assertIn("clearance_other", {f["code"] for f in report["findings"]})
        self.assertTrue(any(f.get("obstacle") == "A2" for f in report["findings"]))

    def test_validator_catches_structural_errors(self):
        ws = make_workspace(self.tmp.name)
        self.assertEqual(full_pipeline(ws).returncode, 0)

        def corrupt(m):
            r = m["tasks"][0]
            r["wp"][3]["yaw"] = 250
            r["wp"] = [w for w in r["wp"] if w["type"] != "takeoff"]
            m["tasks"].append({**r, "task_id": "T2", "depends_on": ["T7"],
                               "wp": [{**r["wp"][0], "target": "Z9"}, r["wp"][-1]]})
            return m
        edit_json(ws / "data/mission.json", corrupt)
        result = run(ws, "tools/validate.py", check=False)
        self.assertEqual(result.returncode, 1)
        codes = {f["code"] for f in json.loads((ws / "data/validation.json").read_text())["findings"]}
        self.assertEqual(codes, {"format", "depends_on", "coverage", "uav"})

    def test_build_refuses_broken_assignment(self):
        ws = make_workspace(self.tmp.name)
        self.assertEqual(full_pipeline(ws).returncode, 0)
        (ws / "data/assignment.json").write_text(json.dumps({"routes": [
            {"uav": "uav_1", "task_id": "T1", "depends_on": ["T9"], "blocks": ["A3/blades"]}]}))
        r = run(ws, "tools/build_mission.py", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("bloques sin dron: A3/tower", r.stderr)
        self.assertIn("T9", r.stderr)


if __name__ == "__main__":
    unittest.main()
