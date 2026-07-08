# Live 3D-Watch-Orientierung — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine live per Watch-Quaternion mitdrehende, präsentations-schöne 3D-Watch in der Recording- **und** Admin-Seite, deren Display grün leuchtet, wenn die Live-Inferenz „writing" meldet.

**Architecture:** `POST /watch` cached das jüngste Quaternion und broadcastet es throttled (~10 Hz) über den bestehenden `_broadcast`. `ws.js` reicht `{type:"orientation"}` über einen dedizierten Subscriber (umgeht die Status-Pipeline) an einen seiten-agnostischen Three.js-Helfer `watch3d.js`, der per slerp auf 60 fps glättet. Recording- und Admin-Seite mounten denselben Helfer in `onShow()` und reißen ihn in `onHide()` ab.

**Tech Stack:** FastAPI/WebSocket (Backend), ES-Module + importmap, Three.js r169 (via jsdelivr-CDN, kein Build-Step), `GLTFLoader` + `RoomEnvironment`/`PMREMGenerator`.

## Global Constraints

- **Three.js gepinnt:** `three@0.169.0`, importmap für `three` **und** `three/addons/` → `.../examples/jsm/`, platziert **vor** dem `dashboard.js`-Module-Script (nur eine importmap pro Seite).
- **Kein Build-Step:** alles ES-Module/CDN, wie das bestehende Chart.js-`<script>`.
- **Transport-Throttle:** Orientierungs-Broadcast höchstens alle **100 ms**.
- **Kein Hardcoded-Grün:** die writing-Farbe aus `getComputedStyle().--green` ziehen (`THREE.Color().setStyle(rgb)`), nie `0x00ff00`.
- **Teardown-Pflicht:** `destroy()` macht rAF-cancel, `ResizeObserver.disconnect()`, traverse-dispose Geometrien/Materialien, PMREM-Textur dispose, `renderer.dispose()` **+ `renderer.forceContextLoss()`**.
- **Lifecycle:** Init in `onShow()`, Destroy in `onHide()` (NICHT `mount` — das läuft nur einmal). Geparste GLTF modul-cachen.
- **Lizenz:** CC-BY-4.0-Credit („Smartwatch" · _tegarma · CC-BY-4.0) sichtbar im UI beider Panels.
- **Kein JS-Unit-Runner im Repo:** JS-Logik wird über die Static-Smoke (`tests/test_dashboard_static.py`, 404-Trap) + eine manuelle Smoke-Checkliste (Task 7) abgesichert; nur der Backend-Teil ist echtes pytest-TDD.

---

### Task 1: Backend — Orientierung cachen + throttled broadcasten

**Files:**
- Modify: `src/server/state.py:60-73` (Felder im `__init__`) + `src/server/state.py:107-130` (`reset_for_session`)
- Modify: `src/server/routes/watch.py:154-256` (Loop + nach dem Loop)
- Test: `tests/test_endpoints.py`

**Interfaces:**
- Produces: `state.last_orientation: Optional[list[float]]` (`[qx,qy,qz,qw]` oder `None`), `state.last_orientation_broadcast_ms: int`. WS-Nachricht `{"type": "orientation", "q": [qx,qy,qz,qw]}`.

- [ ] **Step 1: Failing test schreiben**

In `tests/test_endpoints.py` ans Dateiende anhängen (nutzt den bestehenden `client`-Fixture-Stil der Datei; falls die Datei `from fastapi.testclient import TestClient` + `client` schon hat, wiederverwenden):

```python
def test_watch_batch_caches_and_broadcasts_orientation(monkeypatch):
    from src.server import state as state_mod
    from src.server.routes import watch as watch_mod

    sent = []
    async def fake_broadcast(msg):
        sent.append(msg)
    monkeypatch.setattr(watch_mod, "_broadcast", fake_broadcast)

    state_mod.state.last_orientation = None
    state_mod.state.last_orientation_broadcast_ms = 0

    payload = {"sequence": 1, "samples": [
        {"ts": 1000, "ax": 0.1, "ay": 0.0, "az": 0.0,
         "rx": 0.0, "ry": 0.0, "rz": 0.0,
         "qx": 0.0, "qy": 0.0, "qz": 0.0, "qw": 1.0},
    ]}
    r = client.post("/watch", json=payload)
    assert r.status_code == 200
    assert state_mod.state.last_orientation == [0.0, 0.0, 0.0, 1.0]
    assert any(m.get("type") == "orientation" and m.get("q") == [0.0, 0.0, 0.0, 1.0]
               for m in sent)


def test_watch_batch_without_quaternion_leaves_orientation_none(monkeypatch):
    from src.server import state as state_mod
    from src.server.routes import watch as watch_mod
    async def fake_broadcast(msg):
        pass
    monkeypatch.setattr(watch_mod, "_broadcast", fake_broadcast)
    state_mod.state.last_orientation = None
    payload = {"sequence": 2, "samples": [
        {"ts": 2000, "ax": 0.1, "ay": 0.0, "az": 0.0,
         "rx": 0.0, "ry": 0.0, "rz": 0.0},
    ]}
    r = client.post("/watch", json=payload)
    assert r.status_code == 200
    assert state_mod.state.last_orientation is None
```

- [ ] **Step 2: Test laufen lassen — muss fehlschlagen**

Run: `python -m pytest tests/test_endpoints.py -k orientation -q`
Expected: FAIL (`AttributeError: ... last_orientation` oder Assertion, weil kein Broadcast).

- [ ] **Step 3: State-Felder ergänzen**

In `src/server/state.py`, nach Zeile 73 (`self.last_pen_dot ...`) einfügen:

```python
        # Letztes valides Attitude-Quaternion [qx,qy,qz,qw] fuer die Live-3D-Watch.
        # None, solange kein Quaternion-tragender Sample gesehen wurde (Legacy-Streams).
        self.last_orientation: Optional[list[float]] = None
        # Throttle-Marke fuer den Orientierungs-Broadcast (Unix-ms), <=10 Hz.
        self.last_orientation_broadcast_ms: int = 0
```

In `reset_for_session` (nach Zeile 120, `self.last_pen_dot = None`) einfügen:

```python
        self.last_orientation = None
```

- [ ] **Step 4: Watch-Handler — Quaternion cachen + throttled broadcasten**

In `src/server/routes/watch.py`: **innerhalb** der Sample-Schleife (`for s in envelope.samples:`, ab Zeile 154), direkt nach dem `w.writerow({...})`-Block und vor `valid_count += 1` (Zeile 184), das jüngste vollständige Quaternion festhalten. Zuerst vor der Schleife (bei `last_sample = None`, Zeile 151) eine Variable initialisieren:

```python
    last_quat = None
```

Innerhalb der Schleife, nach `valid_count += 1` (Zeile 184):

```python
        if None not in (s.qx, s.qy, s.qz, s.qw):
            last_quat = [s.qx, s.qy, s.qz, s.qw]
```

Nach der Schleife, direkt vor `return {` (Zeile 251), den Cache + throttled Broadcast:

```python
    if last_quat is not None:
        state.last_orientation = last_quat
        now_ms = int(time.time() * 1000)
        # Why: throttle auf <=10 Hz — der 60-fps-Client slerpt dazwischen; ein
        # ungedrosselter Broadcast pro Batch-Sample flutet alle WS-Clients.
        if now_ms - state.last_orientation_broadcast_ms >= 100:
            state.last_orientation_broadcast_ms = now_ms
            await _broadcast({"type": "orientation", "q": last_quat})
```

- [ ] **Step 5: Test laufen lassen — muss bestehen**

Run: `python -m pytest tests/test_endpoints.py -k orientation -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Volle Endpoint-Suite grün halten**

Run: `python -m pytest tests/test_endpoints.py -q`
Expected: alle bestehenden + 2 neue PASS.

- [ ] **Step 7: Commit**

```bash
git add src/server/state.py src/server/routes/watch.py tests/test_endpoints.py
git commit -m "feat(watch): cache + throttled broadcast des attitude-quaternions fuer 3D-Watch"
```

---

### Task 2: Frontend-Transport — ws.js Orientierungs-Subscriber

**Files:**
- Modify: `static/js/core/ws.js:23-36` (onmessage-Branch) + neuer Export

**Interfaces:**
- Produces: `setOrientationHandler(fn | null)` — registriert genau EINEN Handler `fn([qx,qy,qz,qw])`, der bei jeder `{type:"orientation"}`-Nachricht aufgerufen wird; `null` meldet ab.

- [ ] **Step 1: Subscriber + Branch ergänzen**

In `static/js/core/ws.js` nach der `let ws, wsReconnectTimer;`-Zeile (Zeile 12) einfügen:

```javascript
// Dedizierter Orientierungs-Subscriber. Die 10-Hz-Watch-Orientierung umgeht
// bewusst handleStatus/_activePageDispatch (die auf status-foermige Payloads
// zielen und die Pill/Badge-Pipeline treiben). Genau ein Handler zur Zeit —
// die aktive Seite registriert in onShow(), meldet in onHide() ab.
let _orientationHandler = null;
export function setOrientationHandler(fn) { _orientationHandler = fn; }
```

Im `ws.onmessage` (nach dem `else if (msg.type === 'stop')`-Block, Zeile 35) ergänzen:

```javascript
    } else if (msg.type === 'orientation') {
      if (_orientationHandler && Array.isArray(msg.q)) _orientationHandler(msg.q);
    }
