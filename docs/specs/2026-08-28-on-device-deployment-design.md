# On-Device-Deployment: serverloser Schreib-Tracker (Design)

**Datum:** 2026-08-28
**Status:** aktiv (Rev. 2, nach Review)
**Vorarbeit:** `models/runs/pod_20260825/`, `models/runs/pod_raw50/`,
`docs/specs/2026-06-24-passive-tracker-mode-design.md` (abgelöst, siehe §10),
`reports/hmm_context_ladder.md`

## 1. Ziel

Der Schreib-Detektor läuft heute server-seitig: Watch streamt volle IMU ans
iPhone, das iPhone POSTet an den FastAPI-Server, der Server inferiert und
broadcastet zurück. Ziel ist ein Stack **ohne Server** mit zwei Betriebsarten:

- **Aktive Schreibphase** (iPhone). Der Nutzer startet bewusst eine Session
  — Vorbild ist die Fokus-App Forest, nur misst diese hier die tatsächliche
  Ausbeute statt Anwesenheit. Die Watch streamt live, das iPhone inferiert,
  am Ende steht „von 45 min hast du 31 min geschrieben".
- **Passiver Ganztags-Tracker** (Watch). `CMSensorRecorder` zeichnet
  systemseitig auf. **Sie zeichnet nur auf — sie inferiert nicht, während die
  App suspendiert oder beendet ist.** Bei der nächsten von watchOS gewährten
  Ausführungszeit liest die App die neuen Samples seit dem letzten Cursor,
  inferiert **nachträglich** und synchronisiert aggregierte Intervalle ans
  iPhone.

**Harte Randbedingung:** Die bestehende Studien-Pipeline (Pen-Ground-Truth,
Server, Study Mode, `data/raw/`) bleibt unverändert daneben bestehen. Sie ist
die Grundlage der laufenden Forschung; dieses Deployment ergänzt sie, ersetzt
sie nicht.

### 1.1 Was `CMSensorRecorder` zusichert — und was nicht

Alle Werte aus Apples Referenz zu `recordAccelerometer(forDuration:)` und
`accelerometerData(from:to:)`, abgerufen 2026-08-28.

| Eigenschaft | Wert | Folge fürs Design |
|---|---|---|
| Aufzeichnung pro Auftrag | **max. 43.200 s (12 h)** | Aufträge müssen erneuert werden; eine Strategie fürs Re-Arming ist Pflicht |
| Spanne **pro Abruf** | **ebenfalls max. 12 h** | Nachholen nach längerer Pause muss in ≤ 12-h-Stücke zerlegt werden |
| Datenrückhalt | **bis 3 Tage** | ein verpasster Tag ist aufholbar, ein verpasstes Wochenende nicht |
| Verzögerung neuer Samples | **bis 3 Minuten** | der Cursor darf nie auf „jetzt" springen, sonst gehen die jüngsten Samples dauerhaft verloren |
| Rate | 50 Hz | passt exakt auf den Modell-Kontrakt (§2) |
| Verhalten bei Lücken | „no data entries are returned for those gaps" | Lücken sind **still**; nur eine zeitbasierte Prüfung findet sie |
| Ausführung der App | **nicht garantiert** | Background Refresh feuert nach Systemermessen, nicht nach Zeitplan |

Daraus folgen vier Anforderungen, die in Teilprojekt 3 umgesetzt und im Spike
(§6) gemessen werden:

1. **Persistenter `lastProcessedTimestamp`** als Cursor, der App-Kill und
   Neustart überlebt.
2. **Re-Arming-Strategie:** vor Ablauf der 12 h einen neuen Auftrag stellen,
   und bei jedem Aufwachen prüfen, ob überhaupt einer aktiv ist.
3. **Idempotenz:** doppelte oder überlappende Abrufe dürfen Schreibzeit nicht
   doppelt zählen. Der Cursor ist die einzige Wahrheit, nicht der Abrufzeitpunkt.
4. **Ehrliche Lückenbuchhaltung:** nicht verarbeitete Zeit wird als
   *unbekannt* geführt, nicht als *nicht geschrieben* (§4).
5. **Sicherheitsabstand am Cursor-Kopf:** abgerufen wird nur bis
   `jetzt − 5 min`. Die dokumentierte Verzögerung von bis zu drei Minuten
   würde sonst dazu führen, dass der Cursor über noch nicht verfügbare
   Samples hinwegzieht und diese nie wieder geholt werden.
