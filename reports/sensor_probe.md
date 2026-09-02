# Sensor-Probe & On-Device-Parität — Messprotokoll

Status: **AUSSTEHEND.** Alle drei Messungen unten sind manuelle
Hardware-Schritte (physische Apple Watch Series 7, gekoppeltes iPhone) und
wurden bislang **nicht** durchgeführt. Der Code-Pfad dafür ist gebaut und
unit-getestet (`SensorProbeEvaluatorTests`, `ScrybeModelParityTests`), aber
kein Agent kann diese Messung selbst ausführen — sie braucht die angelegte
Uhr (12 h für den zweiten Lauf) und das gekoppelte Gerät.

Dieses Dokument hält die vorab vereinbarten Akzeptanzkriterien fest
(Spec `docs/specs/2026-08-28-on-device-deployment-design.md` §6) und lässt
die Ergebnisfelder leer für den Operator, der die Messung tatsächlich
durchführt. Bis dahin gilt: **P3 ist nicht bewiesen**, unabhängig davon,
was ein Commit-Titel oder eine Ledger-Zeile andernorts suggeriert (siehe
Review-Befund I1, `.superpowers/sdd/2026-08-28-on-device-deployment-phase1/progress.md`).

## Ablauf

1. `SensorProbeCard` im iPhone-Admin-Panel (Profil → fünf Taps auf die
   Versionszeile "Scrybe x.y" → PIN, Default `0000`; der Dreifach-Tap auf das
   Logo öffnet das Admin-Panel des Web-Dashboards, nicht dieses hier)
   → "1 h" bzw. "12 h" startet `sensor_probe_start`.
   NSMotionUsageDescription + `CMSensorRecorder.authorizationStatus()` vorher
   prüfen.
2. Nach Ablauf der Dauer (plus 5 min Headroom, Spec §1.1) → "Auswerten"
   ruft `sensor_probe_report` ab und zeigt das Urteil aus
   `SensorProbeEvaluator`.
3. `ModelParityCard` → "Modell-Parität auf der Watch prüfen" stößt
   `parity_check` an (P3, Golden-Vektoren gegen `ScrybePassive.mlmodelc`).

Gerätemodell, watchOS-Version und Datum in jeder Sektion eintragen.

## 1-Stunden-Lauf

Zweck: schnelle Rückmeldung, ob die API überhaupt liefert, bevor die
12-h-Messung investiert wird.

| Messgröße | Anforderung | Begründung | Ergebnis |
|---|---|---|---|
| Ergebnis nicht `nil` | zwingend | dokumentierter Ausfallmodus | _(ausstehend)_ |
| Zeitstempel | streng monoton | Voraussetzung für jede Fensterbildung | _(ausstehend)_ |
| Median-Intervall | ~= 20 ms | 50 Hz nominal | _(ausstehend)_ |
| Effektive Rate | 45-55 Hz | Modelle sind auf 50 Hz trainiert | _(ausstehend)_ |
| Intervall-Verteilung | >= 99 % der Intervalle < 40 ms | fängt Ausdünnung, die ein Mittelwert verdeckt | _(ausstehend)_ |
| Coverage | erhaltene / erwartete Samples >= 98 % | Gesamtvollständigkeit | _(ausstehend)_ |
| Harte Lücken | jede Lücke > 40 ms protokolliert und markiert | siehe Spec §6 | _(ausstehend)_ |
| Überlebt App-Kill | ja | "passiv" heißt genau das | _(ausstehend)_ |
| Historie | >= 3 h rückwirkend abrufbar | Background Refresh feuert unregelmäßig | _(ausstehend)_ |

Gerät: _______________  watchOS-Version: _______________  Datum: _______________

Verdikt (`SensorProbeEvaluator.evaluate`): _______________

Rohantwort (`sensorProbeRaw`): _______________

## 12-Stunden-Lauf