```

- [ ] **Step 2: Statische Smoke bleibt grün (Datei parst)**

Run: `python -m pytest tests/test_dashboard_static.py -q`
Expected: PASS (ws.js wird weiter als `application/javascript` ausgeliefert; Syntax-Fehler würden den Server-Import nicht brechen, aber der manuelle Browser-Check in Task 7 verifiziert das Parsen).

- [ ] **Step 3: Commit**

```bash
git add static/js/core/ws.js
git commit -m "feat(ws): dedizierter orientation-subscriber (umgeht status-pipeline)"
```

---

### Task 3: Three.js-importmap + Modell-Asset spiegeln

**Files:**
- Modify: `dashboard.html:9` (importmap nach dem Chart.js-Script)
- Create: `static/assets/watch/scene.gltf`, `static/assets/watch/scene.bin`, `static/assets/watch/license.txt` (Kopie aus `scripts/plots/assets/smartwatch-2/`)
- Modify: `tests/test_dashboard_static.py:30-65` (Parametrize-Liste)

**Interfaces:**
- Produces: Bare-Import `three` + `three/addons/...` browserweit auflösbar; `/static/assets/watch/scene.gltf` HTTP-servierbar.

- [ ] **Step 1: importmap in den `<head>` einfügen**

In `dashboard.html` direkt nach Zeile 9 (dem Chart.js-`<script>`) einfügen:

```html
<script type="importmap">
{
  "imports": {
    "three": "https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.js",
    "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.169.0/examples/jsm/"
  }
}
</script>
```

- [ ] **Step 2: Modell nach static/ spiegeln**

Run:

```bash
mkdir -p static/assets/watch
cp scripts/plots/assets/smartwatch-2/scene.gltf static/assets/watch/scene.gltf
cp scripts/plots/assets/smartwatch-2/scene.bin static/assets/watch/scene.bin
cp scripts/plots/assets/smartwatch-2/license.txt static/assets/watch/license.txt
```

- [ ] **Step 3: Static-Smoke-Liste erweitern**

In `tests/test_dashboard_static.py` in die Parametrize-Liste einfügen — `"/static/js/core/watch3d.js"` alphabetisch **vor** `"/static/js/core/ws.js"` (Zeile 56), und die Assets ans Ende der Liste:

```python
        "/static/js/core/watch3d.js",