6. **Gestückelter Nachholvorgang:** ein Rückstand von mehr als 12 h wird in
   Teilabrufe zerlegt, weil ein einzelner Abruf höchstens 12 h umspannen darf.

„Einmal einschalten und danach garantiert jeden Tag vollständig" ist mit
dieser API **nicht** zusicherbar. Der Spike misst, wie nah man herankommt.

## 2. Modellwahl

| Pfad | Modell | Pool | Hz | Kanäle | Parameter | N | Accuracy | Seed-σ |
|---|---|---|---:|---:|---:|---:|---:|---:|
| aktiv | `tcn_bigru` | legacy | 50 | 6 | 19.089 | 32 | 0.9209 | 0.0057 |
| passiv | `tcn6` | modern50 `raw_accel` | 50 | 3 | 9.249 | 23 | 0.8840 | 0.0035 |

Beide: 5-s-Fenster (250 Samples), `zscore=False`, `max_gap_ms=2500`,
grouped-5-fold über 3 Seeds. Zahlen aus
`models/runs/*/results/grid_winner_*.csv`, Parameterzahlen aus der Registry
`src/training/deep/models.py`.

**Kanäle.** Aktiv sind das `userAcceleration` (ax/ay/az) + `rotationRate`
(rx/ry/rz) aus `CMDeviceMotion`, sechs Kanäle in dieser Reihenfolge. Passiv
ist es die **rohe Gesamtbeschleunigung** — **drei** Kanäle in der Reihenfolge
x, y, z, gebildet als `(ax+gx, ay+gy, az+gz)`. Genau das liefert
`CMSensorRecorder`, weil CoreMotion die Schwerkraft nur im gyro-fusionierten
`CMDeviceMotion` herausrechnet. Damit gilt train == deploy; der frühere
Ansatz „auf `userAcceleration` trainieren, auf Roh deployen" brach um
8–20 pp ein.

**Warum nicht 9 Kanäle (mit Gravity).** Für `tcn_bigru` ist Gravity messbar
neutral: 0.90927 (6ch) gegen 0.90987 (9ch) auf identischen Folds und Seeds
innerhalb der Modern-23-Kohorte, bei Seed-σ 0.002. Den Gravity-Gewinn hat
`tcn6` (0.9022 → 0.9108). Ein 9-Kanal-Modell liefe zudem auf 100 Hz und damit
auf 500-Sample-Fenstern — das ergäbe eine zweite Vorverarbeitungsstrecke in
der App, weil der passive Pfad wegen `CMSensorRecorder` zwingend bei 50 Hz
bleibt. Die 6ch/50-Hz-Wahl hält beide Modelle auf demselben Kontrakt.

**Die 0.9209 sind nicht mit den 0.9108 vergleichbar** — die Modern-Kohorte
(23) ist eine echte Teilmenge der Legacy-Kohorte (32), ein direkter Vergleich
vermischt Pool mit Kohortengrösse. Die Wahl stützt sich auf die
Deployment-Argumente oben, nicht auf diese Differenz.

### 2.1 Zwischen-Checkpoints und finales Deployment-Artefakt

**Für Spike und Paritätsarbeit** werden die vorhandenen Checkpoints (Seed 42)
verwendet:

```
aktiv:  models/runs/pod_20260825/results/hp_grid/legacy/tcn_bigru_confirm/
        models_tcn_bigru-g00-s42/final.pt
passiv: models/runs/pod_raw50/hp_grid/modern50/tcn6_raw50/
        models_tcn6-g00-s42/final.pt
```

Diese `final.pt` sind **nicht auf allen Personen trainiert**, sondern auf
allen ausser einer Validierungsperson, die das Early Stopping trägt (aktiv:
31 von 32, `val_person: P13`).

**Entscheidung: es wird kein separater Deployment-Checkpoint auf allen
Personen trainiert.** Diese Variante wurde erwogen — Hyperparameter aus der
CV übernehmen, Epochenzahl per Median der Fold-Best-Epochen fixieren, auf
allen 32 bzw. 23 Personen trainieren — und verworfen:

