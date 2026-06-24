# Live-Demo — Runbook (Abschlusspräsentation)

End-to-End-Bühnendemo: **Apple Watch → iPhone-Bridge → Server → Dashboard/App**,
live geschrieben, Schreiben in Echtzeit erkannt. Dieses Dokument ist der
probbare Ablauf inkl. Pre-Flight, Wow-Momenten und mehrstufigem Fallback.

Der einprägsamste Teil der Präsentation ist *nicht* eine Folie, sondern die
laufende Erkennung. Damit das verlässlich klappt, ist der Ablauf gescriptet und
jeder Schritt hat einen Fallback.

---

## Zielbild (was das Publikum sieht)

1. Eine Person trägt die Watch und schreibt auf Papier.
2. Auf der Leinwand füllt sich live die Schreib-Pille / der Tinten-Ring.
3. Die **Schreibzeit** läuft mit und ist dank des kausalen HMM-Filters ruhig und
   treffsicher — keine zappelnde Sekundenanzeige.
4. Optional: dieselbe Zahl erscheint parallel in der **Scrybe**-iPhone-App — die
   Forschung-zu-Produkt-Pointe.

---

## Pre-Flight-Checkliste (T-15 min)

Reihenfolge strikt einhalten — die Bridge meldet sich nur, wenn der Server schon
läuft.

- [ ] **Server + Tunnel-Sicherheitsnetz** booten:
      ```bash
      scripts/ops/start.sh --tunnel      # Auto-Chain: cloudflare → ngrok → LAN-IP
      ```
      Der Tunnel ist nur das Netz; die Demo läuft idealerweise über **LAN**
      (niedrigste Latenz). Notiere die ausgegebene LAN-IP.
- [ ] **HMM-Live-Parameter vorhanden**: `models/hmm_live.json` existiert
      (committet). Fehlt es, einmal `python scripts/ml/export_hmm_live.py`.
- [ ] **Live-Modell**: im Dashboard → Recording → Inferenz-Karte das **Personal**-
      Modell (`rf_noah`) wählen, wenn die tragende Person Noah ist; sonst
      **Generic** (`rf_all_live`). Beim Generic die Kalibrier-Sekunden abwarten.
- [ ] **Watch-App** läuft, **iPhone-Bridge** zeigt „verbunden" (Server-IP =
      die LAN-IP von oben, in den iPhone-Settings).
- [ ] **Watch-Spill leeren**, falls die Watch zwischendurch offline war:
      iPhone → Repair-Sektion → „Spill verwerfen" (verhindert, dass alte Samples
      einer fremden Session live nachtropfen).
- [ ] **Sample-Rate prüfen**: Dashboard-Topbar zeigt ~50 oder ~100 Hz grün; kein
      `rate_mismatch` in der Pille. Bei Mismatch: Phone-App → Settings → Motion auf
      die Trainings-Rate des gewählten Modells stellen (rf_noah = 100 Hz).
- [ ] **Smoke-Schreibtest** (30 s, hinter der Bühne): einmal schreiben, Pille muss
      anspringen, Focus-Sekunden hochzählen, dann idle → Pille fällt.
- [ ] **Fallback-Session bereit**: eine bekannte saubere Session-ID für den Replay
      (z. B. S039/P13 — stärkste Fold) im Terminal vortippen, nicht ausführen.

---

## Bühnen-Ablauf

### A — Der Haken (Recording-Page)
- Dashboard öffnen, **Recording**-Tab. Live-IMU-Chart läuft.
- Eine Zeile schreiben. Die **Schreib-Pille** springt auf „schreibt gerade", die
  60-s-Sparkline zeigt den Ausschlag.
- *Satz dazu:* „Das Modell sieht nur die Handgelenk-Bewegung — kein Stift, keine
  Kamera. Binäre Entscheidung pro Sekunde."

### B — Die ruhige Schreibzeit (der HMM-Moment)
- Weiter schreiben, dann **kurz absetzen** (Denkpause < 2 s), weiterschreiben.
- *Satz dazu:* „Die rohe Sekundenentscheidung würde hier flackern. Ein kausaler
  Zwei-Zustands-HMM auf der Live-Proba glättet die **Schreibzeit-Entscheidung** —
  er hält den Zustand über kurze Pausen und kippt nur bei klarer Evidenz." Das ist
  der Übergang von *Forschung* (offline +2,4 pp, ohne Retraining) zu *Produkt*
  (die mitlaufende Zahl).

### C — Der Tagesverlauf (Focus-Tab)
- **Focus**-Tab öffnen. Der 24-Stunden-Streifen zeigt die eben geschriebene
  Phase als Block, der „Jetzt"-Marker wandert mit.
- *Satz dazu:* „Über den Tag summiert ist das die Schreibzeit — die eigentliche
  Anwendung: ein Schreib-Fokus-Tracker, Activity-Rings für Handschrift."

### D — Das Produkt (Scrybe-App, optional)
- iPhone spiegeln. Scrybe → **Heute**: derselbe Tinten-Ring füllt sich gegen das
  Tagesziel. Durch **Trends** und **Verlauf** wischen.
- *Satz dazu:* „Dieselbe Pipeline, als fertige App."

### E — Generalisierung (Modell-Switcher)
- Inferenz-Karte → von **Personal** auf **Generic** umschalten.
- *Satz dazu:* „Personal ist auf eine Person trainiert; Generic ist das
  cross-subject-LOSO-Modell — es funktioniert für eine fremde Person, die es nie
  gesehen hat."

---

## Fallback-Ebenen (von leicht nach hart)

1. **Pille springt nicht an** → 2–3 s länger schreiben (das Feature-Fenster ist
   1 s, der Buffer braucht Füllung). Lauter/größer schreiben.
2. **`rate_mismatch` in der Pille** → Phone-Settings-Motion-Rate an das Modell
   anpassen, oder im Picker auf das ratenpassende Modell wechseln.
3. **Watch/BLE fällt aus** → auf **Replay** umschalten: eine bekannte Session
   Sample-für-Sample durch dieselbe Live-Inferenz spielen —
   ```bash
   python scripts/ml/replay_live_inference.py S039
   ```
   erzählt dieselbe Geschichte mit garantiert sauberen Daten.
4. **Netz/Tunnel weg** → LAN-IP direkt im iPhone eintragen (Tunnel war nur Netz).
5. **Alles weg** → die committeten Figuren zeigen: `reports/figures/model_ceiling.png`
   (die Decke + zwei Straßen), `reports/figures/ghost_replay_S019.gif`
   (Tinte vs. Bewegung vs. Proba) und die 3D-Watch-Replay-GIF.

---

## Nach der Demo
- `Ctrl+C` im `start.sh`-TTY beendet Server **und** Tunnel sauber.
- Der Live-Lauf hat in `data/inference_log.csv` echte Ticks hinterlassen — die
  Focus-Aggregate bleiben über einen Server-Neustart wahr (append-only Log).
