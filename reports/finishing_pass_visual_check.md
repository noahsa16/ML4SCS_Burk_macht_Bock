# Fertigstellungs-Pass — Sichtprüfung

Status: **AUSSTEHEND.** Die Spec macht „grafisch richtig gut" zu einer eigenen
Abnahmebedingung (`docs/specs/2026-08-31-scrybe-launch-fokus-tab-design.md`
§10, Visual-Quality-Gate). Ein Urteil darüber lässt sich nicht aus dem Code
ableiten — es braucht Screenshots auf echter Hardware und VoiceOver.

Was maschinell belegt ist: 405 Tests grün, `ScrybeGlyphTests` prüft, dass jede
der fünf Glyphen bei 24 pt etwas zeichnet und ihre Box nicht verlässt. Das ist
der Beweis, dass die Symbole **existieren**, nicht dass sie **gut aussehen**.

## Was in diesem Pass geändert wurde

| Task | Änderung | Commit |
|---|---|---|
| 1 | Vier gezeichnete Tab-Glyphen statt SF Symbols; Textlabels bleiben | `cddfede` |
| 2 | Tab-Bar in Papierfarben über `UITabBarAppearance` | `ff2e05a` |
| 3 | Zwei Serifen-Schalter statt `Picker(.segmented)` in Trends | `4bdf388` |
| 4 | Streak-Marke statt `flame.fill` | `4bdf388` |
| 5 | Splash in der Serife der App statt `AvenirNext-Heavy` | `7997a93` |
| 6 | Empty-State als leere linierte Seite statt `list.bullet.rectangle` | `93b9667` |

## Schritt 1 — Referenz-Screenshots

Je Zustand einer auf iPhone 15 Pro, einer auf einem kleinen iPhone, einer bei
größter Dynamic-Type-Stufe.

| Zustand | 15 Pro | klein | XXXL | Anmerkung |
|---|---|---|---|---|
| Heute | ☐ | ☐ | ☐ | |
| Trends | ☐ | ☐ | ☐ | |
| Fokus — bereit | ☐ | ☐ | ☐ | Kreatur bei 140 pt lesbar? |
| Fokus — läuft | ☐ | ☐ | ☐ | Header und Tab-Bar verschwunden? |
| Fokus — fertig | ☐ | ☐ | ☐ | Seite, Signatur, Zeit, ggf. Banner |
| Profil | ☐ | ☐ | ☐ | |

## Schritt 2 — Kriterien aus Spec §10

Abweichungen werden notiert, nicht stillschweigend akzeptiert.

| Kriterium | Befund |
|---|---|
| Komposition | _(ausstehend)_ |
| Rhythmus | _(ausstehend)_ |
| Typografie | _(ausstehend)_ |
| Farbe | _(ausstehend)_ |
| Tiefe | _(ausstehend)_ |
| Animation | _(ausstehend)_ |
| Bedienzustände | _(ausstehend)_ |
| Gerätebreite | _(ausstehend)_ |

Besonders zu prüfen: Ringgröße, Zentrierung, Textumbruch, Buttonhöhe, Safe
Area, Tab-Bar.

## Schritt 3 — Abbruchkriterium

Das Gate ist **kein Abwägungsfall**: Regressiert die Zugänglichkeit gegenüber
dem Stock-Verhalten, wird der betreffende Task zurückgenommen, auch wenn die
Optik fertig ist.

| Prüfung | Erwartet | Ergebnis |
|---|---|---|
| VoiceOver über die Tab-Bar | jeder Tab mit Namen **und** Auswahlzustand angesagt | _(ausstehend)_ |
| Tab-Bar über dem Home-Indikator | sitzt korrekt, keine Überlappung | _(ausstehend)_ |
| VoiceOver über den Trends-Umschalter | beide Optionen als Button, die aktive als ausgewählt | _(ausstehend)_ |
| Splash bei größter Dynamic-Type-Stufe | „scrybe" bleibt auf einer Zeile | _(ausstehend)_ |

Fällt eine dieser Zeilen durch, ist der zugehörige Task zurückzunehmen:
Zeile 1–2 → Task 1 und 2, Zeile 3 → Task 3, Zeile 4 → Task 5.
