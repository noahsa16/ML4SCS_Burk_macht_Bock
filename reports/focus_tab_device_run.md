# Fokus-Tab — Gerätenachweis

Status: **AUSSTEHEND.** Kein Test im Plan
`docs/plans/2026-08-31-scrybe-focus-area.md` beweist die Punkte unten. Sie
brauchen ein gekoppeltes iPhone und eine Apple Watch Series 7 (Spec §13).

Was maschinell belegt ist, steht dagegen fest: 404 Tests grün, iOS- und
watchOS-Gerätebuild `** BUILD SUCCEEDED **` (Stand Commit `fe90b0c`). Das
beweist, dass der Code baut und die Logik hält — nicht, dass die Uhr sich am
Handgelenk so verhält.

## Aufspielen

```bash
xcodebuild -project watch_streamer/WatchStreamer.xcodeproj -scheme "WatchStreamer" \
  -destination 'generic/platform=iOS' -configuration Debug build
xcrun devicectl device install app --device <iphone-udid> <app>
xcrun devicectl device install app --device <watch-udid> "<app>/Watch/WatchStreamer Watch App.app"
```

Gerät: _______________  iOS / watchOS: _______________  Datum: _______________

## Prüfliste

| # | Prüfung | Erwartet | Ergebnis |
|---|---|---|---|
| 1 | Fokusstart bei getrennter Server-WebSocket-Verbindung, Uhr erreichbar | Sitzung startet; der Start hängt nicht am Server | _(ausstehend)_ |
| 2 | Watch-App im Vordergrund | Start wird bestätigt | _(ausstehend)_ |
| 3 | Watch-App im Hintergrund | Start wird bestätigt oder ehrlich als unbestätigt gemeldet | _(ausstehend)_ |
| 4 | Workout-Freigabe verweigert | Ablehnung wird als Ablehnung erklärt, **nicht** als Timeout; kein „Erneut versuchen" | _(ausstehend)_ |
| 5 | Cap greift auf der Uhr, einmal mit herabgesetztem Wert | Sitzung endet mit „Zeitgrenze erreicht" | _(ausstehend)_ |
| 6 | Force-Quit des iPhones bei laufender Sitzung, dann Neustart | Sitzung wird über `capture_mode` wiedergefunden, Laufzeit ab echtem Start | _(ausstehend)_ |
| 7 | Neustart der Uhr bei laufender Sitzung | dokumentiertes Verhalten, kein stiller Zombie-Stream | _(ausstehend)_ |
| 8 | Header und Tab-Bar im Lauf-Zustand | verschwinden beim Start, kommen beim Ende zurück | _(ausstehend)_ |
| 9 | Kreatur bei 140 pt, größte Dynamic-Type-Stufe, kleines iPhone | lesbar, nichts abgeschnitten | _(ausstehend)_ |
| 10 | VoiceOver über Tabs, Dauersatz, Tracking-Punkt, Kreatur | jede Ansage benennt, was sie meint | _(ausstehend)_ |

### Zu Punkt 4 — worauf genau zu achten ist

Der Unterschied zwischen Ablehnung und Timeout ist der Grund, aus dem
`FocusStartOutcome` in `.unconfirmed` und `.unreachable` getrennt wurde. Eine
verweigerte Freigabe darf **kein** „Erneut versuchen" anbieten: der Versuch
ändert nichts, solange die Freigabe fehlt. Umgekehrt darf ein Timeout nicht
behaupten, die Uhr sei nicht erreichbar — darüber sagt eine ausgebliebene
Antwort nichts.

### Zu Punkt 6 — worauf genau zu achten ist

Die Uhr meldet im Poll `capture_mode` und die echte Startzeit. Nach dem
Neustart muss die Laufzeit **ab dem echten Start** zählen, nicht ab dem
Wiederfinden, und das Zeitlimit muss entsprechend früher greifen. Eine
Sitzung, deren Start länger als das Limit zurückliegt, wird gar nicht erst
übernommen.

## Offen und bewusst nicht Teil dieses Plans

Der vollständige `WatchConnectionState` über Header, Profil und
Offline-Banner ist laut Spec §9 **verpflichtender Bestandteil von Phase A vor
einem echten Launch** und noch nicht gebaut.
