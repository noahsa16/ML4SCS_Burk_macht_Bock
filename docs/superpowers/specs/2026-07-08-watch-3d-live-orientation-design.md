# Live 3D-Watch-Orientierung (Three.js) — Design

**Datum:** 2026-07-08
**Status:** abgesegnet (Brainstorming) + Fable-Rendering-Review eingearbeitet; Implementierungsplan ausstehend
**Autor:** Noah Samel (mit Claude)

## Ziel

Eine in Echtzeit mitdrehende, **präsentations-schöne** 3D-Watch im Dashboard,
gespeist aus dem `attitude.quaternion` der Apple Watch. Sie sitzt in der
„live inference"-Sektion der Recording-Seite (Layout-Variante C: Watch-Viewport
~57 % links, die drei bestehenden Inferenz-Karten als rechte Spalte). Das
**Watch-Display leuchtet grün**, wenn die Live-Inferenz „writing" meldet. Zweck:
Wow-Beweis für die Abschlusspräsentation, dass die Watch-Daten echt sind und live
ausgewertet werden — Bewegung und Auswertung in einem Blick.

Die Messlatte ist **„product shot", nicht „clay render"**: realistisch beleuchtet,
reflektierend, sauber kantengeglättet auf dem Beamer.

**Nicht-Ziel (YAGNI):** kein Replay-Scrubber, keine Session-Auswahl, keine
Persistenz der Orientierung. Reiner Live-Spiegel. Replay = spätere, separate Stufe.

## Kontext / Ausgangslage

- Die Watch erfasst `qx/qy/qz/qw` (`motion.attitude.quaternion`, forward-only) →
  landet in der Watch-CSV, ist aber **passiv** und **nicht** im WebSocket-Tick.
- Libs werden bereits per CDN geladen (`dashboard.html` → Chart.js von jsdelivr) →
  Three.js per identischem Muster (ES-Module + importmap), kein Build-Step.
- CC-BY-4.0-Watch-Modell im Repo: `scripts/plots/assets/smartwatch-2/scene.gltf`
  + `scene.bin` (9,4 MB, ~347k Tris, 10 Meshes, **1 PBR-Material** einheitlich
  hellgrau `baseColor 0.935 / metallic 0.27 / roughness 0.67`, **keine Texturen**,
  degenerierte all-null UVs). Autor `_tegarma` — **Attribution ist Lizenzpflicht**.
- Canvas-Lifecycle-Muster existiert (`session_detail.js` → `_destroyAlignCharts()`
  in `onHide()`).

## Kern-Entscheidungen

### Transport: pro Watch-Batch broadcasten (~10 Hz)

Der `/watch`-Handler cached das jüngste valide Quaternion in
`state.last_orientation` und sendet es **throttled (≤ 10 Hz)** über den
bestehenden `_broadcast()` als `{type: "orientation", q: [x,y,z,w]}`. Grund:
der 1-Hz-Tick wäre für ein „wave your wrist"-Demo träge; ~10 Hz + client-seitiger
slerp auf 60 fps wirkt wie ein echter Spiegel.

## §0 — Korrektheits-Fixes (VOR allem anderen; via Code verifiziert)

Zwei Bugs, die die naive Verdrahtung tot machen. Beide an der Quelle bestätigt.

**A. Orientierungs-Nachrichten erreichen `onStatus()` nie.** `static/js/core/ws.js`
routet in `ws.onmessage` **ausschließlich** `msg.type === 'status'` nach
`handleStatus` → `_activePageDispatch`; alles andere wird verworfen. Ein
`{type:"orientation"}` fällt still durch.
**Fix:** in `ws.js` einen dedizierten, leichten Subscriber ergänzen
(`setOrientationHandler(fn)`), der die Status-Cluster-Pipeline **umgeht** — die
10-Hz-Nachricht darf nicht die volle Pill/Badge-Maschinerie durchlaufen, und
Seiten erwarten in `onStatus(s)` status-förmige Payloads (`recording.js:775` liest
`s.live_inference` unbedingt). `ws.js` gehört damit in die Datei-Tabelle.