```

```python
        "/static/assets/watch/scene.gltf",
        "/static/assets/watch/scene.bin",
```

- [ ] **Step 4: Test — gltf/bin da, watch3d.js noch NICHT (erwarteter Teilfehler)**

Run: `python -m pytest tests/test_dashboard_static.py -q`
Expected: die beiden Asset-Fälle PASS; der `watch3d.js`-Fall FAIL (404) — wird in Task 4 grün. (Zwischenzeitlicher roter Test ist ok; Task 4 schließt ihn.)

- [ ] **Step 5: Commit**

```bash
git add dashboard.html static/assets/watch tests/test_dashboard_static.py
git commit -m "chore(3d): three.js importmap + watch-modell nach static/ spiegeln"
```

---

### Task 4: watch3d.js — Three.js-Rendering-Helfer

**Files:**
- Create: `static/js/core/watch3d.js`

**Interfaces:**
- Produces: `initWatch3D(canvas) -> handle`, wobei `handle = { updateOrientation([x,y,z,w]), setWriting(bool), recenter(), destroy() }`. `initWatch3D` startet Laden + rAF-Schleife sofort; mehrfaches `initWatch3D` auf verschiedenen Canvases ist erlaubt (jede Instanz kapselt ihren eigenen Renderer). Die geparste GLTF wird modulweit gecached (`_gltfPromise`), sodass die zweite Instanz/das Re-Show nicht neu lädt.

- [ ] **Step 1: Modul-Skelett + Renderer/Scene/Kamera + Env-Map + Tonemapping**

`static/js/core/watch3d.js` anlegen:

```javascript
// watch3d.js — seiten-agnostischer Three.js-Helfer: rendert das Watch-Modell
// und dreht es live per Attitude-Quaternion. Lazy-importiert Three.js (CDN via
// importmap in dashboard.html). Jede initWatch3D()-Instanz kapselt Renderer +
// rAF; die geparste GLTF wird modulweit gecached.

