# FoxRadio — Gesamtplan (Konzept B: Overlay)

Persönliches Audio-Programm, das sich über beliebig laufende Musik legt.
Morning Show mit zwei Stimmen, danach stündliche Blöcke. Sendezeit 07:00–16:00
während der Arbeit.

Stand: 2026-09-05 — Phase 1 in Umsetzung als Android-App (siehe README).
Entscheidungen vom 2026-09-05 sind in Abschnitt 7 eingetragen.

---

## 1. Konzept

Verworfen wurde der eigene Sender (Icecast + Liquidsoap auf dem VPS). Grund:
Er hätte einen eigenen Musikkatalog, einen laufenden Server und einen
Streaming-Stack gebraucht — für einen einzigen Hörer.

Stattdessen: Die Musik kommt aus einer beliebigen App auf dem Handy
(YouTube Music, Spotify, egal). Deine Blöcke legen sich darüber wie eine
Navi-Ansage. Android regelt das über Audio Focus. Zwei Modi, in der App
umschaltbar:

- **Fadeout + Pause:** Die App fährt die Medienlautstärke stufenweise runter,
  holt sich den Audio Focus (`AUDIOFOCUS_GAIN_TRANSIENT`, die Musik-App
  pausiert), spielt den Block, gibt den Focus ab und blendet wieder ein.
- **Ducking:** `AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK`, die Musik läuft leiser
  weiter, der Block liegt drüber.

Ein echtes Ausblenden der fremden App ist nur über die globale Medienlautstärke
möglich, deshalb der Stufen-Fade. Ob das gut klingt, klärt Phase 1.

**Vorteile:** Keine Rechtefragen, kein Musikarchiv, kein VPS, freie Wahl der
Musikquelle.
**Nachteil:** Ansagen fallen mitten in einen Song. Nicht änderbar, weil du
keine Kontrolle über die fremde App hast.

---

## 2. Architektur

**PC zuhause** — läuft nachts, per SwitchBot geweckt:
1. Feeds abrufen und filtern
2. Dialog-Skripte für alle Blöcke generieren (Claude Code headless)
3. Jede Sprecherzeile einzeln mit Qwen3-TTS rendern
4. Zeilen pro Block zu einer Datei zusammenschneiden
5. Upload auf den Webspace, plus Playlist-Datei
6. Herunterfahren

**Webspace (alchemy-fox.de, Hosting Basic)** — reine Ablage:
- Verzeichnis mit den Tagesblöcken
- `playlist.json` mit Uhrzeit, Dateiname, Titel
- Passwortschutz per .htaccess, Abruf über HTTPS

**Handy** — Android-App (Kotlin), Tasker wurde übersprungen:
- zieht morgens die Playlist
- lädt die Blöcke vor (kein Streaming, wegen Funklöchern in der Halle)
- spielt sie zur passenden Zeit mit Audio Focus über die laufende Musik

Der Strato-VPS wird für dieses Projekt nicht gebraucht.

---

## 3. Sendeschema

```
05:00  PC startet, Produktion läuft
06:30  Upload fertig, PC fährt runter
07:00  MORNING SHOW (10-15 Min, zwei Stimmen)
08:00  Block
09:00  Block
...    stündlich
15:00  Block
16:00  Abschluss, kurz
```

Zehn Blöcke pro Tag. Die Morning Show ist der lange, die Stundenblöcke laufen
bei 2–3 Minuten.

Entschieden: feste Uhrzeiten, in der App standardmäßig Montag bis Freitag
(umschaltbar). Intervalle ab Arbeitsbeginn sind verworfen.

---

## 4. Rubriken

**Morning Show (07:00)**
- Begrüßung, Datum, Uhrzeit, was heute ansteht
- Wetter für Ellwangen
- Gaming-News, die größte Meldung ausführlicher
- Entwickler-/KI-Themen
- Anthropic-Neuigkeiten, falls es welche gibt
- Indie-RPG-Vorstellung: ein bis zwei Projekte

**Stundenblöcke**
- Uhrzeit
- Wetter-Kurzupdate
- ein bis zwei Gaming-Meldungen
- Entwickler-Thema oder KI-News im Wechsel
- gelegentlich ein Indie-RPG-Projekt