Zweck: der von Apple dokumentierte Maximalauftrag. Einziger Lauf, der
Verhalten über eine volle Aufzeichnungsperiode zeigt — Ausdünnung über
die Zeit, Verhalten bei niedrigem Akkustand, Auswirkung von App-Kill und
Neustart.

| Messgröße | Anforderung | Begründung | Ergebnis |
|---|---|---|---|
| Ergebnis nicht `nil` | zwingend | dokumentierter Ausfallmodus | _(ausstehend)_ |
| Zeitstempel | streng monoton | Voraussetzung für jede Fensterbildung | _(ausstehend)_ |
| Median-Intervall | ~= 20 ms | 50 Hz nominal | _(ausstehend)_ |
| Effektive Rate | 45-55 Hz | Modelle sind auf 50 Hz trainiert | _(ausstehend)_ |
| Intervall-Verteilung | >= 99 % der Intervalle < 40 ms | fängt Ausdünnung, die ein Mittelwert verdeckt | _(ausstehend)_ |
| Coverage | erhaltene / erwartete Samples >= 98 % | Gesamtvollständigkeit | _(ausstehend)_ |
| Harte Lücken | jede Lücke > 40 ms protokolliert und markiert | siehe Spec §6 | _(ausstehend)_ |
| Überlebt App-Kill | ja | "passiv" heißt genau das | _(ausstehend)_ |
| Historie | >= 3 h rückwirkend abrufbar | Background Refresh feuert unregelmäßig | _(ausstehend)_ |

Zusätzlich für diesen Lauf zu protokollieren (Spec §6, App-Kill-Test):
- App während der Aufzeichnung explizit beendet (Force-Quit) und neu
  gestartet: _______________
- Akkustand bei Start / Ende: _______________ / _______________
- `readDurationSeconds` aus der `sensor_probe_report`-Antwort (Diagnose,
  ob der Read selbst lange genug dauert, um den sendMessage-Timeout zu
  riskieren): _______________

Gerät: _______________  watchOS-Version: _______________  Datum: _______________

Verdikt (`SensorProbeEvaluator.evaluate`): _______________

Rohantwort (`sensorProbeRaw`): _______________

**Ausgang (Spec §6):** bestehen beide Läufe alle Kriterien, ist Teilprojekt
3 baubar. Andernfalls liegt eine belegte Aussage vor statt einer Vermutung,
und die aktive Schreibphase (Teilprojekt 2) wird zum Hauptprodukt statt zum
Zwischenschritt.

## P3 — On-Device-Modell-Parität (`parity_check`)

Zweck: beweisen, dass `ScrybePassive.mlmodelc` auf der physischen Series 7
dieselben Logits liefert wie PyTorch — nicht durch den Simulator ersetzbar,
weil Rechenwerk, Speicher und Core-ML-Backend der Watch sich vom Mac
unterscheiden (Spec §7.3).

Akzeptanzkriterium (Spec §7.3 / Plan Task 11 Schritt 4): **alle** Fenster
bestanden, `maxAbsDiff` <= 1e-4, `classMismatches` = 0.

| Messgröße | Anforderung | Ergebnis |
|---|---|---|
| `total` | 24 (Fixture-Größe) | _(ausstehend)_ |
| `passed` | = `total` | _(ausstehend)_ |
| `maxAbsDiff` | <= 1e-4 | _(ausstehend)_ |
| `classMismatches` | 0 | _(ausstehend)_ |
| `failedIds` | leer | _(ausstehend)_ |

Gerät: _______________  watchOS-Version: _______________  Datum: _______________

Rohantwort (`parityRaw`): _______________

**Bis diese Tabelle ausgefüllt ist, gilt: P1 (Mac) und P2 (iPhone-Simulator)
sind gemessen, P3 (physische Watch) ist es nicht.** Siehe Spec §7.3 für die
Einschränkung, was P2 tatsächlich beweist (Simulator rechnet auf der
Mac-CPU, nicht auf Zielhardware).