| | |
|---|---|
| Erwarteter Gewinn | +1 Person = +3,1 % (aktiv) bzw. +4,3 % (passiv) Daten. N=22 → N=32 waren +45 % Daten für ~1 pp; extrapoliert liegt das hier bei ~0,1 pp — **unter** dem Seed-σ von 0,57 pp (aktiv) und 0,35 pp (passiv). |
| Verifizierbarkeit | Ohne Holdout gibt es keine Zahl, die belegt, ob das neue Artefakt besser ist. Ein unbelegtes Modell würde gegen ein anderes unbelegtes getauscht. |
| Epochenregel | Bleibt eine Heuristik. Die Fold-Best-Epochen streuen **1 bis 19** (aktiv) bzw. 12 bis 23 (passiv); der Median ersetzt ein verrauschtes Signal durch ein weniger verrauschtes, nicht durch ein richtiges. |
| Kosten | Zwei Trainingsläufe und ein zweites Artefakt in der Verwaltung. |

Die vorhandenen Checkpoints sind methodisch verteidigbar: mit Early Stopping
gegen eine gehaltene Person trainiert. Festgehalten wird stattdessen die
eigentliche Schwäche, damit sie nicht als Versäumnis gelesen wird: **die
Stopp-Epoche hängt an der Idiosynkrasie einer einzelnen Validierungsperson**
(aktiv `val_person: P13` → Epoche 6 bei einem Fold-Median von 8; passiv
`val_person: P66` → Epoche 11 bei einem Fold-Median von 15). Das ist eine
bekannte, benannte Ungenauigkeit, keine offene Aufgabe.

Falls nach bestandener Parität Zeit übrig ist, lässt sich der Lauf lokal auf
der CPU nachziehen; dann werden **beide** Artefakte behalten, damit ein
Rückfall möglich bleibt.

**Metadaten-Fallen.** Der aktive Checkpoint entstand vor Einführung des
Kanalsatz-Feldes und hat **kein** `meta["channels"]` — das Export-Skript
defaultet bei dessen Fehlen auf `"imu"` und nimmt `n_channels` als Wahrheit.
`meta["torch_version"]` trägt ein `TorchVersion`-Objekt, das Laden erfordert
daher `weights_only=False`. Das ist zulässig, **weil ausschliesslich eigene,
im Repo erzeugte Checkpoints geladen werden**; `weights_only=False`
deserialisiert beliebigen Python-Code und darf nie auf fremde Dateien
angewandt werden.

## 3. Entschiedene Nicht-Ziele

- **Kein HMM.** Der kausale Forward-Filter hilft ausschliesslich
  gedächtnislosen 1-s-Modellen (RF-1s +2,4 pp, TCN-1s +1,0 pp) und **schadet**
  5-s-Modellen (RF-5s −0,8 pp p=0.0131, TCN-5s −0,9 pp p=0.0004,
  `reports/hmm_context_ladder.md`). Die Fenstergrösse ist der kausale Faktor,
  nicht die Modellfamilie; ein Modell mit 5 s Kontext hat den Zeit-Struktur-
  Gewinn bereits eingebaut. `hmm_live.json` und `OnlineForwardFilter` gehören
  damit nicht in dieses Deployment.
- **Kein Z-Score**, weil `zscore=False` Bestandteil der evaluierten
  Modellkonfiguration ist und diese Konfiguration empirisch generalisiert. Die
  im Modell eingefrorenen BatchNorm-Running-Statistics werden unverändert
  exportiert. (Ausdrücklich **nicht**, weil BatchNorm zur Laufzeit auf den
  aktuellen Träger kalibrierte — das tut sie im Inferenzmodus gerade nicht.)
- **Keine Feature-Extraktion.** Rohe Fenster gehen ins Netz. Die 88/92
  Features aus `src/features/windows.py` spielen hier keine Rolle — genau das
  entschärft die Paritätsfalle, an der der geparkte RF-Port hing.
- **Entscheidungsschwelle 0,5**, per Konvention gesetzt, nicht gemessen. Eine
  OOF-basierte Kalibrierung wurde erwogen und bewusst zurückgestellt. Falls
  die aufsummierte Tagesschreibzeit später systematisch verzerrt wirkt, ist
  das die erste Stellschraube (vgl. `reports/regression.md`).
- **Studien-Pipeline unangetastet.** Kein Eingriff in `server.py`,
  `src/server/`, Study Mode oder `pen_logger.py`.

## 4. Vertrag: von Vorhersagen zu Schreibzeit

