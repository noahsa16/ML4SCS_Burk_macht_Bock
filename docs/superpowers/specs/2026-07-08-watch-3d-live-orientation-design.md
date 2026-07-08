# Live 3D-Watch-Orientierung (Three.js) — Design

**Datum:** 2026-07-08
**Status:** abgesegnet (Brainstorming), Implementierungsplan ausstehend
**Autor:** Noah Samel (mit Claude)

## Ziel

Eine in Echtzeit mitdrehende 3D-Watch im Dashboard, gespeist aus dem
`attitude.quaternion` der Apple Watch. Sie sitzt in der „live inference"-Sektion
der Recording-Seite (Layout-Variante C: Watch-Viewport ~57 % links, die drei
bestehenden Inferenz-Karten als rechte Spalte) und färbt sich grün, wenn die
Live-Inferenz „writing" meldet. Zweck: Präsentations-Beweis, dass die Watch-Daten
echt sind und live ausgewertet werden — Bewegung und Auswertung in einem Blick.

**Nicht-Ziel (YAGNI):** kein Replay-Scrubber, keine Session-Auswahl, keine
Persistenz der Orientierung. Reiner Live-Spiegel. Replay bleibt eine spätere,
separate Ausbaustufe.

## Kontext / Ausgangslage

- Die Watch erfasst `qx/qy/qz/qw` (`motion.attitude.quaternion`, forward-only
  Capture) → landet in der Watch-CSV, ist aber **passiv**: vom ML/Feature-Set
  ungenutzt, und **nicht** im WebSocket-Tick (der broadcastet nur die
  acc/gyro-Magnitude-Aggregate).
- Das Projekt lädt Libs bereits per CDN (`dashboard.html` zieht Chart.js von
  jsdelivr) → Three.js per identischem Muster, kein Build-Step.
- Ein CC-BY-4.0-Watch-Modell liegt schon im Repo:
  `scripts/plots/assets/smartwatch-2/scene.gltf` + `scene.bin` (9,4 MB Geometrie,
  keine externen Texturen, 10 Meshes / 1 Material). Autor `_tegarma` (Sketchfab)
  — **Attribution ist Lizenzpflicht** und muss im UI stehen.
- Es gibt ein etabliertes Canvas-Lifecycle-Muster: `session_detail.js` reißt seine
  Chart.js-Canvases in `onHide()` via `_destroyAlignCharts()` ab. Der neue
  WebGL-Canvas folgt demselben Vier-Funktions-Seitenkontrakt
  (`mount/onStatus/onShow/onHide`).

## Kern-Entscheidungen

### Transport: pro Watch-Batch broadcasten (~10 Hz), NICHT nur der 1-Hz-Tick

Der `/watch`-Handler legt das jüngste valide Quaternion in `state.last_orientation`
ab und sendet es **throttled (≤ 10 Hz)** über den bestehenden `_broadcast()` als
`{type: "orientation", q: [x, y, z, w]}`. Grund: der 1-Hz-Status-Tick wäre für ein
„wave your wrist"-Demo spürbar träge (bis 1 s Lag); ~10 Hz + client-seitige
slerp-Glättung auf 60 fps wirkt wie ein echter Spiegel. Die WS-Infrastruktur
existiert bereits, der Mehraufwand ist ein throttled Broadcast-Call.

### Koordinaten-Korrektur (bewusst eingeplanter Fummel-Punkt)

