"""3D-Handgelenk-Replay — eine Smartwatch am Unterarm neigt sich, Schreiben leuchtet.

Rekonstruiert die Handgelenk-Orientierung pro Sample aus dem Schwerkraft-
Einheitsvektor ``g = (gx, gy, gz)`` (Modern-Pool) und animiert ein gerendertes
Watch-am-Arm-Modell, das sich entsprechend im Raum neigt — das Display leuchtet
gold, sobald die Live-Schreib-Proba aus ``loso_oof.csv`` ≥ 0.5 ist.

Gerendert mit **pyvista/VTK offscreen** (echtes OpenGL-Shading). Das Modell ist
aus Primitiven gebaut (Unterarm-Zylinder, Armband-Torus, Watch-Gehäuse, Display)
— keine externe Mesh-Datei nötig. Ein heruntergeladenes ``.glb/.obj`` ließe sich
mit ``pv.read(pfad)`` an dieselbe Orientierung hängen, falls später gewünscht.

Aus einem einzelnen Schwerkraft-Vektor ist nur die **Neigung** (2 DOF)
bestimmbar, nicht der Yaw — die Rotation ist der kürzeste Bogen, der ``g`` auf
Welt-"unten" abbildet (ehrlich: Yaw ist aus Schwerkraft allein nicht messbar).
Quaternion-ready: mit befülltem ``qx/qy/qz/qw`` ersetzt eine Quaternion-Variante
von :func:`_orientations_from_gravity` die Schätzung durch volle 3-DOF.

Benötigt ``pyvista`` (``pip install pyvista``). Ausgabe: animiertes GIF.

CLI::

    python scripts/plots/wrist_replay_3d.py
    python scripts/plots/wrist_replay_3d.py --session S040 --start-sec 90 --seconds 24
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

WATCH_DIR = ROOT / "data" / "raw" / "watch"
OOF = ROOT / "models" / "loso_oof.csv"
FIG_DIR = ROOT / "reports" / "figures"

WORLD_DOWN = np.array([0.0, 0.0, -1.0])
SKIN = "#d8b39a"
BAND = "#2b2b33"
CASE = "#1b1a22"
IDLE_RGB = np.array([0.13, 0.14, 0.26])    # dunkles Indigo
WRITING_RGB = np.array([0.88, 0.63, 0.20])  # sattes Gold

# ── Arm-Kopplung (Stufe 1) ────────────────────────────────────────────────
# R_align mappt das Modell-Koordinatensystem auf das Sensor-Frame: die Ruhelage
# (Unterarm flach/horizontal entlang −X, Watch-Display nach +Z) soll bei R = I
# unverdreht stehen. Falls ein geladenes Mesh anders orientiert ist, hier
# kalibrieren (Euler xyz in Grad). Default: die Primitive sind bereits im
# Sensor-Frame gebaut → Identität.
R_ALIGN_EULER_DEG = (0.0, 0.0, 0.0)

# Optionale echte Meshes: irgendwo unter assets/ ablegen (auch in Unterordnern,
# z. B. der Sketchfab-Struktur). Auswahl per Schlüsselwort im Pfad; sonst Primitiv.
ASSET_DIR = Path(__file__).resolve().parent / "assets"
WATCH_MESH_KEYWORDS = ("watch",)
FOREARM_MESH_KEYWORDS = ("forearm",)
MESH_EXTS = (".obj", ".gltf", ".glb", ".stl", ".ply")
# Statische Mesh-Ausrichtung (Modell-Frame → Szenen-Frame): geladene Downloads
# haben beliebige Achsen-Konvention. Hier kalibrieren, bis die Strap-Schlaufe um
# die Arm-Achse (X) läuft und das Display nach +Z zeigt. Euler xyz in Grad.
WATCH_FIT_EULER_DEG = (0.0, 90.0, 0.0)
# Platzhalter-Maße in VTK-Einheiten. Arm-Radius bewusst schlank (war 0.5 =
# „Baumstamm"), damit die Watch dominiert.
ARM_LENGTH = 2.8
ARM_RADIUS = 0.40
WATCH_LOOP_FACTOR = 2.2   # Strap-Schlaufen-Durchmesser / Arm-Durchmesser

# App-Screen: realer Screenshot als emissive Textur auf der Display-Fläche.
# SCREEN_BEZEL_OBJECT = Name des glTF-Teils, das den Display-Rahmen bildet (gibt
# die Pose). Beides optional — fehlt eins, bleibt das Display blank.
SCREEN_IMAGE = ASSET_DIR / "watch_screen.png"
SCREEN_BEZEL_OBJECT = "Object_3"
SCREEN_INSET = 0.84        # Screen etwas kleiner als die Bezel-Öffnung
SCREEN_LIFT = 0.02         # knapp über die Case-Oberkante (gegen z-fighting)

# Neutrale Studio-IBL-Umgebung (autogeneriert) statt blauem Himmel-Cubemap.
STUDIO_ENV = ASSET_DIR / "studio_env.png"

# PBR-Materialien (pbr=True → physically-based statt Plastik-Flat-Shading).
SKIN_PBR = {"color": SKIN, "metallic": 0.0, "roughness": 0.70}
CASE_PBR = {"color": "#26252d", "metallic": 0.80, "roughness": 0.34}
GROUND_PBR = {"color": "#e7e3db", "metallic": 0.0, "roughness": 0.95}
RENDER_PX = 1100          # hochrendern …
OUTPUT_PX = 660           # … dann fürs GIF runterskalieren (Supersampling)


def _r_align() -> np.ndarray:
    """Feste Modell→Sensor-Korrektur aus ``R_ALIGN_EULER_DEG`` (oben editierbar)."""
    from scipy.spatial.transform import Rotation  # noqa: PLC0415
    return Rotation.from_euler("xyz", R_ALIGN_EULER_DEG, degrees=True).as_matrix()


def _shortest_arc(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """3×3-Rotation R mit R·a = b (kürzester Bogen zwischen Einheitsvektoren)."""
    a = a / (np.linalg.norm(a) + 1e-12)
    b = b / (np.linalg.norm(b) + 1e-12)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if c < -1 + 1e-8:
        ortho = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
        axis = np.cross(a, ortho); axis /= np.linalg.norm(axis)
        K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]],
                      [-axis[1], axis[0], 0]])
        return np.eye(3) + 2 * K @ K
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K / (1 + c)


def _orientations_from_gravity(g: np.ndarray) -> list[np.ndarray]:
    """2-DOF-Tilt: Welt←Watch-Rotation, die gemessenes g auf Welt-unten abbildet.
    Yaw (Drehung um die Vertikale) ist aus Schwerkraft allein nicht messbar."""
    return [_shortest_arc(WORLD_DOWN, gi) for gi in g]


def _orientations_from_quaternion(q: np.ndarray,
                                  g: np.ndarray | None) -> list[np.ndarray]:
    """Volle 3-DOF Welt←Watch-Rotation aus dem Attitude-Quaternion (qx,qy,qz,qw).

    Apples ``CMAttitude``-Quaternion-Konvention (rotiert Referenz→Body oder
    umgekehrt) ist ohne Testdaten mehrdeutig. Statt zu raten wird sie
    **datengetrieben** aufgelöst: liegt auch der Schwerkraft-Vektor vor, wird die
    Variante (R oder Rᵀ) gewählt, die das gemessene ``g`` am besten auf
    Welt-unten abbildet — den ``g``-Pfad verstehen wir, also eicht er den
    Quaternion-Pfad. Ohne Gravity Fallback auf die ungetransponierte Form."""
    from scipy.spatial.transform import Rotation  # noqa: PLC0415
    M = Rotation.from_quat(q).as_matrix()  # scipy: (x, y, z, w) → (n, 3, 3)
    if g is None:
        return [M[i] for i in range(len(M))]
    best, best_name, best_score = M, "R", -1e9
    for name, C in (("R", M), ("Rᵀ", np.transpose(M, (0, 2, 1)))):
        mapped = np.einsum("nij,nj->ni", C, g)        # C · g pro Sample
        score = float(np.mean(mapped @ WORLD_DOWN))   # zeigt es nach unten?
        if score > best_score:
            best, best_name, best_score = C, name, score
    print(f"  Quaternion-Konvention via Gravity geeicht: {best_name} "
          f"(g→down score {best_score:+.2f})")
    return [best[i] for i in range(len(best))]


def _load(session: str, start_sec: float, seconds: float, stride: int):
    f = WATCH_DIR / f"{session}_watch.csv"
    if not f.exists():
        raise SystemExit(f"{f} fehlt.")
    cols = ("ts", "gx", "gy", "gz", "qx", "qy", "qz", "qw")
    df = pd.read_csv(f, usecols=lambda c: c in cols)
    df = df.dropna(subset=["ts", "gx", "gy", "gz"]).reset_index(drop=True)
    if df.empty:
        raise SystemExit(f"{session}: keine Schwerkraft-Daten (Legacy-Session?).")
    t0 = df["ts"].iloc[0]
    rel = (df["ts"] - t0) / 1000.0
    sel = df[(rel >= start_sec) & (rel <= start_sec + seconds)].iloc[::stride]
    if sel.empty:
        raise SystemExit("Gewählter Zeitraum leer — start-sec/seconds prüfen.")
    g = sel[["gx", "gy", "gz"]].to_numpy()
    g /= (np.linalg.norm(g, axis=1, keepdims=True) + 1e-12)
    ts = sel["ts"].to_numpy()

    qcols = ("qx", "qy", "qz", "qw")
    has_quat = all(c in sel.columns for c in qcols) and \
        bool(sel[list(qcols)].notna().all(axis=1).mean() > 0.5)
    q = sel[list(qcols)].to_numpy() if has_quat else None
    if has_quat:
        q = q / (np.linalg.norm(q, axis=1, keepdims=True) + 1e-12)

    proba = np.full(len(ts), np.nan)
    if OOF.exists():
        oof = pd.read_csv(OOF)
        s = oof[oof["session_id"] == session].sort_values("t_center_ms")
        if not s.empty:
            proba = np.interp(ts, s["t_center_ms"], s["proba_raw"])
    return ts, g, q, has_quat, proba


def _read_mesh(path: Path):
    """OBJ/PLY/STL/GLB → einzelnes PolyData (MultiBlock wird kombiniert); None
    bei Fehler."""
    import pyvista as pv  # noqa: PLC0415
    try:
        m = pv.read(path)
    except Exception as exc:  # noqa: BLE001 — jede Reader-Exception → Fallback
        print(f"  Mesh {path.name} nicht lesbar ({exc}) → Fallback.")
        return None
    if isinstance(m, pv.MultiBlock):
        m = m.combine()
    # glTF-Combine liefert UnstructuredGrid teils ohne Normalen → smooth_shading
    # crasht. Zu sauberer Dreiecks-Oberfläche mit Normalen aufbereiten.
    try:
        m = m.extract_surface().triangulate()
        m = m.compute_normals(auto_orient_normals=True, non_manifold_traversal=False)
    except Exception:  # noqa: BLE001 — Normalen optional, Flat-Shading reicht
        pass
    return m


def _find_mesh_path(keywords):
    """Pfad des ersten Mesh unter ASSET_DIR (rekursiv), dessen Pfad ein keyword
    enthält — oder None."""
    if not ASSET_DIR.exists():
        return None
    cands = sorted(p for p in ASSET_DIR.rglob("*")
                   if p.suffix.lower() in MESH_EXTS)
    for kw in keywords:
        for p in cands:
            if kw in str(p).lower():
                return p
    return None


def _discover_mesh(keywords):
    """Geladenes Mesh (pyvista) für das erste passende keyword — oder None."""
    path = _find_mesh_path(keywords)
    if path is None:
        return None
    m = _read_mesh(path)
    if m is not None:
        print(f"  Mesh geladen: {path.relative_to(ASSET_DIR)} ({m.n_points} Punkte)")
    return m


def _fit_forearm(mesh):
    """Längste Achse → X, auf ARM_LENGTH skalieren, Wrist-Ende (x max) in den
    Ursprung, Körper erstreckt sich in −X (Richtung Ellbogen). Statisch."""
    m = mesh.copy()
    m.translate(tuple(-np.asarray(m.center)), inplace=True)
    b = m.bounds
    long_axis = int(np.argmax((b[1] - b[0], b[3] - b[2], b[5] - b[4])))
    if long_axis == 1:
        m.rotate_z(90, inplace=True)
    elif long_axis == 2:
        m.rotate_y(90, inplace=True)
    b = m.bounds
    m.scale(ARM_LENGTH / max(b[1] - b[0], 1e-9), inplace=True)
    m.translate((-m.bounds[1], 0, 0), inplace=True)        # x max → 0
    return m


def _ensure_studio_env():
    """Erzeugt eine neutrale, equirektanguläre Studio-Umgebung (Grau-Gradient,
    helle Softbox oben) für die IBL, falls sie noch nicht existiert. Neutral statt
    Himmel-Cubemap → keine Farbstich-Reflexionen aufs Metall."""
    if STUDIO_ENV.exists():
        return
    from PIL import Image  # noqa: PLC0415
    h, w = 256, 512
    y = np.linspace(0, 1, h)[:, None]
    val = 0.92 - 0.5 * np.clip((y - 0.15) / 0.85, 0, 1)
    img = np.repeat((val * 255).astype(np.uint8), w, axis=1)[:, :, None].repeat(3, axis=2)
    img[:40, :] = 245
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(STUDIO_ENV)


def _screen_quad(scene, fit, Rfit, watch_center, zmax):
    """Texturiertes Quad genau auf die Display-Fläche legen — Pose aus dem
    Bezel-Teil (``SCREEN_BEZEL_OBJECT``): Zentrum + Normale (PCA), 12-Uhr
    deterministisch entlang des Arms (+X). None, falls Bild/Bezel fehlen."""
    import pyvista as pv  # noqa: PLC0415
    if not SCREEN_IMAGE.exists() or SCREEN_BEZEL_OBJECT not in scene.geometry:
        return None
    v3 = np.asarray(scene.geometry[SCREEN_BEZEL_OBJECT].vertices)
    c3 = v3.mean(0)
    _, _, vt = np.linalg.svd(v3 - c3, full_matrices=False)
    n3 = vt[2]
    if np.dot(c3 - watch_center, n3) < 0:
        n3 = -n3
    c3f = fit(c3[None])[0]
    n = Rfit @ n3
    n /= np.linalg.norm(n)
    up = np.array([1.0, 0, 0]) - np.dot([1.0, 0, 0], n) * n
    up /= np.linalg.norm(up)
    right = np.cross(up, n)
    right /= np.linalg.norm(right)
    v3f = fit(v3)
    hh = np.ptp((v3f - c3f) @ up) * SCREEN_INSET
    ww = np.ptp((v3f - c3f) @ right) * SCREEN_INSET
    c = np.array([c3f[0], c3f[1], zmax + SCREEN_LIFT])
    pts = np.array([c - up * hh / 2 - right * ww / 2,
                    c - up * hh / 2 + right * ww / 2,
                    c + up * hh / 2 + right * ww / 2,
                    c + up * hh / 2 - right * ww / 2])
    quad = pv.PolyData(pts, faces=[4, 0, 1, 2, 3])
    quad.active_texture_coordinates = np.array(
        [[0, 0], [1, 0], [1, 1], [0, 1]], dtype=float)
    return quad


def _load_watch_scene(arm_radius):
    """Watch via trimesh laden und fitten (Strap-Schlaufe um die X-Achse, am
    Ursprung zentriert). Returns ``body_pv`` oder ``None``."""
    path = _find_mesh_path(WATCH_MESH_KEYWORDS)
    if path is None:
        return None
    import pyvista as pv  # noqa: PLC0415
    import trimesh  # noqa: PLC0415
    from scipy.spatial.transform import Rotation  # noqa: PLC0415
    scene = trimesh.load(path, force="scene")
    full = trimesh.util.concatenate(list(scene.geometry.values()))
    vf = np.asarray(full.vertices)
    c0 = vf.mean(0)
    Rfit = Rotation.from_euler("xyz", WATCH_FIT_EULER_DEG, degrees=True).as_matrix()
    s = (WATCH_LOOP_FACTOR * arm_radius) / np.ptp((Rfit @ (vf - c0).T).T, axis=0).max()

    def fit(pts):
        return s * (Rfit @ (np.asarray(pts) - c0).T).T

    body = pv.wrap(full)
    body.points = fit(full.vertices)
    try:
        body = body.extract_surface().triangulate().compute_normals(
            auto_orient_normals=True)
    except Exception:  # noqa: BLE001 — Flat-Shading reicht, falls Normalen scheitern
        pass
    print(f"  Watch-Mesh: {path.relative_to(ASSET_DIR)} ({body.n_points} Punkte)")
    return body


def _build_scene(p):
    """Nur die Watch (kein Unterarm, kein App-Screen) + ein Boden als
    Schatten-Fänger. Die Watch-Actors teilen sich pro Frame dieselbe
    ``user_matrix`` und rotieren als starrer Körper um den Ursprung.

    Returns ``watch_actors`` (Liste) — nur diese rotieren; der Boden bleibt statisch.
    """
    import pyvista as pv  # noqa: PLC0415

    # ── Boden (statisch, deutlich unter der Watch → Schlagschatten) ──
    ground = pv.Plane(center=(0, 0, -0.95), direction=(0, 0, 1),
                      i_size=10, j_size=10)
    p.add_mesh(ground, pbr=True, **GROUND_PBR)

    # ── Watch (ohne Arm, ohne Screen) ──
    body = _load_watch_scene(ARM_RADIUS)
    watch_actors = []
    if body is not None:
        watch_actors.append(
            p.add_mesh(body, pbr=True, smooth_shading=True, **CASE_PBR))
        return watch_actors

    # ── Primitiv-Fallback (kein Watch-Mesh vorhanden) ──
    band = pv.ParametricTorus(ringradius=0.42, crosssectionradius=0.10)
    band.rotate_y(90, inplace=True)
    case = pv.Cube(center=(0, 0, 0.50), x_length=0.86, y_length=0.62, z_length=0.18)
    crown = pv.Cylinder(center=(0, -0.34, 0.50), direction=(0, 1, 0),
                        radius=0.05, height=0.06)
    watch_actors.append(p.add_mesh(band, pbr=True, metallic=0.7, roughness=0.5,
                                   color=BAND, smooth_shading=True))
    watch_actors.append(p.add_mesh(case, pbr=True, smooth_shading=True, **CASE_PBR))
    watch_actors.append(p.add_mesh(crown, color="#888888", specular=0.8))
    return watch_actors


def run(session: str, start_sec: float, seconds: float, stride: int,
        fps: int, source: str) -> None:
    try:
        import pyvista as pv
    except ModuleNotFoundError:
        raise SystemExit("pyvista fehlt — `pip install pyvista`.")
    from PIL import Image  # noqa: PLC0415

    ts, g, q, has_quat, proba = _load(session, start_sec, seconds, stride)
    use_quat = (source == "quat") or (source == "auto" and has_quat)
    if source == "quat" and not has_quat:
        raise SystemExit(
            f"{session} hat keine befüllten Quaternionen — mit aktuellem "
            f"Watch-Build neu aufnehmen oder --source gravity nutzen.")
    if use_quat:
        R = _orientations_from_quaternion(q, g)
        src_label = "Orientierung: 3-DOF Quaternion"
    else:
        R = _orientations_from_gravity(g)
        src_label = "Orientierung: Schwerkraft-Tilt (2 DOF)"
    n = len(R)
    print(f"{session}: {n} Frames ({seconds:g}s ab {start_sec:g}s, "
          f"stride {stride})  ·  {src_label}")

    pv.OFF_SCREEN = True
    p = pv.Plotter(off_screen=True, window_size=(RENDER_PX, RENDER_PX),
                   lighting="none")
    p.set_background("#edeae3", top="#d6d2cb")     # weicher Verlauf statt Flat-Grau
    _ensure_studio_env()
    try:
        p.set_environment_texture(pv.read_texture(str(STUDIO_ENV)))   # IBL
    except Exception:  # noqa: BLE001 — ohne IBL trägt das 3-Punkt-Licht
        pass
    watch_actors = _build_scene(p)
    # 3-Punkt-Licht: warmes Key, kühles Fill, weißes Rim (Studio-Setup).
    p.add_light(pv.Light(position=(5, -4, 7), color="#fff4e6", intensity=1.0))
    p.add_light(pv.Light(position=(-6, -2, 3), color="#e8ecff", intensity=0.45))
    p.add_light(pv.Light(position=(-3, 5, 5), color="#ffffff", intensity=0.5))
    p.enable_shadows()
    p.enable_ssao(radius=0.12)             # Kontaktschatten in den Ritzen
    p.enable_anti_aliasing("ssaa")
    p.camera.SetParallelProjection(False)  # Perspektive statt CAD-Parallel
    p.camera_position = [(1.85, -2.10, 1.5), (0, 0, 0.0), (0, 0, 1)]  # weiter raus
    p.camera.view_angle = 28
    p.add_text(src_label, position="lower_left", font_size=16, color="#7a7688")

    R_align = _r_align()
    frames = []
    print(f"Rendere {n} Frames offscreen …")
    for i in range(n):
        # Starrer Körper: dieselbe Sensor-Orientierung auf alle Watch-Teile.
        M = np.eye(4); M[:3, :3] = R[i] @ R_align
        for wa in watch_actors:
            wa.user_matrix = M
        pr = float(proba[i]) if not np.isnan(proba[i]) else 0.0
        state = "schreibt" if pr >= 0.5 else "idle"
        p.add_text(f"{session}   t={(ts[i]-ts[0])/1000:4.1f}s   "
                   f"P(writing)={pr:.2f}  ·  {state}",
                   name="hud", position="upper_left", font_size=22,
                   color="#3a3744")
        frame = Image.fromarray(p.screenshot(return_img=True))
        frames.append(frame.resize((OUTPUT_PX, OUTPUT_PX), Image.LANCZOS))

    p.close()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = FIG_DIR / f"wrist_replay_{session}.gif"
    frames[0].save(out, save_all=True, append_images=frames[1:],
                   duration=int(1000 / fps), loop=0, optimize=True)
    print(f"\n→ {out}")


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session", default="S039",
                   help="Modern-Session mit Schwerkraft (Default S039/P13).")
    p.add_argument("--start-sec", type=float, default=120.0)
    p.add_argument("--seconds", type=float, default=20.0)
    p.add_argument("--stride", type=int, default=10,
                   help="Sample-Downsample (100 Hz / stride = Frame-Rate).")
    p.add_argument("--fps", type=int, default=12)
    p.add_argument("--source", choices=["auto", "quat", "gravity"], default="auto",
                   help="auto = Quaternion wenn befüllt, sonst Schwerkraft-Tilt.")
    return p.parse_args()


if __name__ == "__main__":
    a = _parse()
    run(a.session, a.start_sec, a.seconds, a.stride, a.fps, a.source)