const GLTF_URL = '/static/assets/watch/scene.gltf';
const CAMERA_FOV = 28;      // lange Brennweite = Produkt-Shot statt Handy-Snapshot
const SLERP_HALFLIFE = 0.08;

let _threePromise = null;
let _gltfPromise = null;

async function _loadThree() {
  if (!_threePromise) {
    _threePromise = (async () => {
      const THREE = await import('three');
      const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js');
      const { RoomEnvironment } = await import('three/addons/environments/RoomEnvironment.js');
      return { THREE, GLTFLoader, RoomEnvironment };
    })();
  }
  return _threePromise;
}

export function initWatch3D(canvas) {
  let disposed = false;
  let raf = 0;
  let renderer, scene, camera, wrapper, ro, envTex;
  let THREE_;
  const targetQuat = { x: 0, y: 0, z: 0, w: 1 };
  let refInv = null;         // q_ref^-1, gesetzt durch recenter()/erstes Sample
  const axisFix = { x: 0, y: 0, z: 0, w: 1 };  // in Step 3 justiert
  let writing = false;
  let lastMsgTs = 0;
  let introT = 0;

  const handle = {
    updateOrientation, setWriting, recenter,
    destroy() {
      disposed = true;
      if (raf) cancelAnimationFrame(raf);
      if (ro) ro.disconnect();
      if (envTex) envTex.dispose();
      if (scene) scene.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
        if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => m.dispose());
      });
      if (renderer) { renderer.dispose(); renderer.forceContextLoss(); }
    },
  };

  _loadThree().then(({ THREE, GLTFLoader, RoomEnvironment }) => {
    if (disposed) return;
    THREE_ = THREE;
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.15;
    renderer.outputColorSpace = THREE.SRGBColorSpace;

    scene = new THREE.Scene();
    const pmrem = new THREE.PMREMGenerator(renderer);
    envTex = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environment = envTex;
    pmrem.dispose();

    camera = new THREE.PerspectiveCamera(CAMERA_FOV, 1, 0.1, 100);
    camera.position.set(0, 0.6, 6);
    camera.lookAt(0, 0, 0);

    const key = new THREE.DirectionalLight(0xffffff, 2.0);
    key.position.set(2, 4, 3);
    scene.add(key);
    scene.add(new THREE.AmbientLight(0xffffff, 0.15));

    _resize();
    ro = new ResizeObserver(_resize);
    ro.observe(canvas);

    _loadModel(THREE, GLTFLoader);
    _tick();
  });

  function _resize() {
    if (!renderer || !canvas.clientWidth) return;
    const w = canvas.clientWidth, h = canvas.clientHeight || Math.round(w * 0.75);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }

  // --- Step 2/3/4 fuellen _loadModel / _tick / updateOrientation etc. ---
  function _loadModel() {}
  function _tick() {}
  function updateOrientation() {}
  function setWriting() {}
  function recenter() {}

  return handle;
}
```

- [ ] **Step 2: GLTF laden, Pivot-Wrapper (Box3-Recenter), Material-Baseline**

`_loadModel` ersetzen. Das Modell liegt weit off-origin + der Root trägt eine gebackene Z-up→Y-up-Matrix → in einen `wrapper`-Group re-zentrieren und NUR den Wrapper rotieren. Alle Meshes bekommen ein Dunkelmetall-Material (garantierter Baseline-Look; Screen-Emissive folgt in Step 5 nach Diagnose).

```javascript
  function _loadModel(THREE, GLTFLoader) {
    if (!_gltfPromise) {
      const loader = new GLTFLoader();
      _gltfPromise = loader.loadAsync(GLTF_URL);
    }
    _gltfPromise.then((gltf) => {
      if (disposed) return;
      const model = gltf.scene.clone(true);
      const bodyMat = new THREE.MeshStandardMaterial({
        color: new THREE.Color(0x2b2e33), metalness: 0.9, roughness: 0.35,
      });
      model.traverse((o) => { if (o.isMesh) { o.material = bodyMat; o._name = o.name; } });

      const box = new THREE.Box3().setFromObject(model);
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      model.position.sub(center);                 // Pivot in den Geometrie-Mittelpunkt
      const scale = 3.2 / Math.max(size.x, size.y, size.z);
      wrapper = new THREE.Group();
      wrapper.scale.setScalar(scale);
      wrapper.add(model);
      wrapper.scale.multiplyScalar(0.92);         // Intro-Startskala (Step 4)
      scene.add(wrapper);
      handle._model = model;                       // fuer Step 5 (Material-Split)
    }).catch((e) => console.warn('watch3d: GLTF load failed', e));
  }