CoreMotions `attitude.quaternion` lebt im Device-Frame (andere Achsenlage als
Three.js' y-up-Rechtssystem). Das rohe Quaternion legt das Modell schief auf →
es braucht ein **konstantes Korrektur-Quaternion** `q_render = q_fix * q_device`,
`q_fix` einmal empirisch eingestellt, plus optional einen „recenter"-Button
(setzt `q_fix` so, dass die aktuelle Pose zur Ruhelage wird). Das ist der einzige
echte Integrations-Risikopunkt.

### Three.js-Laden: lazy per importmap

Eine `importmap` in `dashboard.html` mappt `three` + `three/addons/` auf
jsdelivr-ESM-URLs. Der Rendering-Helfer importiert Three.js + `GLTFLoader`
**dynamisch** (`import()`) erst beim Mounten der Recording-Seite → die 9,4 MB
`scene.bin` und der Three.js-Core belasten keine andere Seite.

## Architektur

### Backend (`src/server/`)

- **`state.py`** — neues Feld `last_orientation: Optional[list[float]]` (letztes
  valides `[qx,qy,qz,qw]`), plus `last_orientation_broadcast_ms` fürs Throttling.
- **`routes/watch.py`** — beim Batch-Verarbeiten das jüngste Sample mit
  vollständigem Quaternion in `state.last_orientation` schreiben; wenn seit dem
  letzten Orientierungs-Broadcast ≥ 100 ms vergangen sind,
  `await _broadcast({"type": "orientation", "q": state.last_orientation})`.
  Legacy-Streams ohne Quaternion (None) → kein Broadcast, Feld bleibt/wird null.
- **Keine neue Route, kein neues Pydantic-Schema.** `WatchSample` trägt qx…qw
  bereits.

### Frontend — Rendering-Helfer (`static/js/core/watch3d.js`, NEU)

Self-contained, ohne Wissen über die Recording-Seite (isoliert testbar):

- `initWatch3D(canvas) -> handle` — WebGLRenderer + PerspectiveCamera +
  Ambient/Directional-Light; lazy `import()` von `three` + `GLTFLoader`; lädt
  `/static/assets/watch/scene.gltf`; startet die rAF-Schleife.
- `updateOrientation([x,y,z,w])` — setzt das Ziel-Quaternion (nach
  Korrektur-Transform); die rAF-Schleife slerpt das Modell pro Frame dorthin.
- `setWriting(bool)` — grüner Rim-/Emissive-Akzent an/aus.
- `destroy()` — rAF stoppen, `renderer.dispose()`, GLTF-Geometrie/Material
  freigeben, Resize-Listener entfernen (GPU-Context-Leak-Schutz).
- Interne Helfer: Korrektur-Quaternion + optionales `recenter()`; Resize-Handling.

### Frontend — Verdrahtung

- **`static/views/recording.html`** — die `rec-sec--inference`-Sektion auf das
  Split-Layout C umbauen: Watch-`<canvas>` (~57 %) links, die drei bestehenden
  Karten (`--now`, `--spark`, `--today`) als rechte Spalte; CC-BY-Credit-Zeile.
- **`static/css/recording.css`** — Split-Grid + Canvas-Aspekt + grüner
  writing-Akzent + Credit-Zeilen-Stil.
- **`static/js/pages/recording.js`** — `mount()` → `initWatch3D`;
  `onStatus(payload)` → bei `payload.type === "orientation"` `updateOrientation`,
  bei `live_inference` `setWriting(payload.live_inference.writing)`;
  `onHide()` → `destroy()`.

### Modell-Asset

- `scene.gltf` + `scene.bin` nach `static/assets/watch/` spiegeln (das Dashboard
  serviert nur `static/`; die Kopie unter `scripts/plots/assets/` bleibt für die
  Matplotlib-Nutzung unangetastet). `license.txt` mitkopieren.

## Datenfluss

```
Apple Watch (attitude.quaternion, forward-only)
  → POST /watch (Batch)
  → routes/watch.py: state.last_orientation = [qx,qy,qz,qw]
                     throttle ≥100ms → await _broadcast({type:"orientation", q:[...]})
  → WebSocket /ws
  → recording.js onStatus() → watch3d.updateOrientation([...])
  → watch3d rAF-Loop: model.quaternion.slerp(q_fix*q_target, t)  (60 fps)

Live-Inferenz (bestehender live_inference-Payload, writing-Flag)
  → recording.js onStatus() → watch3d.setWriting(bool) → grüner Akzent
```

## Graceful degradation

- Kein Quaternion (Legacy-Watch / kein Stream) → Platzhalter „no orientation
  data" im Panel statt eingefrorener Watch.
- Kein WebGL im Browser → Panel ausblenden (Feature-Detect), Inferenz-Karten
  bleiben.
- GLTF-Ladefehler → Platzhalter + Konsolen-Warnung, restliche Seite intakt.

## Fehlerbehandlung / Performance

- Teardown ist **Pflicht** (WebGL-Context-Leak): `destroy()` in `onHide()`,
  gerendert wird nur, während die Recording-Seite sichtbar ist.
- Throttling backend-seitig (≤ 10 Hz) hält die WS-Bandbreite klein
  (~40 B/Nachricht).
- slerp-Faktor so wählen, dass ~1 Batch Lag (~100 ms) glatt überbrückt wird,
  ohne sichtbares Nachziehen.

## Testing

- **Backend-Unit** (`tests/test_endpoints.py` o. neu): nach einem `/watch`-Batch
  mit Quaternion enthält `state.last_orientation` die Werte; ein Batch ohne
  Quaternion lässt es null. Throttle-Logik: zwei schnelle Batches → höchstens ein
  Orientierungs-Broadcast in 100 ms (mit gemockter Zeit/Broadcast).
- **Static-Smoke** (`tests/test_dashboard_static.py`): `static/js/core/watch3d.js`
  in die Parametrize-Liste; die gltf/bin-Assets optional mit aufnehmen (404-Trap).
- **Three.js-Rendering** bleibt manueller Smoke-Test (kein WebGL/DOM in pytest):
  Watch dreht mit echtem Stream, grün bei writing, sauberer Teardown beim
  Tab-Wechsel, Legacy-Stream zeigt Platzhalter.

## Betroffene Dateien (Überblick)

| Datei | Änderung |
|---|---|
| `src/server/state.py` | `last_orientation` + Throttle-Timestamp |
| `src/server/routes/watch.py` | Quaternion cachen + throttled broadcasten |
| `static/js/core/watch3d.js` | **neu** — Three.js-Rendering-Helfer |
| `static/views/recording.html` | Inferenz-Sektion → Split-Layout C + Credit |
| `static/css/recording.css` | Split-Grid, Canvas, writing-Akzent, Credit |
| `static/js/pages/recording.js` | mount/onStatus/onHide-Verdrahtung |
| `dashboard.html` | Three.js-importmap |
| `static/assets/watch/` | **neu** — gespiegeltes gltf/bin + license |
| `tests/test_endpoints.py`, `tests/test_dashboard_static.py` | neue Fälle |

## Offene Punkte für den Implementierungsplan

1. Korrektur-Quaternion `q_fix` empirisch bestimmen (Watch flach auf Tisch =
   Ruhepose) — evtl. „recenter"-Button statt fixem Wert.
2. Genaue jsdelivr-Three.js-Version + importmap-Einträge fixieren.
3. slerp-Faktor / Kamera-Framing am echten Modell justieren.