Dieser Abschnitt ist normativ für alle Folge-Teilprojekte. Er existiert, weil
die naive Umsetzung die Tageszeit **um Faktor zehn aufbläht**: bei 5-s-Fenstern
mit 0,5-s-Stride addiert ein positives Fenster nicht fünf Schreibsekunden.

| Festlegung | Regel |
|---|---|
| Zeitbezug eines Fensters | Ein Fenster mit Entscheidungszeitpunkt `t` deckt `[t − 5 s, t]` ab. |
| Beitrag pro Vorhersage | **Höchstens ein Stride (0,5 s).** Jede Vorhersage besitzt nur das neue Zeitstück, nicht das ganze Fenster. |
| Beginn eines Intervalls | Erste positive Vorhersage; die 4,5 s Vorlauf des ersten Fensters werden **nicht** rückwirkend zugeschrieben. |
| Ende eines Intervalls | Erste negative Vorhersage nach positiven. |
| Tolerierte negative Lücken | **Keine Überbrückung in der Abrechnung.** Begründung unten. |
| Verworfene Sensorfenster | Tragen **weder** zu Schreibzeit **noch** zu Nicht-Schreibzeit bei. Sie werden als *unbekannte Zeit* separat gebucht und in der UI ausgewiesen. |
| Tagesgrenze | Lokale Zeit, mit Sommerzeitwechsel; ein 23- oder 25-Stunden-Tag darf die Aggregation nicht brechen. |

Die Zeile zu verworfenen Fenstern hat einen konkreten Grund: ohne separate
Buchung sieht ein Tag mit Sensorlücken aus wie ein Tag mit wenig Schreiben.

### 4.1 Warum nicht überbrückt wird

**Das Modell hat die Mikropausen bereits einkalkuliert.** Die Trainingslabels
liefen mit `max_gap_ms=2500` durch das morphologische Closing; Schreibpausen
bis 2,5 s zählen dort bereits als Schreiben. Die positive Klasse bedeutet „im
Schreibmodus", nicht „Stift berührt jetzt Papier". Eine zusätzliche
Überbrückung in der App wäre **Doppelzählung derselben Semantik** — und
genau die Art zusätzlicher Glättung, die auf einem 5-s-Modell messbar
schadet (`reports/hmm_context_ladder.md`: −0,9 pp bei p=0,0004).

**Abrechnung und Darstellung werden getrennt:**

- **Abrechnung:** jede Vorhersage besitzt ihren Stride. Keine Überbrückung,
  keine Glättung, keine nachträgliche Korrektur der Summe.
- **Darstellung:** die UI darf visuell benachbarte Intervalle zu einem Balken
  zusammenfassen, **ohne die Summe zu verändern**. Damit wird das
  Flacker-Problem dort gelöst, wo es entsteht — in der Anzeige, nicht in den
  Zahlen.

## 5. Zerlegung

| # | Teilprojekt | Abhängig von |
|---|---|---|
| **S** | Spike: `CMSensorRecorder`-Machbarkeit auf Series 7 / watchOS 26 | — |
| **1** | Konvertierung nach Core ML + Paritäts-Harness | — |
| **2** | Aktive Schreibphase auf dem iPhone | 1 |
| **3** | Passiver Tracker auf der Watch | S, 1 |
| **4** | Integration in `FocusStore`, Nachlieferung, Akku-Messung | 2, 3 |

Reihenfolge S → 1 → 2 → 3 → 4. Teilprojekt 2 steht vor 3, obwohl 3 das
eigentliche Ziel ist: der aktive Pfad braucht **keine neue Sensor-API** — die
Watch streamt heute schon, das iPhone empfängt heute schon, es fällt nur der
Server-Umweg weg. Er bringt damit den gesamten serverlosen Inferenz-Stack
zum ersten Mal real zum Laufen. Teilprojekt 3 erbt diesen Stack und tauscht
nur Sensorquelle und Ausführungsort. Umgekehrt wären Core ML und
Background-Sensorik gleichzeitig unbewiesen.

Diese Spec detailliert **S und 1**. Teilprojekte 2–4 bekommen eigene Specs,
sobald ihre Voraussetzungen gemessen sind.

## 6. Teilprojekt S — Spike: trägt `CMSensorRecorder`?