```

- [ ] **Step 3: updateOrientation + recenter + Slerp-Ziel (Double-Cover)**

CoreMotion-Yaw ist pro App-Start arbiträr → `q_display = axisFix ⊗ refInv ⊗ q_device`; `refInv` beim ersten Sample auto-gesetzt (und per `recenter()`). Vor dem Speichern Hemisphäre normalisieren (Double-Cover).

```javascript
  function updateOrientation(q) {
    if (!THREE_ || !q) return;
    lastMsgTs = performance.now();
    const dev = new THREE_.Quaternion(q[0], q[1], q[2], q[3]).normalize();
    if (!refInv) refInv = dev.clone().invert();       // erstes Sample = Ruhepose
    const fix = new THREE_.Quaternion(axisFix.x, axisFix.y, axisFix.z, axisFix.w);
    const disp = fix.multiply(refInv).multiply(dev);
    // Double-Cover: kuerzeste Hemisphaere relativ zum aktuellen Ziel
    if (disp.x*targetQuat.x + disp.y*targetQuat.y + disp.z*targetQuat.z + disp.w*targetQuat.w < 0) {
      disp.set(-disp.x, -disp.y, -disp.z, -disp.w);
    }
    targetQuat.x = disp.x; targetQuat.y = disp.y; targetQuat.z = disp.z; targetQuat.w = disp.w;
  }

  function recenter() { refInv = null; }   // naechstes Sample wird neue Ruhepose
```

- [ ] **Step 4: rAF-Schleife — framerate-unabhängiges Slerp, Intro, Idle-Rotate**

```javascript
  function _tick() {
    if (disposed) return;
    raf = requestAnimationFrame(_tick);
    if (!renderer || !wrapper) return;
    const now = performance.now();
    const dt = Math.min(0.05, (now - (_tick._prev || now)) / 1000);
    _tick._prev = now;

    // Intro: 0.92 -> 1.0 ueber ~600 ms
    if (introT < 1) {
      introT = Math.min(1, introT + dt / 0.6);
      wrapper.scale.setScalar(wrapper.userData._base ||= wrapper.scale.x); // no-op guard
    }

    const stale = now - lastMsgTs > 2000;
    const t = 1 - Math.pow(0.0001, dt / SLERP_HALFLIFE);
    if (stale) {
      wrapper.rotateY(dt * 0.5);                 // Idle-Plattenteller = Liveness-Beweis
    } else {
      const tgt = new THREE_.Quaternion(targetQuat.x, targetQuat.y, targetQuat.z, targetQuat.w);
      wrapper.quaternion.slerp(tgt, t);
    }
    renderer.render(scene, camera);
  }
```

- [ ] **Step 5: setWriting — Emissive (Screen falls identifiziert, sonst Ganzkörper-Tint)**

Der Screen-Mesh lässt sich nicht per Name isolieren (alle `Object_*`, ein Material). **Diagnose zuerst** (Step 6). Bis dahin färbt `setWriting` als robuster Fallback das Body-Material emissiv grün; nach der Diagnose wird `SCREEN_MESH_NAMES` gefüllt und nur der Screen leuchtet.

```javascript
  const SCREEN_MESH_NAMES = new Set([/* nach Diagnose in Step 6 fuellen, z.B. 'Object_7' */]);

  function setWriting(on) {
    writing = !!on;
    if (!handle._model || !THREE_) return;
    const green = new THREE_.Color().setStyle(
      getComputedStyle(document.body).getPropertyValue('--green').trim() || '#4ade80'
    ).convertSRGBToLinear();
    handle._model.traverse((o) => {
      if (!o.isMesh) return;
      const isScreen = SCREEN_MESH_NAMES.size === 0 ? true : SCREEN_MESH_NAMES.has(o._name);
      o.material.emissive = isScreen && writing ? green : new THREE_.Color(0x000000);
      o.material.emissiveIntensity = isScreen && writing ? 0.9 : 0.0;
      o.material.needsUpdate = true;
    });
  }
```

- [ ] **Step 6: Mesh-Diagnose (manuell, einmalig) → SCREEN_MESH_NAMES setzen**

Temporär im Browser die Mesh-Boxen loggen, um den flachen Display-Mesh zu finden. In `_loadModel` nach `handle._model = model;` temporär:

```javascript
      model.traverse((o) => { if (o.isMesh) {
        const b = new THREE.Box3().setFromObject(o); const s = b.getSize(new THREE.Vector3());
        console.log(o.name, s.x.toFixed(2), s.y.toFixed(2), s.z.toFixed(2));
      }});