**B. Lifecycle-Mismatch → tote Watch nach einem Tab-Wechsel.** `dashboard.js` ruft
`mount(slot)` **genau einmal** pro Seitenleben (`if (slot && !mounted.has(pageId))`),
`onShow`/`onHide` bei **jedem** Wechsel. Init-in-`mount` + destroy-in-`onHide`
hinterlässt nach Recording→Sessions→Recording einen zerstörten Renderer.
**Fix:** Init in `onShow()`, Destroy in `onHide()` (symmetrisch). Die **geparste
GLTF modul-cachen**, damit ein Re-Show nicht 9,4 MB neu lädt/parst (Parsen von
347k Tris ist ein sichtbarer Ruckler).

## §1 — Rendering-Baseline („Ambient + Directional" reicht NICHT)

Das Material ist einheitlich hellgrau, teil-metallisch, ohne Texturen → unter
flachem Licht garantiert Plastik-Grau. Pflicht-Baseline, nach Hebelwirkung:

1. **Environment-Map — der größte Hebel, nicht verhandelbar.** Ein teil-metallisches
   Material ohne `scene.environment` reflektiert *nichts*. `RoomEnvironment` +
   `PMREMGenerator` braucht **keine externe Datei**:
   ```js
   const pmrem = new THREE.PMREMGenerator(renderer);
   scene.environment = pmrem.fromScene(new RoomEnvironment()).texture;
   pmrem.dispose();
   ```
   Einmalkosten ~ms, null pro Frame. (Env-Textur beim Teardown disposen.)
2. **`renderer.toneMapping = THREE.ACESFilmicToneMapping`** (+ `toneMappingExposure`
   ≈ 1.1–1.3) und explizit `outputColorSpace = THREE.SRGBColorSpace`. Gratis; ohne
   ACES clippen die Env-Highlights hässlich.
3. **`antialias: true` + `renderer.setPixelRatio(Math.min(devicePixelRatio, 2))`.**
   Pflicht — der Beamer vergrößert Alias-Kanten an Metallrändern brutal.
4. **Licht:** ein Key-`DirectionalLight` + schwaches Ambient; die Env-Map ist der
   Fill. Hinweis: seit three r155 ist Beleuchtung physikalisch — Intensitäts-Werte
   aus alten Tutorials sind um ~π falsch; gegen die **gepinnte** Version tunen.
5. **Boden-/Kontaktschatten: weglassen.** Die Watch spiegelt ein Handgelenk und
   kippt kopfüber — eine Bodenebene ist semantisch falsch. Stattdessen
   **transparenter Renderer** (`alpha: true`) + CSS-Radial-Vignette als Backdrop.
6. **Bloom / EffectComposer: weglassen.** Voller Post-Chain = echte GPU-Kosten +
   bricht den Transparenz-Trick. Emissive-Material + CSS-Glow (Radial-Gradient /
   `drop-shadow` hinter dem Canvas) liest sich aus Publikumsdistanz wie Bloom, ~0 Kosten.

## §2 — Dieses Modell konkret: Pivot + Material-Split (beides Pflicht)

- **Pivot: Geometrie liegt weit off-origin** (Accessor-Bounds ~x∈[0.4,14.6],
  z∈[9.6,19.2]) **und** der Sketchfab-Root trägt eine gebackene Z-up→Y-up-`matrix`.
  Ein Quaternion direkt auf `gltf.scene` **umkreist die Watch um einen fernen Punkt
  und schleudert sie aus dem Bild** und überschreibt die Root-Matrix.
  **Pflicht:** `new THREE.Box3().setFromObject(gltf.scene)` → Mesh in eine
  Wrapper-`Group` re-zentrieren, das Device-Quaternion **nur auf den Wrapper**
  anwenden.