**Wichtig für die Textgenerierung:** Feste Rubriken mit engem Prompt, keine
freie Plauderei. Zwei-Stimmen-Dialog kippt sonst sofort ins Peinliche
("Ja Chris, absolut, und weißt du was noch spannend ist?"). Jede Rubrik bekommt
eine feste Struktur und eine Längenvorgabe.

---

## 5. Die zwei Stimmen

Qwen3-TTS ist Apache-2.0, offene Gewichte, Deutsch wird unterstützt. Verfügbar
in 0.6B und 1.7B.

**Zu beachten:** Die neun mitgelieferten Sprecher decken Englisch, Chinesisch,
Japanisch und Koreanisch ab — kein Deutsch. Beide Stimmen müssen also über
Voice Cloning (3 Sekunden Referenzaudio genügen) oder Voice Design per
Textbeschreibung erzeugt werden.

Rollen sollten klar getrennt sein, sonst klingen beide gleich:
- eine Stimme führt durch die Sendung, sachlich, macht die Übergänge
- die zweite kommentiert, bringt die Meinung, ist lockerer

Qwen3-TTS kann Tonfall, Tempo und Emotion per Anweisung steuern. Damit spricht
derselbe Sprecher den News-Teil nüchtern und den Gaming-Teil aufgeräumter.

**Produktionsmenge:** Zwei Stimmen im Dialog heißt, jede Zeile wird einzeln
gerendert und danach zusammengeschnitten. Eine Morning Show sind 30–50
Wortwechsel, die Stundenblöcke je 8–15. Macht **150–300 Einzeldateien pro
Nacht**. GPU ist eine RTX 5070 Ti — ein 1,7B-Modell passt dort mühelos rein,
VRAM ist kein Thema. Offen ist allein der Durchsatz: 150–300 Clips müssen
zwischen 05:00 und 06:30 fertig sein. Wird in Phase 2 gemessen, danach steht
fest ob 1.7B geht oder 0.6B reicht.

---

## 6. Feeds

Grundsatz: RSS statt freier Websuche. Feste Quellen, LLM als Filter und Texter.
Verhindert erfundene Meldungen.

**Anthropic:** Kein RSS nötig. anthropic.com/news ist server-gerendert und
kommt beim direkten Abruf als saubere Liste mit Datum, Kategorie, Titel und
Link heraus (geprüft 09/2026). Claude Code holt die Seite im Nachtlauf selbst
und filtert, was seit gestern dazugekommen ist. Kein Feed-Mirror, keine
Abhängigkeit von Dritten.

Falls das Layout sich irgendwann ändert, bricht der Abruf — der Block sollte
dann übersprungen werden statt leer zu senden.

**Gaming und Entwicklung:** Quellen stehen noch nicht fest. Auswahl gehört in
Phase 4.

**Indie-RPG:** Quellen offen (itch.io, Steam-Neuheiten, Kickstarter, RSS von
Indie-Magazinen). Auswahl in Phase 4.

**Wetter:** Ein Problem, das im Konzept steckt — alles ist um 05:00 gerendert.
Die 15:00-Wetteransage ist damit eine zehn Stunden alte Vorhersage. Falls das
stört, müsste das Handy Wetter live ziehen und mit einer schnellen
On-Device-Stimme sprechen. Anderer Aufwand, andere Stimme, klingt anders als
der Rest. Offene Entscheidung. Die Uhrzeit spricht die App schon jetzt live
über die Android-Sprachausgabe, dasselbe wäre für Wetter denkbar.

---

## 7. Offene Entscheidungen

- [x] Tasker zum Testen oder direkt eine Android-App bauen? → App, Kotlin,
      Build über GitHub Actions (2026-09-05)