```

Server starten (`uvicorn server:app --port 8000`), Recording öffnen, Konsole lesen: der Screen ist der dünnste, flächigste Mesh (eine Achse ≪ die anderen zwei, oben liegend). Dessen Namen in `SCREEN_MESH_NAMES` eintragen, das temporäre Log **wieder entfernen**. Findet sich kein sauberer Screen → `SCREEN_MESH_NAMES` leer lassen (Ganzkörper-Emissive-Fallback) und im Commit-Body notieren. **Zeitbudget: max. 1 h** (Spec §2), sonst Fallback akzeptieren.

- [ ] **Step 7: Static-Smoke grün (schließt den Task-3-Rotfall)**

Run: `python -m pytest tests/test_dashboard_static.py -q`
Expected: PASS (watch3d.js jetzt vorhanden → 200).

- [ ] **Step 8: Commit**

```bash
git add static/js/core/watch3d.js
git commit -m "feat(3d): watch3d.js — render-baseline, pivot-wrapper, slerp, idle-rotate, writing-emissive"
```

---

### Task 5: Recording-Seite verdrahten (Split-Layout C)

**Files:**
- Modify: `static/views/recording.html:124-156` (Inferenz-Sektion → Split)
- Modify: `static/css/recording.css` (Split-Grid, Canvas, Vignette, writing-Glow, Credit)
- Modify: `static/js/pages/recording.js:765-846` (`onShow`/`onHide`/`onStatus`)

**Interfaces:**
- Consumes: `initWatch3D` (Task 4), `setOrientationHandler` (Task 2).

- [ ] **Step 1: HTML — Split-Grid mit Canvas links, Karten rechts**

In `static/views/recording.html` die `<div class="rec-inference-grid">` (Zeile 131) durch eine Split-Struktur ersetzen: ein neues `rec-inference-split` mit dem Watch-Panel links und dem bestehenden Grid rechts. Direkt nach `</header>` der Sektion:

```html
    <div class="rec-inference-split">
      <div class="rec-watch3d-panel" id="recWatch3dPanel">
        <div class="rec-watch3d-eyebrow">/ live wrist orientation</div>
        <canvas class="rec-watch3d-canvas" id="recWatch3dCanvas"></canvas>
        <button type="button" class="rec-watch3d-recenter" id="recWatch3dRecenter">/ recenter</button>
        <div class="rec-watch3d-credit">„Smartwatch" · _tegarma · CC-BY-4.0</div>
      </div>
      <div class="rec-inference-grid">
```

Das bestehende `<div class="rec-inference-grid">` (Zeile 131) dabei entfernen (die drei `<article>`-Karten bleiben als Inhalt des neuen rechten Grids), und den schließenden `</div>` der Split-Struktur nach dem Grid-Ende ergänzen.

- [ ] **Step 2: CSS — Split, Canvas, writing-Glow, Vignette**

An `static/css/recording.css` anhängen:

```css
.rec-inference-split { display: grid; grid-template-columns: 57% 1fr; gap: 16px; }
@media (max-width: 820px) { .rec-inference-split { grid-template-columns: 1fr; } }
.rec-watch3d-panel {
  position: relative; border-radius: 12px; min-height: 280px;
  background: radial-gradient(120% 100% at 50% 30%, rgba(99,102,241,.10), transparent 70%);
  display: flex; flex-direction: column;
}
.rec-watch3d-eyebrow { font-size: 11px; letter-spacing: .05em; opacity: .6; padding: 10px 12px 0; text-transform: uppercase; }
.rec-watch3d-canvas { flex: 1; width: 100%; min-height: 240px; display: block; }
.rec-watch3d-panel.is-writing { box-shadow: inset 0 0 60px -20px var(--green); }
.rec-watch3d-recenter { position: absolute; bottom: 8px; left: 12px; background: none; border: 1px solid var(--border); border-radius: 6px; color: inherit; font: inherit; font-size: 10px; padding: 2px 8px; cursor: pointer; opacity: .6; }
.rec-watch3d-credit { position: absolute; bottom: 8px; right: 12px; font-size: 9px; opacity: .4; }
```

- [ ] **Step 3: JS — Import + onShow/onHide/onStatus**

In `static/js/pages/recording.js` oben bei den Imports ergänzen:

```javascript
import { initWatch3D } from '/static/js/core/watch3d.js';
import { setOrientationHandler } from '/static/js/core/ws.js';
```

Ein Modul-lokales Handle deklarieren (nahe den anderen `let`-Deklarationen der Datei):

```javascript
let _watch3d = null;
```

`onShow` (Zeile 765) so ergänzen, dass die Watch initialisiert wird:

```javascript
export function onShow() {
  drawPenCanvas();
  const canvas = document.getElementById('recWatch3dCanvas');
  if (canvas && !_watch3d) {
    _watch3d = initWatch3D(canvas);
    setOrientationHandler((q) => _watch3d && _watch3d.updateOrientation(q));
    document.getElementById('recWatch3dRecenter')
      ?.addEventListener('click', () => _watch3d && _watch3d.recenter());
  }
}
```

`onHide` (Zeile 770) ergänzen:

```javascript
export function onHide() {
  setOrientationHandler(null);
  if (_watch3d) { _watch3d.destroy(); _watch3d = null; }
}
```

In `onStatus(s)` bei der bestehenden `updateInferencePanel(...)`-Zeile (846) direkt danach den writing-State an die Watch geben:

```javascript
  if (_watch3d && s.live_inference) {
    const w = !!s.live_inference.writing;
    _watch3d.setWriting(w);
    document.getElementById('recWatch3dPanel')?.classList.toggle('is-writing', w);
  }