- **Material-Split — bestes Wow-pro-Aufwand.** Die 10 Meshes (`Object_0..9`)
  trennen mit hoher Wahrscheinlichkeit Display/Body/Armband. UVs sind degeneriert →
  Textur-Rettung unmöglich; Material-Zuweisung ist der **einzige** Weg und ist
  billig: Display = fast-schwarzes Glas (`roughness 0.05, metalness 0`) mit grünem
  **Emissive** (= der „writing"-Zustand); Body = `metalness 0.9, roughness 0.3`;
  Armband = dunkel, `roughness 0.8`.
  **Fallback (Spec-Pflichtnotiz):** isolieren die Meshes kein Display, dann
  Ganzkörper-Dunkelmetall + Rim-Light; **Budget max. 1 h**, bevor ein besseres
  Modell getauscht wird, statt einen Knet-Render zu polieren.
- **Kamera:** Produkt-Framing mit langer Brennweite — **FOV ~28°**, Kamera leicht
  erhöht, Watch ~70 % Bildhöhe. Default 50–75° FOV sieht aus wie ein Handy-Schnappschuss.

## §3 — Koordinaten-Korrektur (recenter ist PFLICHT, nicht optional)

CoreMotions Default-Referenz (`xArbitraryZVertical`) wählt beim Start des
Motion-Managers einen **arbiträren Yaw** — bei jedem App-Start anders. Ein
konstantes Compile-Time-`q_fix` korrigiert nur die Achsenkonvention, nicht das
zufällige Heading. Deshalb:

- `q_display = q_axisfix ⊗ q_ref⁻¹ ⊗ q_device`, wobei `q_ref` per
  **„recenter"-Button** erfasst wird (und auto beim ersten Sample). Recenter wird
  damit **Pflicht** + Demo-Versicherung.
- **Kein Handedness-Flip** (beide Frames rechtshändig) — eine reine Rotations-
  Korrektur genügt; explizit so festhalten, damit niemand an Vorzeichen fummelt.
- **Quaternion-Double-Cover:** vor dem Slerp Ziel negieren, wenn
  `dot(current, target) < 0` (sonst gelegentliche 360°-Drehungen den langen Weg).
- **Framerate-unabhängige Dämpfung:** `t = 1 - Math.pow(0.0001, dt)` statt fixem
  Pro-Frame-Faktor.

## §4 — Wow-Politur, nach Wow-pro-Aufwand

1. **Display leuchtet grün** bei „writing" (Emissive + CSS-Panel-Glow, `--green`-
   Token) — die Demo-Story in einem Bild. Weit besser als Ganzkörper-Tönung.
2. **Env-Map + ACES** (§1) — ~6 Zeilen, verwandelt den Look.
3. **Idle-Auto-Rotate:** keine Orientierungs-Nachricht > 2 s → sanft in einen
   langsamen Plattenteller einblenden (= zugleich der Stale-/Legacy-Fallback,
   besser als ein statischer Platzhalter; „no orientation data" bleibt dem
   *nie-Daten*-Fall vorbehalten). Bei Daten-Rückkehr zurück-slerpen — doppelt als
   Proof-of-Liveness.
4. **Intro:** Scale 0.92→1 + Opacity-Fade über ~600 ms nach GLTF-Load (in der rAF-Schleife).
5. **Writing-Puls:** `emissiveIntensity` mit langsamer Sinuskurve während „writing"
   + passender CSS-Glow am Panel-Rand.
6. **Recenter-Button** im Haus-Stil (`/ recenter`-Eyebrow).

## Architektur

### Backend (`src/server/`)

