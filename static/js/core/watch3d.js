// watch3d.js — seiten-agnostischer Three.js-Helfer: rendert das Watch-Modell
// und dreht es live per Attitude-Quaternion. Lazy-importiert Three.js (CDN via
// importmap in dashboard.html). Jede initWatch3D()-Instanz kapselt Renderer +
// rAF; die geparste GLTF wird modulweit gecached.

const GLTF_URL = '/static/assets/watch/scene-lite.glb';  // 7.4k tris (dezimiert von 347k)
const CAMERA_FOV = 28;      // lange Brennweite = Produkt-Shot statt Handy-Snapshot
// Jitter-Buffer-Playback: die Samples kommen gebuendelt (~10 Batches/s à ~10 Stück,
// mit Netz-Jitter), sollen aber mit KONSTANTER Winkelgeschwindigkeit abgespielt werden
// (so lief das Offline-Replay fluessig). Ein fraktionaler Lese-Cursor interpoliert
// zwischen zwei Nachbar-Samples; ein sanfter Regler haelt die Puffertiefe stabil.
const BUF_LATENCY_FRAC = 0.15; // Ziel-Puffertiefe als Sekundenbruchteil (~150 ms Latenz)
const BUF_CTRL_GAIN = 0.03;    // Regler-Verstaerkung (klein = ruhige, driftkorrigierende Geschwindigkeit)
// Geschwindigkeits-Clamp: eng (±20 %), weil die Rate jetzt die BEKANNTE Geräte-fs ist
// (nicht mehr aus Ankunftszeiten geschätzt) -> der Regler trimmt nur wenige % und bleibt
// unsichtbar. Weite Clamps wären nur nötig, um eine verrauschte Rate zu maskieren.
const BUF_SPEED_MIN = 0.85, BUF_SPEED_MAX = 1.2;
const QUEUE_CAP = 36;          // harte Latenz-Obergrenze (>= Ziel + 2 Batches) gegen Netz-Bursts

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
  let refInv = null;         // q_ref^-1, gesetzt durch recenter()/erstes Sample
  let writing = false;
  let lastMsgTs = 0;
  let introT = 0;
  let lastRender = 0;        // performance.now() des letzten gerenderten Frames
  let lastW = 0, lastH = 0;  // Firing-Feedback-Loop-Schutz fuer ResizeObserver
  let tgtQ;                  // wiederverwendetes Quaternion (keine Per-Frame-Allokation)
  let devQ, dispQ, prevQ;    // Reusable quaternions for GC prevention (prevQ = Playback-Startpose)
  const _queue = [];         // gepufferte korrigierte Anzeige-Quaternionen (~100 Hz Playback)
  // Jitter-Buffer-Playback-Zustand (siehe _tick):
  let havePrev = false;      // prevQ initialisiert?
  let frac = 0;              // fraktionaler Cursor prevQ -> _queue[0], in [0,1)
  let fsRate = 0;            // BEKANNTE Geräte-Samplerate (Hz) aus dem Payload = Playback-Tempo
  let bufEMA = 0;            // geglättete Puffertiefe (entkoppelt den Batch-Sägezahn vom Regler)
  let primed = false;        // Prebuffer-Gate: erst spielen, wenn ~½ Ziel gepuffert (kein Dry-Start)
  let colorActive, colorDefault; // Reusable colors for setWriting()
  let needsRender = true;    // Reactive rendering flag to save CPU/GPU cycles
  let C_FIX, C_INV;          // Basis-Konjugation CoreMotion(Z-up) -> Three.js(Y-up)
  let onKey = null;          // Dev-Key-Handler (Basis-Nudger + recenter), in destroy() entfernt

  const handle = {
    updateOrientation, setWriting, recenter,
    destroy() {
      disposed = true;
      if (raf) cancelAnimationFrame(raf);
      if (onKey) window.removeEventListener('keydown', onKey);
      if (ro) ro.disconnect();
      if (envTex) envTex.dispose();
      // Why: geometry is module-cached (_gltfPromise) and shared across instances via
      // gltf.scene.clone(true) (a shallow clone — meshes still reference the same
      // BufferGeometry objects as the cache/other live instances), so it must NOT be
      // disposed here. Only the per-instance material (fresh MeshStandardMaterial from
      // _loadModel) is instance-owned and safe to dispose.
      if (scene) scene.traverse((o) => {
        if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => m.dispose());
      });
      if (renderer) { renderer.dispose(); renderer.forceContextLoss(); }
    },
  };

  _loadThree().then(({ THREE, GLTFLoader, RoomEnvironment }) => {
    if (disposed) return;
    THREE_ = THREE;
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' });
    // Why: antialias ist auf Apple-Tile-GPUs quasi gratis (glaettet die Metallraender);
    // pixelRatio 1.5 haelt die Fragment-Kosten bei ~2.25x, sieht aber knackig statt weich.
    // Bei kleiner Canvas (~1/4) ist das billig. precision:'mediump' raus (Banding-Artefakte).
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    tgtQ = new THREE.Quaternion();
    devQ = new THREE.Quaternion();
    dispQ = new THREE.Quaternion();
    prevQ = new THREE.Quaternion();
    colorActive = new THREE.Color(0x00e676);
    colorDefault = new THREE.Color(0x000000);

    // Basis-Konjugation CoreMotion(Z-up) -> Three.js(Y-up), in updateOrientation()
    // als C ⊗ q ⊗ C⁻¹ angewandt (plus feste Rotationsrichtungs-Umkehr, s.u.).
    // Empirisch kalibriert (Nutzer, echter Watch-Stream): C_FIX = [0, -√½, √½, 0].
    C_FIX = new THREE.Quaternion(0, -Math.SQRT1_2, Math.SQRT1_2, 0);
    C_INV = C_FIX.clone().invert();
    // 'r' = recenter (Ruhepose neu setzen) — Demo-Affordance, greift auf die
    // aktuelle Handhaltung als neue Nulllage.
    onKey = (e) => { if (e.key === 'r') recenter(); };
    window.addEventListener('keydown', onKey);

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
    if (w === lastW && h === lastH) return;
    lastW = w; lastH = h;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }

  function _loadModel(THREE, GLTFLoader) {
    if (!_gltfPromise) {
      const loader = new GLTFLoader();
      _gltfPromise = loader.loadAsync(GLTF_URL);
    }
    _gltfPromise.then((gltf) => {
      if (disposed) return;
      const model = gltf.scene.clone(true);
      // Why: das ORIGINAL-PBR-Material des Modells behalten (mit Env-Map = echte-Uhr-Look),
      // aber pro Instanz klonen — sonst teilt der clone(true) die Material-Referenz mit dem
      // Cache/anderen Instanzen und setWriting()'s Emissive-Aenderung + destroy()'s dispose
      // wuerden global durchschlagen. Der fruehere Dunkelmetall-Override sah wie ein
      // texturloser Klumpen aus.
      model.traverse((o) => { if (o.isMesh) { o.material = o.material.clone(); o._name = o.name; } });

      // Pivot = Mittelpunkt des ganzen Modells (Box3). Das fruehere Object_1/Object_3-
      // Namensraten traf oft ein Band-Segment -> die Watch orbitierte um einen Off-Center-
      // Punkt statt sich an Ort zu drehen ("buggy" Wobble).
      const pivot = new THREE.Box3().setFromObject(model).getCenter(new THREE.Vector3());

      const box = new THREE.Box3().setFromObject(model);
      const size = box.getSize(new THREE.Vector3());
      model.position.set(-pivot.x, -pivot.y, -pivot.z); // watch-case relativ zur pivotGroup zentrieren
      
      const pivotGroup = new THREE.Group();
      pivotGroup.add(model);
      pivotGroup.rotation.set(0, Math.PI / 2, 0); // Display nach vorne (+Z), Bänder horizontal (X), Arm vertikal (Y)
      
      const scale = 1.8 / Math.max(size.x, size.y, size.z); // Kleiner skaliert, damit es ins Panel passt
      wrapper = new THREE.Group();
      wrapper.userData.baseScale = scale;
      wrapper.scale.setScalar(scale * 0.92);       // Intro-Startskala, siehe _tick()
      wrapper.add(pivotGroup);
      scene.add(wrapper);
      handle._model = model;                       // fuer Step 5 (Material-Split)
      try {
        const bodyStyles = getComputedStyle(document.body);
        const greenHex = bodyStyles.getPropertyValue('--green').trim() || '#4ade80';
        colorActive.setStyle(greenHex).convertSRGBToLinear();
      } catch (e) {
        colorActive.set(0x4ade80);
      }
      setWriting(writing);                         // Aktuellen Status auf geladenes Modell anwenden
    }).catch((e) => console.warn('watch3d: GLTF load failed', e));
  }

  function _tick() {
    if (disposed) return;
    raf = requestAnimationFrame(_tick);
    if (!renderer || !wrapper) return;
    const now = performance.now();
    const dt = Math.min(0.05, (now - (lastRender || now)) / 1000);
    lastRender = now;

    // Intro animation
    if (introT < 1) {
      introT = Math.min(1, introT + dt / 0.6);
      wrapper.scale.setScalar(wrapper.userData.baseScale * (0.92 + 0.08 * introT));
      needsRender = true;
    }

    const stale = now - lastMsgTs > 2000;

    // Konstant-Geschwindigkeits-Playback: pro Frame um (Geräte-fs × dt) Samples
    // vorruecken — NICHT um einen Bruchteil der Puffertiefe (das koppelte die
    // Winkelgeschwindigkeit an den Batch-Saegezahn) und NICHT aus Ankunftszeiten
    // geschaetzt (koaleszierende WS-Frames -> Rate-Spikes). fs ist kristall-genau.
    const rate = fsRate || 100;
    const target = Math.max(4, rate * BUF_LATENCY_FRAC);
    // Prebuffer: erst starten, wenn ~½ Ziel gepuffert ist (Modell haelt derweil die
    // Pose) -> kein Dry-Start-Ruckler bei Beginn / nach Stale-Resume.
    if (havePrev && !primed && _queue.length >= Math.max(2, target * 0.5)) primed = true;

    if (havePrev && primed && (_queue.length || frac > 0)) {
      // geglaettete Puffertiefe treibt einen sanften Drift-Regler; der rohe
      // Per-Batch-Saegezahn (0->10->0) wuerde sonst die Geschwindigkeit modulieren.
      bufEMA = bufEMA * 0.9 + _queue.length * 0.1;
      let speed = 1 + BUF_CTRL_GAIN * (bufEMA - target);
      speed = Math.max(BUF_SPEED_MIN, Math.min(BUF_SPEED_MAX, speed));
      let step = rate * dt * speed;
      step = Math.min(step, _queue.length + (1 - frac)); // nie ueber Vorhandenes hinaus
      frac += step;
      while (frac >= 1 && _queue.length) {
        const q = _queue.shift();
        prevQ.set(q[0], q[1], q[2], q[3]);              // konsumiertes Sample = neue Startpose
        frac -= 1;
      }
      if (_queue.length) {
        const q = _queue[0];
        tgtQ.set(q[0], q[1], q[2], q[3]);
        // slerp waehlt intern den kuerzesten Pfad (Hemisphaeren-Flip) -> keine manuelle Umkehr.
        wrapper.quaternion.copy(prevQ).slerp(tgtQ, Math.min(1, frac));
      } else {
        frac = 0;
        primed = false;                                 // trockengelaufen: neu prebuffern
        wrapper.quaternion.copy(prevQ);                 // auf letztem Sample halten
      }
      needsRender = true;
    } else if (stale) {
      wrapper.rotateY(dt * 0.5);                        // Idle-Plattenteller (nur ganz ohne Daten)
      needsRender = true;
    }
    
    if (needsRender) {
      renderer.render(scene, camera);
      needsRender = false;
    }
  }

  // qs = Array von [x,y,z,w] (ein ganzer Watch-Batch, ~100 Hz), fs = bekannte
  // Geräte-Samplerate (Hz). Jedes Quaternion wird korrigiert und in die Playback-Queue
  // gelegt; _tick() spielt sie mit konstantem, fs-getaktetem Tempo ab.
  function updateOrientation(qs, fs) {
    if (!THREE_ || !qs || !qs.length) return;
    const nowT = performance.now();
    const wasStale = nowT - lastMsgTs > 2000;

    if (fs) fsRate = fs;                          // kristall-genaue Rate, keine Schaetzung
    lastMsgTs = nowT;
    if (wasStale) { _queue.length = 0; havePrev = false; frac = 0; bufEMA = 0; primed = false; }

    for (let i = 0; i < qs.length; i++) {
      const q = qs[i];
      if (!q || q.length < 4) continue;
      devQ.set(q[0], q[1], q[2], q[3]).normalize();
      if (!refInv) refInv = devQ.clone().invert();  // erstes Sample = Ruhepose
      // local = q_ref⁻¹ ⊗ q_dev, kalibrierte Spiegel-Achsen-Umkehr (.conjugate),
      // dann C ⊗ local ⊗ C⁻¹ (Z-up -> Y-up Basis-Konjugation).
      dispQ.copy(refInv).multiply(devQ).conjugate().premultiply(C_FIX).multiply(C_INV);
      _queue.push([dispQ.x, dispQ.y, dispQ.z, dispQ.w]);
    }
    // Harte Latenz-Obergrenze: nie mehr als ~2 Batches puffern (Netz-Burst-Schutz).
    if (_queue.length > QUEUE_CAP) _queue.splice(0, _queue.length - QUEUE_CAP);

    // Startpose setzen. Nach einer Luecke auf das NEUESTE Sample snappen (kein Swoop,
    // kein Replay des stale Puffers); beim allerersten Datum auf das aelteste, dann
    // normal weiterspielen.
    if (!havePrev && _queue.length) {
      const q = wasStale ? _queue[_queue.length - 1] : _queue.shift();
      if (wasStale) _queue.length = 0;
      prevQ.set(q[0], q[1], q[2], q[3]);
      havePrev = true; frac = 0;
      if (wrapper) wrapper.quaternion.copy(prevQ);
    }
    needsRender = true;
  }

  // naechstes Sample wird neue Ruhepose; Playback-Zustand zuruecksetzen, damit die
  // alte Basis nicht in die neue Nulllage swoopt.
  function recenter() {
    refInv = null; _queue.length = 0; havePrev = false; frac = 0;
    bufEMA = 0; primed = false; needsRender = true;
  }

  // Screen-Mesh laesst sich nicht per Name isolieren (alle Object_*, ein Material).
  // Diagnose ist ein manueller Schritt (laufender Server + Browser-Konsole) und steht
  // noch aus -- bis dahin bleibt SCREEN_MESH_NAMES leer und setWriting faerbt den
  // gesamten Body als Fallback.
  const SCREEN_MESH_NAMES = new Set();

  function setWriting(on) {
    const nextVal = !!on;
    if (writing === nextVal && handle._model) return;
    writing = nextVal;
    if (!handle._model || !THREE_) return;
    needsRender = true;
    const color = writing ? colorActive : colorDefault;
    handle._model.traverse((o) => {
      if (!o.isMesh) return;
      const isScreen = SCREEN_MESH_NAMES.size === 0 ? true : SCREEN_MESH_NAMES.has(o._name);
      o.material.emissive.copy(color);
      o.material.emissiveIntensity = isScreen && writing ? 0.3 : 0.0;
    });
  }

  return handle;
}
