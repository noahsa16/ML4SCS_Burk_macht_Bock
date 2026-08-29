# Sensor-Probe & On-Device-Paritaet — Messprotokoll

Status: **AUSSTEHEND.** Alle drei Messungen unten sind manuelle
Hardware-Schritte (physische Apple Watch Series 7, gekoppeltes iPhone) und
wurden bislang **nicht** durchgefuehrt. Der Code-Pfad dafuer ist gebaut und
unit-getestet (`SensorProbeEvaluatorTests`, `ScrybeModelParityTests`), aber
kein Agent kann diese Messung selbst ausfuehren — sie braucht die angelegte
Uhr (12 h fuer den zweiten Lauf) und das gekoppelte Geraet.

Dieses Dokument haelt die vorab vereinbarten Akzeptanzkriterien fest
(Spec `docs/specs/2026-08-28-on-device-deployment-design.md` §6) und laesst
die Ergebnisfelder leer fuer den Operator, der die Messung tatsaechlich
durchfuehrt. Bis dahin gilt: **P3 ist nicht bewiesen**, unabhaengig davon,
was ein Commit-Titel oder eine Ledger-Zeile andernorts suggeriert (siehe
Review-Befund I1, `.superpowers/sdd/2026-08-28-on-device-deployment-phase1/progress.md`).

## Ablauf

1. `SensorProbeCard` im iPhone-Admin-Panel (Profil → fuenf Taps auf die
   Versionszeile "Scrybe x.y" → PIN, Default `0000`; der Dreifach-Tap auf das
   Logo oeffnet das Admin-Panel des Web-Dashboards, nicht dieses hier)
   → "1 h" bzw. "12 h" startet `sensor_probe_start`.
   NSMotionUsageDescription + `CMSensorRecorder.authorizationStatus()` vorher
   pruefen.
2. Nach Ablauf der Dauer (plus 5 min Headroom, Spec §1.1) → "Auswerten"
   ruft `sensor_probe_report` ab und zeigt das Urteil aus
   `SensorProbeEvaluator`.
3. `ModelParityCard` → "Modell-Paritaet auf der Watch pruefen" stoesst
   `parity_check` an (P3, Golden-Vektoren gegen `ScrybePassive.mlmodelc`).

Geraetemodell, watchOS-Version und Datum in jeder Sektion eintragen.

## 1-Stunden-Lauf

Zweck: schnelle Rueckmeldung, ob die API ueberhaupt liefert, bevor die
12-h-Messung investiert wird.

| Messgroesse | Anforderung | Begruendung | Ergebnis |
|---|---|---|---|
| Ergebnis nicht `nil` | zwingend | dokumentierter Ausfallmodus | _(ausstehend)_ |
| Zeitstempel | streng monoton | Voraussetzung fuer jede Fensterbildung | _(ausstehend)_ |
| Median-Intervall | ~= 20 ms | 50 Hz nominal | _(ausstehend)_ |
| Effektive Rate | 45-55 Hz | Modelle sind auf 50 Hz trainiert | _(ausstehend)_ |
| Intervall-Verteilung | >= 99 % der Intervalle < 40 ms | faengt Ausduennung, die ein Mittelwert verdeckt | _(ausstehend)_ |
| Coverage | erhaltene / erwartete Samples >= 98 % | Gesamtvollstaendigkeit | _(ausstehend)_ |
| Harte Luecken | jede Luecke > 40 ms protokolliert und markiert | siehe Spec §6 | _(ausstehend)_ |
| Ueberlebt App-Kill | ja | "passiv" heisst genau das | _(ausstehend)_ |
| Historie | >= 3 h rueckwirkend abrufbar | Background Refresh feuert unregelmaessig | _(ausstehend)_ |

Geraet: _______________  watchOS-Version: _______________  Datum: _______________

Verdikt (`SensorProbeEvaluator.evaluate`): _______________

Rohantwort (`sensorProbeRaw`): _______________

## 12-Stunden-Lauf

