---
titel: "Schreiberkennung per Apple Watch"
semester: "SoSe 2026"
team: ["Noah Samel", "Tajuddin Snasni"]
frage: "Lässt sich allein aus den IMU-Daten einer Apple Watch erkennen, ob eine Person gerade mit der Hand schreibt – unabhängig davon, wer schreibt und was geschrieben wird?"
domaene: "Wearable Sensing / Activity Recognition"
sensorik: ["Apple Watch", "Moleskine Smart Pen (nur als Ground Truth)"]
datenart: "Eigene Aufnahmen unter counterbalanciertem Studienprotokoll. Watch-IMU (Beschleunigung + Gyroskop) mit automatisch gelabelten Stiftstrichen als Ground Truth. Klassen: Schreiben, kein Schreiben – inkl. schreibähnlicher Störaktivitäten wie Tippen und Scrollen"
datenmenge: "32 Proband*innen, 81.938 gelabelte 1-s-Fenster (ca. 11 h Sensordaten)"
methode: ["Stift↔Watch-Zeitabgleich per Varianzminimierung", "Sliding-Window + 88 Statistik-/Spektral-Features", "Random Forest", "HMM-Glättung", "TCN-BiGRU auf Rohsequenzen", "Grouped 5-Fold nach Person"]
ergebnis: "Random Forest 86,5 % Accuracy / 0,942 ROC-AUC je 1-s-Fenster; mit HMM-Glättung 89,8 % live (kausaler Filter) bzw. 91,7 % im Nachhinein (Smoother), jeweils 32/32 Folds besser. Bestes Modell TCN-BiGRU auf 5-s-Fenstern: 92,1 % Accuracy / 0,975 ROC-AUC"
limitation: "Handschrift und schnelles Tastatur- oder Handy-Tippen sind am Handgelenk teils nicht unterscheidbar (bei einzelnen Personen bis zu 2/3 der Tippfenster als Schreiben erkannt). Random Forest reagiert nicht mehr auf zusätzliche Daten; nur das Sequenzmodell skaliert noch"
tags: ["Wearable", "IMU", "Klassifikation", "Random Forest", "Deep Learning", "Watch-App"]
repo: "https://github.com/noahsa16/ML4SCS_Burk_macht_Bock"
zustimmung_veroeffentlichung: "ja"
---
![Team oder anderes interessantes Foto, das das Projekt beschreibt](https://github.com/noahsa16/ML4SCS_Burk_macht_Bock/blob/main/docs/assets/team.jpg?raw=true)
[Demovideo – hier verlinken](https://www.youtube.com/)

Das Projekt untersucht, ob sich Handschrift allein aus den Bewegungssensoren
einer Apple Watch erkennen lässt. Während der Datenaufnahme liefert ein
Moleskine Smart Pen die Ground Truth: Jeder Stiftstrich labelt die Watch-Samples
zum passenden Zeitpunkt, der Zeitversatz zwischen Stift und Uhr wird pro Sitzung
automatisch per Varianzminimierung bestimmt. Ein Studienprotokoll mit
counterbalancierter Reihenfolge mischt Schreibaufgaben mit schreibähnlichen
Störaktivitäten wie Tippen, Scrollen und Gestikulieren.

In der personenweisen Kreuzvalidierung erreicht ein Random Forest auf 88
Handfeatures je 1-s-Fenster 86,5 % Accuracy und 0,942 ROC-AUC. Eine kausale
HMM-Glättung der Vorhersagen hebt das ohne Nachtraining auf 89,8 %, in allen
32 Folds; darf der Decoder den ganzen Tag im Nachhinein sehen (Smoother), sind es
91,7 %. Ein TCN-BiGRU auf rohen 5-s-Sequenzen erreicht 92,1 % Accuracy und
0,975 ROC-AUC. Die verbleibenden Fehler konzentrieren sich auf schnelles Tippen,
das bei einzelnen Personen wie Schreiben aussieht.

Zusätzlich entstand eine eigene App für iPhone und Apple Watch, die das Modell
direkt auf der Uhr ausführt und die tägliche Schreibzeit ohne Server
protokolliert. Wichtigste offene Punkte: mehr Proband*innen mit aggressivem
Tippstil sowie die Hardware-Validierung der passiven On-Watch-Erkennung.