- **`state.py`** — `last_orientation: Optional[list[float]]` + `last_orientation_broadcast_ms` (Throttle).
- **`routes/watch.py`** — jüngstes vollständiges Quaternion in `state.last_orientation`;
  wenn seit letztem Orientierungs-Broadcast ≥ 100 ms → `await _broadcast({"type":"orientation","q": state.last_orientation})`. Legacy-Streams (None) → kein Broadcast.
- **Broadcast-Fan-out beachten:** `_broadcast` geht an **alle** WS-Clients inkl.
  iPhone-Bridge (`ServerCommandListener`, mit dokumentierter Reconnect-Storm-
  Historie) — vor dem 10-Hz-Stream verifizieren, dass die Bridge unbekannte
  `type`s ignoriert.
- Keine neue Route, kein neues Schema (`WatchSample` trägt qx…qw bereits).

### Frontend — Rendering-Helfer (`static/js/core/watch3d.js`, NEU)

Self-contained (isoliert testbar): `initWatch3D(canvas)`, `updateOrientation([x,y,z,w])`,
`setWriting(bool)`, `recenter()`, `destroy()`. Lazy `import()` von `three` +
`GLTFLoader` + `RoomEnvironment`. Enthält Renderer-Setup (§1), Pivot-Wrapper +
Material-Split (§2), Korrektur/Slerp (§3), Idle-Rotate/Intro/Puls (§4).

### Frontend — Transport (`static/js/core/ws.js`)

`setOrientationHandler(fn)` + Branch in `ws.onmessage` für `type==='orientation'`,
der `fn(q)` direkt aufruft (umgeht `handleStatus`).

### Frontend — Verdrahtung

- **`static/views/recording.html`** — `rec-sec--inference` auf Split-Layout C
  (Canvas ~57 % links, 3 Karten rechts) + CC-BY-Credit + `/ recenter`-Button.
- **`static/css/recording.css`** — Split-Grid, Canvas-Aspekt, transparente-Canvas-
  Vignette (theme-abhängig), grüner writing-Glow, Credit-Stil.
- **`static/js/pages/recording.js`** — `onShow()` → `initWatch3D` + `setOrientationHandler`;
  `live_inference`-Tick → `setWriting`; `onHide()` → `destroy()` + Handler abmelden.

### Themes (nicht übersehen)

Dashboard ist **hell (warmes Papier) per Default**, dunkel via
`body[data-theme="dark"]` (`base.css`). Transparenter Renderer + CSS-Backdrop löst
das meiste; Exposure/Vignette pro Theme prüfen. Das Grün aus
`getComputedStyle` `--green` ziehen (oklch → via computed rgb in
`THREE.Color().setStyle()`), **nie** `0x00ff00` hardcoden.

### Three.js-Laden (importmap in `dashboard.html`)

Exakte Version pinnen (z. B. `three@0.1xx`) für **beide** `three` **und**
`three/addons/` → `.../examples/jsm/`; die importmap **vor** dem
`dashboard.js`-Module-Script platzieren (nur eine importmap pro Seite erlaubt).

### Modell-Asset

`scene.gltf` + `scene.bin` (+ `license.txt`) nach `static/assets/watch/` spiegeln.
**Asset-Gewicht:** 9,4 MB ist auf localhost ok, aber der Demo-Pfad nutzt einen
Cloudflare-Tunnel → entweder einmalig offline `gltfpack`/meshopt auf ~1–2 MB
komprimieren (Decoder vom selben CDN, kein Build-Step) **oder** mindestens
`GLTFLoader.onProgress` in einen Panel-Shimmer/Prozent verdrahten, damit die Demo
nie eine leere Box zeigt.

## Datenfluss

```
Watch attitude.quaternion → POST /watch (Batch)
  → routes/watch.py: state.last_orientation=[..]; throttle ≥100ms → await _broadcast({type:"orientation",q:[..]})
  → WebSocket /ws → ws.js: type==='orientation' → orientationHandler(q)
  → watch3d.updateOrientation(q) → rAF: wrapper.quaternion.slerp(q_display, t)  (60fps)
live_inference-Payload (writing) → recording.js → watch3d.setWriting(bool) → grünes Display-Emissive + Glow
```

