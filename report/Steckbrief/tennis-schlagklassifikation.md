---
titel: "Tennis-Schlag-Klassifikation per Apple Watch"
semester: "SoSe 2026"
team: ["Florian Schneider", "Marcel Vogeler", "Metehan Tetik"]
frage: "Lassen sich Bewegungs- und IMU-Daten einer Smartwatch nutzen, um Tennisschläge automatisch zu erkennen und zu klassifizieren?"
domaene: "Sport / Activity Recognition"
sensorik: ["Apple Watch", "Video-Labeling"]
datenart: "Eigene Aufnahmen, Sensordaten + Video, klassenweise gelabelt. Klassen: Vorhand, Rückhand, Aufschlag von unten, Schläger drehen, kein Schlag"
datenmenge: "1400 Ereignisse von 10 Spieler*innen"
methode: ["Event-Fenster + Statistik-Features je Sensorsignal", "Random Forest", "SVM-Vergleich", "Grid-Search", "Leave-One-Session-Out"]
ergebnis: "LOSO 4 Klassen: 95,8 % Accuracy / 0,953 Macro F1. 5 Klassen: 89,1 % Accuracy, aber nur ~76 % Balanced Accuracy"
limitation: "Kleiner Datensatz, neue Sessions noch ungelabelt. Der hohe 4-Klassen-Wert entsteht auch durch Zusammenlegen schwer trennbarer Klassen (Schläger drehen + kein Schlag)"
tags: ["Wearable", "IMU", "Klassifikation", "Random Forest", "Watch-App"]
repo: "https://github.com/Marcel-vgl/ML4SCS"
zustimmung_veroeffentlichung: "ja"
---
![Team oder anderes interessantes Foto, das das Projekt beschreibt](https://github.com/Marcel-vgl/ML4SCS/blob/main/docs/assets/team.jpg?raw=true)
[Großes Tennis - hier Ihr Demovideo verlinken](https://www.youtube.com/watch?v=7H8CXB2ZYJM)

Das Projekt untersucht, ob sich Tennisschläge allein aus den Bewegungssensoren
einer Apple Watch erkennen und in Schlagarten einteilen lassen. Sensordaten
werden mit paralleler Videoaufnahme aufgezeichnet, per Video-Review gelabelt und
über eine Event-Fenster-Pipeline in Statistik-Features je Signal überführt. Ein
Random Forest dient als Baseline, eine SVM als Vergleich.

In der Leave-One-Session-Out-Bewertung erreicht die 4-Klassen-Variante (Schläger
drehen und kein Schlag zusammengelegt) 95,8 % Accuracy und 0,953 Macro F1. Die
vollständige 5-Klassen-Aufgabe ist deutlich schwerer: 89,1 % Accuracy bei nur
rund 76 % Balanced Accuracy, weil die Nicht-Schlag-Klassen schlecht trennbar sind.

Zusätzlich entstand eine eigene TennisTracker-App für iPhone und Apple Watch, die
SensorLog ersetzt und Datenaufnahme sowie Live-Vorhersage direkt auf der Uhr
bündeln soll. Wichtigste offene Punkte: mehr und sauber gelabelte Daten sowie die
Integration des Modells in die Live-Vorhersage.
