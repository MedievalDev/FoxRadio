# FoxRadio — Gesamtplan (Konzept B: Overlay)

Persönliches Audio-Programm, das sich über beliebig laufende Musik legt.
Morning Show mit zwei Stimmen, danach stündliche Blöcke. Sendezeit 07:00–16:00
während der Arbeit.

Stand: 2026-09-05 — Phase 1 bestanden: Die Android-App legt den Testblock
über YouTube Music, auch bei gesperrtem Handy aus dem Hintergrund (Mi 10T
Lite 5G). Entscheidungen vom 2026-09-05 sind in Abschnitt 7 eingetragen.
Phase 2 vorbereitet: Render-Skript `pc/foxtts.py` steht und ist gegen einen
Mock-Server getestet. Offen ist der Teil am PC: Workflows in ComfyUI bauen,
Stimmen anhören, Renderzeit messen.

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
3. Jede Sprecherzeile einzeln mit Qwen3-TTS rendern (läuft in ComfyUI,
   siehe Abschnitt 5)
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
- spielt sie zur passenden Zeit mit Audio Focus über die laufende Musik,
  aber nur wenn gerade Musik läuft, sonst wird der Block übersprungen
- zeigt die Meldungen des Tages zusätzlich als Artikel zum Nachlesen

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

**Wo es läuft:** Qwen3-TTS ist als ComfyUI-Nodes installiert.
- ComfyUI Portable: `C:\Users\marco\Desktop\ComfyUI_windows_portable`
- Start: `run_nvidia_gpu.bat` in diesem Ordner
- API: `http://127.0.0.1:8188/`
- Die nächtliche Routine-Session startet die BAT, wartet bis die API
  antwortet, schickt pro Sprecherzeile einen Workflow (`POST /prompt`),
  wartet über `/history` auf das Ergebnis und holt die WAV ab.
- Welches Node-Paket installiert ist, muss am PC geprüft werden. Bekannte
  Pakete (Stand 09/2026): DarioFT/ComfyUI-Qwen3-TTS (Voice Design, Voice
  Clone, Prompt Maker zum Wiederverwenden der Stimme), 1038lab/ComfyUI-QwenTTS,
  flybirdxx/ComfyUI-Qwen-TTS (hat zusätzlich Dialogue-Node mit Rollen).
  Der Text-Eingang heißt je nach Paket `text` oder `target_text`, das Skript
  erkennt beides.
- Ausgabe über den ComfyUI-Knoten SaveAudio (FLAC) oder SaveAudioAdvanced,
  das Skript dekodiert mit PyAV und schneidet selbst.

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
In ComfyUI einen Workflow für eine einzelne Sprecherzeile bauen und als
API-JSON exportieren. Skript, das den Workflow per API aufruft und die WAV
abholt. Zwei deutsche Stimmen erzeugen (Voice Clone oder Voice Design),
denselben Testdialog rendern und anhören. Renderzeit pro Zeile messen.
Ziel: Zwei Stimmen, die du neun Stunden lang erträgst, und ein Skript, das
eine Textzeile in eine WAV verwandelt.

**Phase 3 — Ein Block von Hand**
Einen Stundenblock komplett durchziehen: Text schreiben, rendern,
zusammenschneiden, hochladen, auf dem Handy abspielen.
Ziel: Die ganze Kette einmal manuell durchlaufen.

**Phase 4 — Automatisierung**
Routine-Session auf dem PC: ComfyUI per `run_nvidia_gpu.bat` starten, Feeds
holen, Texte mit festen Rubriken generieren, alle Zeilen über die ComfyUI-API
rendern, Schnitt, Upload, ComfyUI beenden, PC herunterfahren.
Ziel: Ein Tag läuft ohne Handgriff.

**Phase 5 — App ausbauen**
Playlist von alchemy-fox.de ziehen, Blöcke morgens vorladen, pro Slot die
passende Datei statt des Testblocks, Fallback wenn nichts Neues da ist.
Dazu die Artikelansicht: Die Nachtproduktion legt neben den Audio-Blöcken
eine `articles.json` ab (Titel, Kurztext, Quelle mit Link, Bild-URL,
Rubrik, zugehöriger Block). Die App zeigt eine "Heute"-Liste mit Karten,
Bild oben, Rubrik-Farbe, und eine Artikelseite. Bilder werden mit den
Blöcken vorgeladen. Bilder kommen aus dem Artikel (og:image des Feeds),
kein eigenes Rendern. Jeder Artikel hat einen Play-Button zum Nachhören:
`articles.json` trägt pro Meldung Block-Datei, Startsekunde und Dauer, die
das Render-Skript beim Schneiden aus den Zeilenlängen berechnet. Die App
spielt dann genau diesen Abschnitt, ohne Overlay-Logik, einfach in der App.

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
| Audio Focus greift nicht | Overlay funktioniert nicht | Phase 1 bestanden, erledigt |
| ComfyUI startet nicht oder Node-Update bricht Workflow | Keine Stimmen | Routine prüft API-Antwort, sonst Abbruch mit Meldung aufs Handy |
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