```

> Falls `onHide` in der Datei bereits Inhalt hat, die neuen Zeilen **anhängen**, nicht ersetzen.

- [ ] **Step 4: Static-Smoke grün**

Run: `python -m pytest tests/test_dashboard_static.py -q`
Expected: PASS.

- [ ] **Step 5: Manueller Browser-Check (Recording)**

`uvicorn server:app --port 8000`, `http://localhost:8000` öffnen, Watch streamen. Erwartet: Watch dreht mit, Display/Modell grün bei writing, Panel-Glow, `/ recenter` setzt die Ruhepose, kein Ruckeln.

- [ ] **Step 6: Commit**

```bash
git add static/views/recording.html static/css/recording.css static/js/pages/recording.js
git commit -m "feat(recording): live 3D-watch panel (split-layout C) + writing-glow"
```

---

### Task 6: Admin-Seite verdrahten (VL-Monitor)

**Files:**
- Modify: `static/views/admin.html` (Watch-Card in `adm-grid`)
- Modify: `static/css/admin.css` (Card + Canvas + writing-Glow)
- Modify: `static/js/pages/admin.js:259-281` (`onShow`/`onHide`/`onStatus`)

**Interfaces:**
- Consumes: `initWatch3D`, `setOrientationHandler`. Identischer Lifecycle wie Recording; eigenes Handle (`_admWatch3d`).

- [ ] **Step 1: HTML — Watch-Card ins Monitor-Grid**

In `static/views/admin.html` als erstes Kind von `<div class="adm-grid">` (nach Zeile 21) einfügen:

```html
    <section class="adm-card adm-watch3d">
      <span class="adm-card-eyebrow">/ live wrist orientation</span>
      <canvas class="adm-watch3d-canvas" id="admWatch3dCanvas"></canvas>
      <div class="adm-watch3d-credit">„Smartwatch" · _tegarma · CC-BY-4.0</div>
    </section>
```

- [ ] **Step 2: CSS**

An `static/css/admin.css` anhängen:

```css
.adm-watch3d { position: relative; min-height: 260px; display: flex; flex-direction: column; }
.adm-watch3d-canvas { flex: 1; width: 100%; min-height: 220px; display: block; }
.adm-watch3d.is-writing { box-shadow: inset 0 0 60px -20px var(--green); }
.adm-watch3d-credit { position: absolute; bottom: 6px; right: 10px; font-size: 9px; opacity: .4; }
```

- [ ] **Step 3: JS — Import + Lifecycle**

In `static/js/pages/admin.js` oben ergänzen:

```javascript
import { initWatch3D } from '/static/js/core/watch3d.js';
import { setOrientationHandler } from '/static/js/core/ws.js';
```

Modul-lokal (bei `let _mounted = false;`, Zeile 17):

```javascript
let _admWatch3d = null;
```

`onShow` (Zeile 268) ergänzen:

```javascript
  const c = document.getElementById('admWatch3dCanvas');
  if (c && !_admWatch3d) {
    _admWatch3d = initWatch3D(c);
    setOrientationHandler((q) => _admWatch3d && _admWatch3d.updateOrientation(q));
  }
```

`onHide` (Zeile 277) ergänzen:

