# Focus-Tracker Startup — Strategie-Design

**Datum:** 2026-05-28
**Status:** Strategie-Brainstorm abgeschlossen, bereit für Pre-Launch-Checklist
**Kontext:** Geschäftsmodell-Skizze auf Basis des ML4SCS-Semesterprojekts,
ausgehend vom Focus-Tracker-Pivot (Live-Inference + Personal-Modell `rf_noah`
als Deployment-Story neben dem Generic-LOSO-Headline).

## Ziel

Eine konkrete, testbare 12-Wochen-Skizze für einen Solo-Spin-off des
Projekts in ein Indie-/Startup-Produkt: **"Activity Rings für deinen
Schreib-Schreibtisch"** — eine Apple-Watch-App, die Offline-Schreibzeit
misst, daily Streak free, AI-Wochen-Review premium.

Das Dokument ist Strategie-Skizze, kein Implementierungs-Plan. Es soll
festhalten: welche strategischen Entscheidungen im Brainstorming gefallen
sind, was daraus konkret als V1 zu bauen ist, welche Annahmen der erste
Markt-Test prüft, und welche Punkte vor dem öffentlichen Build-in-Public-
Start zwingend geklärt sein müssen.

## Nicht-Ziele

- Kein Implementierungs-Plan. Code-Level-Details kommen in einem separaten
  Plan-Dokument nach Spec-Freigabe.
- Keine Markt-Validierungs-Ersatzhandlung. Der 60-Tage-Demand-Test ist die
  Validierung — dieses Dokument ist nur die Skizze drumherum.
- Keine Bindung des ML4SCS-Bericht-Scope. Der Semester-Bericht bleibt
  unverändert; das Startup ist Post-Semester-Aktivität.
- Kein Co-Founder-Agreement. Equity-Splits, Vesting, IP-Übertragung sind
  Anwaltsfragen, kein Spec-Inhalt.

## One-Line-Pitch

> "Activity Rings für deinen Schreib-Schreibtisch." Apple-Watch-App, die
> deinen Offline-Schreib-Tag misst — das, was RescueTime, Toggl und alle
> Calendar-Tools systematisch verpassen. Daily Streak free, AI-Wochen-
> Review premium.

## Strategische Entscheidungen

Sechs Weichenstellungen aus dem Brainstorming, jeweils mit der Alternative,
die explizit verworfen wurde:

| # | Entscheidung | Verworfen weil |
|---|---|---|
| 1 | **Ambition: Startup/Gründung** (vs. Side Project / B2B-Lizenz) | Side Project nutzt den Wedge nicht voll aus; B2B-Lizenz hätte längere Sales-Zyklen ohne Distribution. |
| 2 | **Zielgruppe: Focus-Nerds als Wedge, ADHD als Vision** (vs. EdTech / Pen-Replacement) | EdTech-DE zu zäh und langsam; Pen-Replacement zu schmaler Markt. ADHD-First scheitert an Regulatorik vor Distribution. |
| 3 | **Promise: Streak + AI-Coach (Strava-Pattern)** (vs. Quantified-Self / Pen-Identity) | Streak löst Retention, AI-Coach rechtfertigt Pricing. Strava/Whoop/Oura belegen das Muster. |
| 4 | **Onboarding: Aktive 90-Sek-Kalibrierung** (vs. Generic-from-day-one / 7-Tage-Trainingsphase / Hybrid) | Der entscheidende erste Eindruck in den ersten 60 Sek ist der wichtigste Conversion-Hebel. Engineering-Risiko niedrig (Study-Mode-Code wiederverwendbar). |
| 5 | **MVP-Wette: Demand-First** (vs. Pricing / Retention / Tech-Robustheit) | Solo-Founder ohne Audience: teuerster Fehler ist 6 Monate ein Produkt zu bauen, das niemand will. Demand-First kostet 6 Wochen, nicht 6 Monate, falls falsch. |
| 6 | **Distribution: Build-in-Public + Newsletter, HN als Crescendo** (vs. nur HN / nur Communities / Campus) | BIP baut Audience *vor* Launch auf; HN-Schuss ohne warme Liste konvertiert schlecht. Semester-Story (Sort-Stability-Bug, 90-Sek-Demo) ist BIP-tauglicher Content. |
| 7 | **Team: Solo Noah, Ben + Taji als Credit-Mention** (vs. Trio Co-Founder / 2er-Team / Solo-then-recruit) | Volle Kontrolle, klare Entscheidungswege, BIP funktioniert besser mit einer Stimme. Ben/Taji nicht automatisch Co-Founder, nur weil sie am Semester-Projekt waren. |