**Frage:** Liefert `CMSensorRecorder` auf der Series 7 unter watchOS 26
verwertbare Beschleunigungsdaten — dicht genug für lückenlose 5-s-Fenster,
über einen vollen Aufzeichnungsauftrag, ohne dass die App läuft?

Die API ist die einzige auf watchOS, die dauerhaft im Hintergrund aufzeichnet
(`CMBatchedSensorManager` bräuchte Series 9+). Sie ist zugleich dafür
bekannt, auf neueren watchOS-Versionen leere Ergebnisse zu liefern:
`accelerometerData(from:to:)` gibt dann `nil` zurück, ohne Fehler. Das ist
nicht dokumentiert und muss auf der Zielhardware gemessen werden.

**Aufbau.** Der Admin-Bereich liegt am **iPhone**
(`WatchStreamer/Admin/AdminPanelView.swift`); die Watch-App besteht aus drei
Swift-Dateien und hat keine eigene Admin-Oberfläche. Der Spike nutzt deshalb
den bereits existierenden Command-Pfad: iPhone-Knopf → WCSession-Command →
`MotionManager.handleCommand` auf der Watch → Antwort zurück ans iPhone. Das
ist exakt das Muster der vorhandenen `drain_spill` / `clear_spill`-Commands.

Zwei neue Commands: `sensor_probe_start` stellt einen Aufzeichnungsauftrag,
`sensor_probe_report` liest `accelerometerData(from:to:)` und gibt **rohe
Kennzahlen** zurück (Anzahl, erster und letzter Zeitstempel,
Intervall-Histogramm, grösste Lücke, Anzahl nicht-monotoner Übergänge).

**Die Bewertung dieser Kennzahlen gegen die Kriterien unten geschieht auf dem
iPhone**, in einem eigenen Typ unter `WatchStreamer/Scrybe/Logic/` — dem
Ordner, dessen Inhalt vom Test-Target `ScrybeTests` erreichbar ist (Vorbild:
`DataFlowEvaluator.swift` + `DataFlowEvaluatorTests.swift`). Damit ist die
Urteilslogik unit-testbar ohne Hardware, während auf der Watch nur
Datenerhebung ohne Entscheidungslogik liegt.

Mitgeprüft werden dabei `NSMotionUsageDescription` in der Watch-App und
`CMSensorRecorder.authorizationStatus()`.

**Zwei Durchläufe, nicht einer:**

1. **1 h** — schnelle Rückmeldung, ob die API überhaupt liefert.
2. **12 h** — der von Apple dokumentierte Maximalauftrag. Nur dieser Lauf
   zeigt Verhalten über eine volle Aufzeichnungsperiode: Ausdünnung über die
   Zeit, Verhalten bei niedrigem Akkustand, Auswirkung von App-Kill und
   Neustart.

**Erfolgskriterien, vorab festgelegt:**

| Messgrösse | Anforderung | Begründung |
|---|---|---|
| Ergebnis nicht `nil` | zwingend | der dokumentierte Ausfallmodus |
| Zeitstempel | streng monoton | Voraussetzung für jede Fensterbildung |
| Median-Intervall | ≈ 20 ms | 50 Hz nominal |
| Effektive Rate | 45–55 Hz | Modelle sind auf 50 Hz trainiert |
| Intervall-Verteilung | ≥ 99 % der Intervalle < 40 ms | fängt Ausdünnung, die ein Mittelwert verdeckt |
| Coverage | erhaltene / erwartete Samples ≥ 98 % | Gesamtvollständigkeit |
| Harte Lücken | jede Lücke > 40 ms wird protokolliert und markiert | siehe unten |
| Überlebt App-Kill | ja | „passiv" heisst genau das |
| Historie | ≥ 3 h rückwirkend abrufbar | Background Refresh feuert unregelmässig |

**Kein Zusammenrücken über Lücken.** Ein Fenster, das eine harte Lücke
enthält, wird **verworfen**, nicht aus benachbarten Samples zusammengesetzt.
Das ist keine Vorsichtsmassnahme, sondern die Lehre aus einem dokumentierten
Fehler dieses Projekts: `build_windows` iteriert **index-** statt zeitbasiert,
weshalb im S093-Vorfall eine 209-Sekunden-Lücke für den Loop unsichtbar war
und die Abtastraten-Schätzung um 11,6 % verzog — was jedes Feature dieser
Session verfälschte. Die On-Device-Fensterbildung muss zeitbasiert prüfen.