```javascript
  setOrientationHandler(null);
  if (_admWatch3d) { _admWatch3d.destroy(); _admWatch3d = null; }
```

`onStatus(s)` (Zeile 281) ergänzen:

```javascript
  if (_admWatch3d && s.live_inference) {
    const w = !!s.live_inference.writing;
    _admWatch3d.setWriting(w);
    document.querySelector('.adm-watch3d')?.classList.toggle('is-writing', w);
  }
```

- [ ] **Step 4: Static-Smoke grün**

Run: `python -m pytest tests/test_dashboard_static.py -q`
Expected: PASS.

- [ ] **Step 5: Manueller Check (Admin)**

Admin per Triple-Click aufs Brand-Logo öffnen (oder `#admin`). Watch dreht mit, grün bei writing. Idealerweise Recording auf einem zweiten Gerät gleichzeitig — beide zeigen dieselbe Bewegung.

- [ ] **Step 6: Commit**

```bash
git add static/views/admin.html static/css/admin.css static/js/pages/admin.js
git commit -m "feat(admin): live 3D-watch panel im VL-monitor"
```

---

### Task 7: End-to-End manuelle Smoke-Checkliste + volle Suite

**Files:** keine (Verifikation).

- [ ] **Step 1: Volle Test-Suite**

Run: `python -m pytest tests/ -q`
Expected: alle grün (bestehende + neue Backend-/Static-Fälle).

- [ ] **Step 2: Manuelle Render-Checkliste (Spec „Testing")**

Server starten, echten Watch-Stream. Prüfen:
- [ ] Watch dreht flüssig mit dem Handgelenk (kein 1-Hz-Ruckeln → slerp greift).
- [ ] `/ recenter` richtet die Ruhepose neu aus.
- [ ] Display/Modell wird grün + Panel-Glow bei writing, aus bei idle.
- [ ] Stille > 2 s → Idle-Plattenteller (nicht eingefroren).
- [ ] Legacy-/Kein-Quaternion-Stream → Idle statt eingefroren; „nie Daten" → Platzhalter/leeres Panel ohne Crash.
- [ ] Tab-Wechsel Recording→Sessions→Recording mehrfach: Watch lebt weiter, keine WebGL-Context-Warnung in der Konsole (forceContextLoss greift).
- [ ] Hell- **und** Dunkel-Theme beide sauber (transparenter Canvas + Vignette).
- [ ] Recording (Laptop) + Admin (zweites Gerät) gleichzeitig: beide zeigen dieselbe Live-Bewegung.
- [ ] Ladeverhalten der 9,4 MB akzeptabel; falls störend → Entscheidung gltfpack vs. Loading-Shimmer (Spec offener Punkt #5).

- [ ] **Step 3: Abschluss-Commit (falls Justierungen nötig waren)**

```bash
git add -A
git commit -m "chore(3d): manuelle smoke-justierungen (framing/exposure/screen-mesh)"
```

---

## Self-Review

**Spec-Coverage:** §0-A → Task 2 (ws.js Subscriber); §0-B → Task 5/6 (onShow/onHide); §1 Render-Baseline → Task 4 Step 1 (PMREM/ACES/AA/pixelRatio, transparent); §2 Pivot+Material-Split → Task 4 Step 2/5/6; §3 Koordinaten/Slerp/Double-Cover → Task 4 Step 3/4; §4 Politur (Idle/Intro/Glow/Recenter) → Task 4 Step 4/5 + Task 5; Transport → Task 1; importmap/Asset → Task 3; Themes → Task 5 CSS + `--green`; Teardown → Task 4 `destroy`; Admin → Task 6; Tests → Task 1/3/7. **Offen (bewusst, Spec offene Punkte):** gltfpack-Kompression, exakte Screen-Mesh-ID (Diagnose Task 4 Step 6), Exposure/FOV-Feinjustage (Task 7).

**Placeholder-Scan:** einziger bewusster Platzhalter ist `SCREEN_MESH_NAMES` (leer, per Diagnose-Step gefüllt) + `axisFix` (Identität, per Task 7 justiert) — beide mit explizitem Fallback (Ganzkörper-Emissive / Identitäts-Rotation), also nie ein blockierender Leerwert.

**Typ-Konsistenz:** `initWatch3D(canvas) → {updateOrientation, setWriting, recenter, destroy}` identisch in Task 4 (Def), Task 5, Task 6. `setOrientationHandler(fn|null)` identisch Task 2/5/6. WS-`{type:"orientation", q:[…]}` identisch Task 1 (Sender) / Task 2 (Empfänger).