## Produkt-Architektur (V1, ~12 Wochen)

| Komponente | Was | Quelle aus Semester-Projekt |
|---|---|---|
| **Watch-Complication** | Live-Counter "47 / 90 min", farbiger Ring | Live-Inference-Pill aus dem Dashboard |
| **Watch-App (Minimal)** | 90-Sek-Kalibrierung, Streak-View, Force-Touch für manuelle Session | Study-Mode-Pre-Task-Countdown als Vorlage |
| **iPhone-App, Today-Tab** | 24-h-Timeline, Total-Minuten, Streak, Wochen-Heatmap | `static/views/focus.html` — fast 1:1 portierbar |
| **iPhone-App, Onboarding** | 90-Sek-Kalibrierung + Modell-Switch Generic→Personal | Study-Mode-State-Machine + `POST /inference/model` |
| **Backend** | **On-device only** als Default. Optional minimaler Tier (Fly.io/Render, ~50 €/mo) nur für Newsletter-Wartelist + Wochen-Review-API | `src/server/inference.py` |
| **AI-Wochen-Review (v1.5)** | OpenAI-Call Sonntag 18 Uhr mit 7-Tage-Aggregaten, Push-Notif | Neu, nicht aus Semester |

### Out-of-Scope für V1

- AirPods-Daten (logged, aber nicht genutzt)
- Cross-Device-Sync mit Mac
- Web-Dashboard
- Team-Features
- Integrations (Notion / Obsidian / Toggl-Export)
- Modern-Pool-Modell live (siehe Open Items)

## 12-Wochen-Roadmap

```
Woche  1–2:   Pre-Launch-Closure
              - Ben/Taji-Gespräch (siehe Operational Notes)
              - IP-Check TH (Modulhandbuch + Mail an die Betreuung)
              - App-Store-Developer-Account ($99/yr)
              - Privacy-Architektur final entscheiden (on-device only)
              - Erster BIP-Post: "Why I'm trying to measure the
                invisible half of my workday"

Woche  3–6:   MVP-Build (Watch-App + iPhone-App)
              - Streak + Calibration + Today + Heatmap
              - BIP 2×/Woche: Build-Posts, Demo-Videos, Sort-Stability-
                Bug-Post-Mortem als Highlight
              - Newsletter-Wartelist live (Beehiiv/Substack)

Woche  7–8:   TestFlight Closed Beta
              - 20–30 User aus Twitter-Audience
              - Iteration auf Calibration-Completion-Rate + Day-7
                Retention

Woche  9–10:  App-Store-Submission
              - Apple-Review-Cycle einplanen (2 Submission-Rounds als
                Worst-Case)
              - Landing-Page geht live, Wartelist hochfahren

Woche 11–12:  Public Launch
              - "Show HN: I tracked my analog writing time for 90
                days" als Crescendo
              - Product Hunt parallel
              - 60-Tage-Demand-Test startet
```

## Go-to-Market

| Channel | Cadence | Asset |
|---|---|---|
| **Twitter/X + Threads** | 3×/Woche | Build-Posts, Demo-Videos, Daten-Visualisierungen |
| **Newsletter (Beehiiv)** | 1×/Woche | Längere Story-Beats, Wartelist |
| **Hacker News** | 1 Schuss in Woche 11/12 | "Show HN" mit Post-Mortem + Daten |
| **Product Hunt** | 1 Schuss am Launch-Day | Standard-Indie-Move |
| **r/QuantifiedSelf, r/digitalminimalism** | Authentisch, 1 Post pro Community zum Launch | Native Post, kein Spam |

### BIP-Content-Hooks (vorhandene Story-Assets aus dem Semester)

- Sort-Stability-Bug-Post-Mortem (`reports/sort_stability_bug.md`)
- 90-Sek-Kalibrierung als Demo-Video
- Modell-Vergleich Personal (`rf_noah`) ↔ Generic (`rf_all_live`)
- Pen↔Watch-Alignment via Stroke-Variance
- N=10-LOSO-Headline (acc 0.863, AUC 0.935)

## Success vs. Kill-Criteria (60-Tage-Demand-Test)

| Metric | Survive | Pivot | Kill |
|---|---|---|---|
| Day-1 Calibration Completion | ≥ 70 % | 40–70 % | < 40 % |
| Day-7 Retention | ≥ 25 % | 15–25 % | < 15 % |
| Day-30 Retention | ≥ 15 % | 8–15 % | < 8 % |
| Organic Shares (Twitter/IG, ungezwungen) | ≥ 50 / Monat | 10–50 | < 10 |
| Optional "Support" 2 €-Conversion | ≥ 5 % aktiver | 2–5 % | < 2 % |