## Fehlerbehandlung / Teardown (Vollständigkeit ist Pflicht)

WebGL-Context-Leak-Schutz in `destroy()`: rAF cancel, `ResizeObserver.disconnect()`
(Resize via **ResizeObserver auf dem Canvas-Wrapper**, nicht `window` — die
57 %-Spalte ändert Breite bei Grid-Reflows), traverse-dispose Geometrien/Materialien,
PMREM-Env-Textur disposen, `renderer.dispose()` **+ `renderer.forceContextLoss()`**
(Browser halten ≤ ~16 WebGL-Contexts; wiederholte Tab-Flips ohne Context-Loss
killen den Renderer irgendwann mitten in der Demo). Gerendert wird nur, während die
Recording-Seite sichtbar ist.

## Graceful degradation

- Kein Quaternion / Stale > 2 s → **Idle-Auto-Rotate** (nicht eingefroren).
- Nie Daten gehabt → Platzhalter „no orientation data".
- Kein WebGL → Panel ausblenden (Feature-Detect), Inferenz-Karten bleiben.
- GLTF-Ladefehler → Platzhalter + Konsolen-Warnung, restliche Seite intakt.

## Testing

- **Backend-Unit** (`tests/test_endpoints.py`): `/watch`-Batch mit Quaternion →
  `state.last_orientation` gesetzt; ohne → null. Throttle: zwei schnelle Batches →
  höchstens ein Orientierungs-Broadcast in 100 ms (gemockte Zeit/Broadcast).
- **Static-Smoke** (`tests/test_dashboard_static.py`): `static/js/core/watch3d.js`
  in die Parametrize-Liste; gltf/bin-Assets als 404-Trap aufnehmen.
- **Three.js-Rendering** bleibt manueller Smoke-Test (kein WebGL/DOM in pytest):
  Watch dreht mit echtem Stream, Display grün bei writing, Idle-Rotate bei Stille,
  sauberer Teardown über mehrere Tab-Wechsel (Context-Count stabil), Legacy-Stream
  → Idle statt eingefroren, hell/dunkel-Theme beide sauber.

## Betroffene Dateien

| Datei | Änderung |
|---|---|
| `src/server/state.py` | `last_orientation` + Throttle-Timestamp |
| `src/server/routes/watch.py` | Quaternion cachen + throttled broadcasten |
| `static/js/core/ws.js` | **§0-A** — `setOrientationHandler` + orientation-Branch |
| `static/js/core/watch3d.js` | **neu** — Three.js-Helfer (Render-Baseline, Pivot, Material-Split, Slerp, Politur) |
| `static/views/recording.html` | Split-Layout C + Credit + recenter-Button |
| `static/css/recording.css` | Split-Grid, Canvas, Vignette, writing-Glow, Credit |
| `static/js/pages/recording.js` | **§0-B** — init in `onShow`, destroy in `onHide` |
| `dashboard.html` | Three.js-importmap (gepinnt, vor dashboard.js) |
| `static/assets/watch/` | **neu** — gltf/bin/license (evtl. gltfpack-komprimiert) |
| `tests/test_endpoints.py`, `tests/test_dashboard_static.py` | neue Fälle |

## Offene Punkte für den Implementierungsplan

1. `q_axisfix` empirisch bestimmen; `q_ref` per recenter (auto beim ersten Sample).
2. Exakte jsdelivr-three.js-Version fixieren (three + addons/examples/jsm).
3. Mesh→Material-Mapping am echten Modell verifizieren (Display isolierbar?);
   sonst Fallback-Pfad + 1-h-Budget.
4. Kamera-Framing/FOV + Exposure am echten Modell justieren (hell/dunkel).
5. Entscheidung gltfpack-Kompression vs. Loading-Shimmer.
