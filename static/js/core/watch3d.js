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
      wrapper.userData.baseScale = scale;
      wrapper.scale.setScalar(scale * 0.92);       // Intro-Startskala, siehe _tick()
      wrapper.add(model);
      scene.add(wrapper);
      handle._model = model;                       // fuer Step 5 (Material-Split)
    }).catch((e) => console.warn('watch3d: GLTF load failed', e));
  }

  function _tick() {
    if (disposed) return;
    raf = requestAnimationFrame(_tick);
    if (!renderer || !wrapper) return;
    const now = performance.now();
    const dt = Math.min(0.05, (now - (_tick._prev || now)) / 1000);
    _tick._prev = now;

    // Intro: 0.92 -> 1.0 ueber ~600 ms, einmalig nach dem Laden
    if (introT < 1) {
      introT = Math.min(1, introT + dt / 0.6);
      wrapper.scale.setScalar(wrapper.userData.baseScale * (0.92 + 0.08 * introT));
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

  // Screen-Mesh laesst sich nicht per Name isolieren (alle Object_*, ein Material).
  // Diagnose ist ein manueller Schritt (laufender Server + Browser-Konsole) und steht
  // noch aus -- bis dahin bleibt SCREEN_MESH_NAMES leer und setWriting faerbt den
  // gesamten Body als Fallback.
  const SCREEN_MESH_NAMES = new Set();

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

  return handle;
}