**Realistischer Outcome-Range:** 1.500–3.000 Downloads, 400 Day-1-aktive,
80 Day-30-aktive, 5–10 freiwillige "Support"-Zahler. Das ist kein
VC-Erfolg, aber ein **klares Signal**. Wenn Retention stimmt, ist
Skalierung Marketing-Problem (lösbar). Wenn nicht, hat man in 60 Tagen
statt 18 Monaten gelernt.

## Pre-Launch-Checklist (vor erstem BIP-Post)

1. **Privacy-Architektur final.** Empfehlung: **on-device only**, keine
   Cloud-Sync der Sensor-Daten. Nur aggregierte Minuten/Tag werden
   (optional) gesynct. Marketing-Asset + EU/DSGVO-schmerzfrei + spart
   Hosting-Kosten.
2. **IP-Check TH.** Modulhandbuch ML4SCS + Studien-/Prüfungsordnung
   prüfen, ggf. kurze Nachricht an die Betreuung. Vor erstem öffentlichen
   BIP-Post abschließen.
3. **App-Store-Compliance vorbereiten.** Continuous-Motion-Tracking
   braucht klare Privacy-Disclosure + Justification. 2 Review-Rounds
   als Worst-Case einplanen.
4. **Modell-Update-Strategie.** Für V1: bundled Joblib pro App-Version
   (einfach). Server-Push verschoben auf v2.
5. **Modern-Pool-Live-Inference-Gap schließen oder umgehen.**
   `LiveInference.append_sample` akzeptiert aktuell nur 6 Kanäle
   (Legacy). V1 nutzt daher Legacy-Modell (88 Features). Modern-Pool-
   Migration für 9-Kanal-Modell ist Post-V1.

## Operational Notes

### Ben & Taji-Gespräch

Früh, klar, mit Wertschätzung — *vor* erstem BIP-Post. Wortlaut-Vorschlag:

> "Ich will weiterbauen, als mein Projekt. Eure Arbeit am Semester wird
> auf Website + README explizit benannt, ihr behaltet das Recht, das
> Projekt in eurem Portfolio zu nutzen. Wenn es jemals Umsatz schafft,
> reden wir nochmal."

Schriftlich (Mail/Signal). Klärt soziale Frequenz, bevor es kommerziell
wird.

### Solo-Beirat

Solo-Founder, die's geschafft haben (Pieter Levels, Marc Köhlbrugge),
hatten alle einen lockeren Beirat — 2–3 Leute, die nicht mitarbeiten,
aber alle 2 Wochen sparring geben. Naheliegend:

- Betreuer als Advisor (Modell-/Forschungs-Seite)
- Ein:e Indie-Hacker aus dem deutschen BIP-Twitter (Produkt/Marketing)

Kostet nichts, fängt Tunnel-Blick ab.

### Defensibility-Hypothese gegen Apple

Apple könnte die Feature in WatchOS nachziehen (wie Sleep, Handwashing,
Fall-Detection). Antwort: Apple baut **Plattform-Features**, nicht
Productivity-Apps mit Streak-Mechanik, Sunday-Review und Notion-
Integration. Strava lebt neben Apple Fitness, Sleep-Cycle neben Apple
Sleep — dieselbe Logik schützt euch. Tiefe statt Breite verteidigen.

## Pivot-Optionen falls 60-Tage-Test "Pivot"-Range trifft

| Signal | Mögliche Reaktion |
|---|---|
| Day-7 ≥ 25 %, Day-30 < 15 % | Retention-Problem — AI-Coach + Sunday-Review früher in V1 ziehen, Streak alleine reicht nicht |
| Day-1 Calibration < 40 % | Onboarding-Problem — auf "Generic from day one + opt-in calibration" wechseln |
| Day-30 ≥ 15 %, Support-Conversion < 2 % | Free-Tier zu komplett — Premium-Features früher gaten |
| Day-30 ≥ 15 %, hohe Shares aber wenig Free→Support | Audience falsch — Pivot auf ADHD-Vision oder Notion-Power-User vorbereiten |

## Was als Nächstes

Wenn dieses Spec freigegeben ist: separater Implementierungs-Plan für die
Pre-Launch-Closure-Phase (Woche 1–2) als nächste Iteration. Watch-App-
und iPhone-App-Skeleton ist eigener Plan in Woche 3–6.