Zweck: der von Apple dokumentierte Maximalauftrag. Einziger Lauf, der
Verhalten ueber eine volle Aufzeichnungsperiode zeigt — Ausduennung ueber
die Zeit, Verhalten bei niedrigem Akkustand, Auswirkung von App-Kill und
Neustart.

| Messgroesse | Anforderung | Begruendung | Ergebnis |
|---|---|---|---|
| Ergebnis nicht `nil` | zwingend | dokumentierter Ausfallmodus | _(ausstehend)_ |
| Zeitstempel | streng monoton | Voraussetzung fuer jede Fensterbildung | _(ausstehend)_ |
| Median-Intervall | ~= 20 ms | 50 Hz nominal | _(ausstehend)_ |
| Effektive Rate | 45-55 Hz | Modelle sind auf 50 Hz trainiert | _(ausstehend)_ |
| Intervall-Verteilung | >= 99 % der Intervalle < 40 ms | faengt Ausduennung, die ein Mittelwert verdeckt | _(ausstehend)_ |
| Coverage | erhaltene / erwartete Samples >= 98 % | Gesamtvollstaendigkeit | _(ausstehend)_ |
| Harte Luecken | jede Luecke > 40 ms protokolliert und markiert | siehe Spec §6 | _(ausstehend)_ |
| Ueberlebt App-Kill | ja | "passiv" heisst genau das | _(ausstehend)_ |
| Historie | >= 3 h rueckwirkend abrufbar | Background Refresh feuert unregelmaessig | _(ausstehend)_ |

Zusaetzlich fuer diesen Lauf zu protokollieren (Spec §6, App-Kill-Test):
- App waehrend der Aufzeichnung explizit beendet (Force-Quit) und neu
  gestartet: _______________
- Akkustand bei Start / Ende: _______________ / _______________
- `readDurationSeconds` aus der `sensor_probe_report`-Antwort (Diagnose,
  ob der Read selbst lange genug dauert, um den sendMessage-Timeout zu
  riskieren): _______________

Geraet: _______________  watchOS-Version: _______________  Datum: _______________

Verdikt (`SensorProbeEvaluator.evaluate`): _______________

Rohantwort (`sensorProbeRaw`): _______________

**Ausgang (Spec §6):** bestehen beide Laeufe alle Kriterien, ist Teilprojekt
3 baubar. Andernfalls liegt eine belegte Aussage vor statt einer Vermutung,
und die aktive Schreibphase (Teilprojekt 2) wird zum Hauptprodukt statt zum
Zwischenschritt.

## P3 — On-Device-Modell-Paritaet (`parity_check`)

Zweck: beweisen, dass `ScrybePassive.mlmodelc` auf der physischen Series 7
dieselben Logits liefert wie PyTorch — nicht durch den Simulator ersetzbar,
weil Rechenwerk, Speicher und Core-ML-Backend der Watch sich vom Mac
unterscheiden (Spec §7.3).

Akzeptanzkriterium (Spec §7.3 / Plan Task 11 Schritt 4): **alle** Fenster
bestanden, `maxAbsDiff` <= 1e-4, `classMismatches` = 0.

| Messgroesse | Anforderung | Ergebnis |
|---|---|---|
| `total` | 24 (Fixture-Groesse) | _(ausstehend)_ |
| `passed` | = `total` | _(ausstehend)_ |
| `maxAbsDiff` | <= 1e-4 | _(ausstehend)_ |
| `classMismatches` | 0 | _(ausstehend)_ |
| `failedIds` | leer | _(ausstehend)_ |

Geraet: _______________  watchOS-Version: _______________  Datum: _______________

Rohantwort (`parityRaw`): _______________

**Bis diese Tabelle ausgefuellt ist, gilt: P1 (Mac) und P2 (iPhone-Simulator)
sind gemessen, P3 (physische Watch) ist es nicht.** Siehe Spec §7.3 fuer die
Einschraenkung, was P2 tatsaechlich beweist (Simulator rechnet auf der
Mac-CPU, nicht auf Zielhardware).