- [x] Feste Uhrzeiten oder Intervalle ab Arbeitsbeginn? → feste Uhrzeiten
- [x] Unterbrechung: Pause oder Ducking? → beides, in der App umschaltbar
- [x] Testgerät: Xiaomi Mi 10T Lite 5G (Android-Version ungeprüft, vermutlich 12)
- [ ] Wetter: mitgerendert (veraltet) oder live auf dem Handy (Extraaufwand)?
- [ ] Welche Gaming-, Entwickler- und Indie-RPG-Feeds?
- [ ] Die zwei Stimmen definieren und gegeneinander testen
- [ ] Qwen3-TTS 0.6B oder 1.7B — Qualität gegen Renderzeit abwägen
- [ ] Wake-on-RTC im BIOS statt SwitchBot? Zuverlässiger, falls das Board es kann
- [ ] Was passiert, wenn der Nachtlauf fehlschlägt — alte Blöcke oder Stille?
- [ ] Wecker-Variante: `setExactAndAllowWhileIdle` (aktuell) oder `setAlarmClock`,
      falls MIUI Wecker verschluckt

---

## 8. Umsetzung in Phasen

Jede Phase für sich testbar. Nicht weitergehen, bevor die vorige läuft.

**Phase 1 — Beweis, dass Overlay funktioniert** (in Arbeit)
Android-App mit Test-Button, Test-Wecker und festem Sendeplan. Spielt einen
Jingle plus Uhrzeitansage über laufende Musik, beide Unterbrechungsmodi.
Ziel: YouTube Music blendet sauber aus und kommt wieder hoch, auch bei
gesperrtem Handy aus dem Hintergrund.

**Phase 2 — Stimmen**
Qwen3-TTS lokal aufsetzen, zwei deutsche Stimmen erzeugen, denselben Testdialog
rendern und anhören. Renderzeit messen.
Ziel: Zwei Stimmen, die du neun Stunden lang erträgst.

**Phase 3 — Ein Block von Hand**
Einen Stundenblock komplett durchziehen: Text schreiben, rendern,
zusammenschneiden, hochladen, auf dem Handy abspielen.
Ziel: Die ganze Kette einmal manuell durchlaufen.

**Phase 4 — Automatisierung**
Feeds, Textgenerierung mit festen Rubriken, Batch-Rendering, Schnitt, Upload,
Autostart auf dem PC.
Ziel: Ein Tag läuft ohne Handgriff.

**Phase 5 — App ausbauen**
Playlist von alchemy-fox.de ziehen, Blöcke morgens vorladen, pro Slot die
passende Datei statt des Testblocks, Fallback wenn nichts Neues da ist.

**Phase 6 — Feinschliff**
Morning Show ausbauen, Monitoring (Nachricht aufs Handy wenn der Nachtlauf
scheitert), Rubriken nachjustieren.

---

## 9. Risiken

| Risiko | Auswirkung | Gegenmaßnahme |
|---|---|---|
| PC startet nicht | Keine neuen Blöcke | Handy spielt die von gestern oder schweigt |
| Dialog klingt künstlich | Nervt nach drei Tagen | Enge Prompts, feste Rubriken, früh testen |
| Renderzeit zu lang | Nachtlauf wird nicht fertig | 0.6B statt 1.7B, weniger Wortwechsel |
| Rate-Limit erreicht | Keine Texte | Lokales Fallback-Modell |
| Audio Focus greift nicht | Overlay funktioniert nicht | Phase 1 klärt das, bevor Aufwand entsteht |
| MIUI killt die App | Wecker feuern nicht | Autostart, Akku ohne Einschränkung, notfalls `setAlarmClock` oder dauerhafter Foreground Service |
| anthropic.com ändert Layout | Rubrik fällt aus | Block überspringen statt leer senden |

---

## 10. Was wegfällt gegenüber Konzept A

Kein Icecast, kein Liquidsoap, kein nginx, kein Musikarchiv, keine
Rotationslogik, keine GEMA-Frage, kein VPS. Dafür kommt die Handy-Seite dazu,
die es vorher nicht gab.

---

## 11. Build und Test ohne Android Studio

Die App wird nicht lokal, sondern von GitHub Actions gebaut
(`.github/workflows/android.yml`). Jeder Push erzeugt eine Debug-APK und ein
Release `apk-<branch>`. Installation und Test laufen am Handy, Fehler werden
aus den CI-Logs gelesen und gefixt. Fester Debug-Keystore im Repo, damit
Updates ohne Deinstallation gehen. Details und Xiaomi-Schritte in der README.