**Ausgang.** Alle Kriterien bestanden → Teilprojekt 3 ist baubar. Andernfalls
liegt eine belegte Aussage vor statt einer Vermutung, und die aktive
Schreibphase wird zum Hauptprodukt statt zum Zwischenschritt.

## 7. Teilprojekt 1 — Konvertierung und Parität

Leitgedanke: **keine Zeile Swift darf dem Modell vertrauen, ohne dass ein
Test es beweist.** Dieses Projekt hat zwei teure Bugs derselben Klasse erlebt
(`reports/sort_stability_bug.md`, Capture-Clock-Fix) — beides stille
Train/Deploy-Abweichungen, die keine Metrik anzeigte, weil sie in beiden
Pfaden gleich falsch aussahen.

### 7.1 Umgebung

`coremltools 9.0` hat ein natives Rad für Python 3.13 auf arm64
(`cp313-none-macosx_11_0_arm64`). Es wird trotzdem in ein **separates venv**
installiert, nicht in die Projektumgebung: `coremltools` pinnt numpy und
torch enger als dieses Projekt, und der Präzedenzfall existiert — die
`aeon`-Installation hat numpy auf 2.3.5 heruntergestuft. Ein
Konvertierungswerkzeug darf die Trainings- und Auswertungsumgebung nicht
verändern.

### 7.2 Export

`scripts/pipeline/export_coreml.py` — unter `pipeline/`, weil es Artefakte
schreibt, die ein laufendes Gerät lädt (Konvention aus `scripts/README.md`).

```
models/coreml/ScrybeActive.mlpackage    ← tcn_bigru, Input (1, 250, 6)
models/coreml/ScrybePassive.mlpackage   ← tcn6,      Input (1, 250, 3)
```

**Verbindliche Exportvorgaben** — jede einzelne ist eine geschlossene
Paritätslücke:

| Vorgabe | Wert | Warum |
|---|---|---|
| Modellzustand | `model.eval()` vor Referenzberechnung **und** vor Tracing | sonst bleiben Dropout und BatchNorm-Batch-Statistiken aktiv — eine stille Paritätsfalle |
| State Dict | strikt laden (`strict=True`) | fängt Architektur-Drift gegen die Registry |
| Input-Dtype | float32, fest | keine implizite Promotion |
| Konvertierungsziel | `convert_to="mlprogram"` | ML Program, nicht das alte NeuralNetwork-Format |
| Deployment Target | explizit gesetzt | sonst wählt coremltools nach Host-OS |
| Compute Precision | **FP32, festgenagelt** | Begründung §7.3; gilt für Parität *und* Produktion |
| Input-/Outputnamen | explizit vergeben, dokumentiert | sie sind der App-Vertrag, keine generierten Namen |
| Begleitartefakt | Modellversion + SHA-256 des `.mlpackage` | macht nachweisbar, welches Gewicht auf dem Gerät lief |

**Input-Layout:** Shape `(batch, seq_len, n_channels)`, wie `build_raw_windows`
es liefert. Kanalreihenfolge aktiv `[ax, ay, az, rx, ry, rz]`; passiv
`[x, y, z]` als **drei aufsummierte** Kanäle. Diese Reihenfolge ist Teil des
Kontrakts und wird in den Golden-Vektoren mitgeprüft.

### 7.3 Golden-Vektoren und die drei Paritätsebenen

Aus echten gemergten Sessions werden ~50 Fenster je Modell gezogen — gemischt
schreibend und idle, einschliesslich Fenstern nahe der 60-%-Label-Schwelle und
**gezielt solcher, deren Wahrscheinlichkeit dicht an 0,5 liegt** — und
zusammen mit dem PyTorch-Logit als JSON abgelegt:

```
tests/fixtures/golden_windows_active.json
tests/fixtures/golden_windows_passive.json
```

Dieselbe Datei wird auf **drei Ebenen** konsumiert. Zwei davon reichen nicht:

| Ebene | Ort | Beweist |
|---|---|---|
| **P1** | Python: PyTorch ↔ Core ML | die Konvertierung ist verlustfrei |
| **P2** | iPhone-**Simulator**: `ScrybeActive` | `coremlc`-Kompilierung, Bundle-Resource-Auflösung, `MLMultiArray`-Packing und Fixture-Dekodierung unter iOS — **nicht** Ausführung auf der Zielhardware: der Simulator rechnet auf der Mac-CPU mit der Mac-Core-ML-Laufzeit, exakt das Argument, mit dem diese Spec P3 begründet |
| **P3** | **physische Series 7**: `ScrybePassive` | das passive Modell lädt und rechnet auf **der** Hardware, auf der es laufen soll |

Den `ScrybeTests`-Lauf einmal auf einem physischen iPhone statt im Simulator
auszuführen, ist neben der Watch-Session nahezu kostenlos und schließt die
P2-Lücke — dieser einmalige Lauf steht noch aus.

P3 ist nicht optional und nicht durch den Simulator ersetzbar: Rechenwerk,
Speicher und Core-ML-Backend der Watch unterscheiden sich vom Mac. Das
bestehende Target `ScrybeTests` ist ein Unit-Test-Bundle des **iPhone**-Projekts
(verifiziert: die einzigen Targets sind `WatchStreamer`,
`WatchStreamer Watch App`, `ScrybeTests`) und deckt P3 nicht ab.

**P3 wird über denselben Command-Pfad wie der Spike ausgeführt** — ein
`parity_check`-Command an die Watch, Ergebnis zurück ins iPhone-Admin-Panel —
und nicht als neues watchOS-Test-Target. Der Spike (§6) baut diese
Maschinerie ohnehin; die Paritätsprüfung ist derselbe Ablauf mit anderen
Eingaben. Ein eigenes Test-Target verlangt Scheme, Test-Host und
Provisioning, läuft über das gekoppelte iPhone langsam und störanfällig, und
seine Automatisierung zahlt sich nur aus, wenn sie regelmässig liefe — sie
braucht aber jedes Mal die angelegte Uhr. Was sich realistisch ändert, ist
die Konvertierung, und die deckt P1 als echter automatisierter Test ab.

**Projektstruktur-Hinweis:** Das Xcode-Projekt nutzt
`PBXFileSystemSynchronizedRootGroup` — die Target-Zugehörigkeit ergibt sich
aus dem Ordner (`WatchStreamer/` → iPhone, `WatchStreamer Watch App/` →
Watch, `ScrybeTests/` → Test-Bundle). Neue Dateien und die `.mlpackage`
werden per Ablage im richtigen Ordner eingebunden; **keine
pbxproj-Bearbeitung nötig**.

**Compute-Konfiguration und Toleranz.** Beide Modelle laufen — in Parität
**und** Produktion — mit **festgenagelter FP32-Compute-Konfiguration** gegen
eine Logit-Toleranz von 1e-4. Damit gilt ein einziges Kriterium auf allen
drei Ebenen.

Begründet ist das durch die Modellgrösse: 9.249 bzw. 19.089 Parameter bei
zwei Inferenzen pro Sekunde sind gegen die Sensorik vernachlässigbar — der
Akku geht fürs Aufzeichnen drauf, nicht fürs Netz. Die Alternative (Neural
Engine, FP16) kostet Determinismus, macht die 1e-4-Toleranz ungültig und
verlangt Ersatzkriterien auf Wahrscheinlichkeits- und Klassifikationsebene;
zudem fällt Core ML bei nicht unterstützten Operationen **still** auf CPU
zurück, und dilatierte Conv1d wie GRU sind genau die Kandidaten dafür. Der
Preis dieser Wahl ist mit hoher Wahrscheinlichkeit nicht messbar.
Revidierbar, falls das Geräteprofiling aus §8 die Inferenz wider Erwarten als
echten Akkuposten ausweist — dann greifen die drei Ersatzkriterien
(Wahrscheinlichkeitsabweichung, identische Klassifikation bei 0,5,
schwellennahe Fälle gesondert).

Erst wenn die Ebene, die eine App-Funktion trägt, grün ist, darf App-Code das
zugehörige Modell benutzen.

### 7.4 Risiko: bidirektionales GRU

`tcn_bigru` enthält ein `nn.GRU(bidirectional=True)`; die Repräsentation ist
`cat(h_n[0], h_n[1])`. Core ML unterstützt bidirektionale GRUs im MIL-Dialekt
grundsätzlich, ein direkter Export ist also plausibel. Falls er scheitert,
gilt diese Reihenfolge:

1. **Direkter Export** über TorchScript beziehungsweise ExportedProgram.
2. **Gezieltes Graph-Rewrite** — den GRU vor der Konvertierung entrollen.
3. **Alternatives, bereits evaluiertes Modell**, das konvertierbar ist —
   `tcn6` legacy (0.9154, reines Conv1d) liegt aus demselben Lauf vor und
   kostet 0,55 pp.
4. **Eigener GRU-Kern in Swift** — praktisch **nicht** für diesen Termin.
   Eine GRU hat drei Gates; eine PyTorch-genaue Rekonstruktion umfasst
   mehrere Eingangs- und Hidden-Matrixoperationen, Bias-Konventionen und
   Gate-Reihenfolgen. Das wäre eine neue grosse Paritätsoberfläche und
   widerspricht dem Leitgedanken dieser Spec.

Stufe 3 ist die realistische Rückfallebene, nicht Stufe 4.

## 8. Konsequenzen für die App (Vorgriff, nicht Teil dieser Spec)

- **Die Watch muss auf 50 Hz.** Aktuell streamt sie 100 Hz; beide Modelle
  sind auf 50 Hz trainiert. `MotionManager.Config.requestedHz` kann das
  bereits, der Wert wird über den Command-Pfad gesetzt.
- **Fenster-Takt aktiv:** Stride 25 Samples (0,5 s) über einem
  250-Sample-Ringpuffer, also zwei Inferenzen pro Sekunde. Jede Entscheidung
  bezieht sich auf die letzten 5 s und trägt nach §4 höchstens 0,5 s bei.
- **Rechenlast passiv:** die Modelle sind klein (9.249 Parameter). Ob die
  Gesamtlast tragbar ist, entscheidet sich aber erst nach Geräteprofiling —
  Abruf, zeitbasiertes Windowing, Core ML und Persistenz müssen **gemeinsam**
  gemessen werden, nicht das Modell allein. Bis dahin steht hier keine
  Aussage.

## 9. Getroffene Entscheidungen

Vier Punkte standen nach der ersten Review offen. Alle vier sind entschieden,
und alle vier reduzieren Arbeit.

| # | Frage | Entscheidung | Abschnitt |
|---|---|---|---|
| A | Deployment-Checkpoint auf allen Personen nachtrainieren? | **Nein.** Gewinn ~0,1 pp liegt unter dem Seed-Rauschen und wäre nicht verifizierbar; die Epochenregel bliebe eine Heuristik. Die Schwäche wird stattdessen benannt. | §2.1 |
| B | P3 als watchOS-Test-Target oder Admin-Diagnose? | **Admin-Diagnose.** Der Spike baut die Maschinerie ohnehin; die Paritätsprüfung ist ein einmaliges Freigabe-Gate, keine Regressionssuite. | §7.3 |
| C | FP32 oder Neural Engine/FP16 in der Produktion? | **FP32 festgenagelt**, in Parität und Produktion. Ein Kriterium für alle drei Ebenen; der Akku liegt in der Sensorik, nicht im Netz. | §7.3 |
| D | Überbrückungsschwelle für negative Lücken? | **Keine Überbrückung.** Das Label-Closing (`max_gap_ms=2500`) hat die Mikropausen bereits absorbiert; Abrechnung und Darstellung werden getrennt. | §4.1 |

## 10. Verhältnis zur geparkten Passiv-Spec

`docs/specs/2026-06-24-passive-tracker-mode-design.md` ist durch diese Spec
**abgelöst**. Ihre vier tragenden Entscheidungen gelten nicht mehr, weil sie
für ein Random-Forest-Deployment getroffen wurden:

| geparkte Spec (RF) | jetzt (Deep) |
|---|---|
| 30 invariante Features in Swift nachbauen | keine Features, rohe Fenster |
| RF als JSON-Baum exportieren, kein Core ML | Core ML für beide Modelle |
| Inferenz auf dem iPhone | passiv auf der Watch, aktiv auf dem iPhone |
| HMM `OnlineForwardFilter` als Glättung | kein HMM (5-s-Fenster) |

Gültig bleibt aus ihr das Modus-Interlock-Prinzip: Collection- und
Tracker-Modus laufen nie gleichzeitig, und ein Studiengerät darf nicht
versehentlich in den Tracker-Modus rutschen. Das wird in Teilprojekt 4
wieder aufgegriffen.
