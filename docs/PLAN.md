# FoxRadio — Gesamtplan (Konzept B: Overlay)

Persönliches Audio-Programm, das sich über beliebig laufende Musik legt.
Morning Show mit zwei Stimmen, ein Tagesthema in Teilen bis zehn, danach
Blöcke. Sendezeit 07:00–15:00
während der Arbeit.

Stand: 2026-09-05 — Alles, was ohne PC geht, ist gebaut: App mit Overlay,
Sendeplan, Sync, Artikelansicht; PC-Pipeline mit Feeds, Wetter, Texten,
Rendern, Schnitt, Upload und Status, gegen Mock-ComfyUI getestet. Offen sind
die Schritte am PC, Webspace und Handy, siehe `HANDOFF.md`.

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
01:00  PC startet, Produktion läuft
02:30  Upload fertig, PC fährt runter
07:00  News + Tagesthema Teil 1        rund 5 Minuten
07:30  Tagesthema Teil 2               rund 2 Minuten
08:00  News + Teil 3                   rund 5 Minuten
08:30  Tagesthema Teil 4               rund 2 Minuten
08:55  News kurz + Teil 5              endet vor der Pause um neun
09:30  Tagesthema Teil 6               rund 2 Minuten
10:00  News + Teil 7, Abschluss        rund 5 Minuten
11:00  News
11:55  News kurz                       endet vor der Pause um zwölf
13:00  News
14:00  News + Tipp des Tages
15:00  Tagesabschluss + Rezept des Tages, letzter Block
```

Zwölf Blöcke pro Tag. Die Uhrzeiten stehen in der `playlist.json`, die App
liest sie von dort. Kein Block um 16:00, weil um 15:45 Feierabend ist; 08:55
und 11:55 enden vor den Pausen.

Das Tagesthema läuft in sieben Teilen über den Vormittag und wechselt nach
Wochentag: Montag ein neues Indie-Spiel, Dienstag ein Mod-Projekt, Mittwoch
Engine und Technik, Donnerstag eine Spielreihe, Freitag Kickstarter oder
Devlog. Am Wochenende Wochenzusammenfassung, bei einem großen Ereignis
(Messe, Showcase, Studio-Event) eine Sondersendung, sonst eine Indie-Rotation
mit zehn kurz vorgestellten Spielen.

Entschieden: feste Uhrzeiten, in der App standardmäßig Montag bis Freitag
(umschaltbar). Intervalle ab Arbeitsbeginn sind verworfen.

---

## 4. Rubriken

Rubriken und Rollen: A (Mann, sachlich) macht Begrüßung, Spieleentwicklung,
KI, das Tagesthema und den Tipp des Tages. B (Frau, mit Meinung) macht das
Wetter als Drei-Tage-Übersicht, alle Gaming-News am Stück und das Rezept.
Sprecher wechseln nur an Rubrikgrenzen, kein Wechselgespräch. Nicht ins
Programm kommen rundenbasierte Spiele, Anime und japanischer Content, Film
und Serie (`avoid` in `pc/writer.py`).

Vor jeder Rubrik steht ein Jingle: Das Skript fordert ihn als Zeile `J: news`
an, `foxtts.py` setzt `pc/jingles/news.wav` ein. Unter dem ganzen Block liegt
leise ein Musikbett aus `pc/music/`.

**Morning Show (07:00), alte Fassung**
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

**Wo es läuft (Stand 2026-09-05):** Qwen3-TTS läuft direkt aus dem ComfyUI-Ordner,
nicht über den Node. Installiert ist 1038lab/ComfyUI-QwenTTS, aber sein `qwen_tts`
braucht transformers 4.57, ComfyUI hat 5.9. Deshalb startet `foxtts.py` einen
Arbeitsprozess mit der isolierten `qwen_tts_env`, Modell bleibt geladen. Gemessen:
Faktor 1,4 bis 1,7 Echtzeit bei 1.7B mit sdpa. Der folgende Absatz beschreibt den
ursprünglichen ComfyUI-Weg, der als Backend `comfy` erhalten bleibt.

**Ursprünglicher Plan:** Qwen3-TTS ist als ComfyUI-Nodes installiert.
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
zwischen 01:00 und 02:30 fertig sein. Wird in Phase 2 gemessen, danach steht
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

**Wetter:** Ein Problem, das im Konzept steckt — alles ist um 01:00 gerendert.
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
- [x] Wetter: live auf dem Handy per Android-Sprachausgabe vor jedem Block (2026-09-05),
      kein Wetter mehr in den Skripten
- [x] Welche Gaming-, Entwickler- und Indie-RPG-Feeds? → `pc/feeds.json`, geprüft
      2026-09-05, Nachjustieren nach ein paar Tagen Hören
- [x] Die zwei Stimmen definieren und gegeneinander testen → A sachlicher Mann, B
      warme Frau, beide Design plus Clone (2026-09-05), Abnahme durch Marco offen
- [ ] Qwen3-TTS 0.6B oder 1.7B — Qualität gegen Renderzeit abwägen
- [x] Aufwachen: SwitchBot drückt um 00:50 den Einschalter, Aufgabe läuft um 01:00 (2026-09-05)
- [ ] Was passiert, wenn der Nachtlauf fehlschlägt — alte Blöcke oder Stille?
- [ ] Wecker-Variante: `setExactAndAllowWhileIdle` (aktuell) oder `setAlarmClock`,
      falls MIUI Wecker verschluckt

---

## 8. Umsetzung in Phasen

Jede Phase für sich testbar. Nicht weitergehen, bevor die vorige läuft.

**Phase 1 — Beweis, dass Overlay funktioniert** (bestanden 2026-09-05)
Android-App mit Test-Button, Test-Wecker und festem Sendeplan. Spielt einen
Jingle plus Uhrzeitansage über laufende Musik, beide Unterbrechungsmodi.
Ziel: YouTube Music blendet sauber aus und kommt wieder hoch, auch bei
gesperrtem Handy aus dem Hintergrund.

**Phase 2 — Stimmen** (Skript fertig, Stimmen offen)
In ComfyUI einen Workflow für eine einzelne Sprecherzeile bauen und als
API-JSON exportieren. Skript, das den Workflow per API aufruft und die WAV
abholt. Zwei deutsche Stimmen erzeugen (Voice Clone oder Voice Design),
denselben Testdialog rendern und anhören. Renderzeit pro Zeile messen.
Ziel: Zwei Stimmen, die du neun Stunden lang erträgst, und ein Skript, das
eine Textzeile in eine WAV verwandelt.

**Phase 3 — Ein Block von Hand** (offen, siehe HANDOFF)
Einen Stundenblock komplett durchziehen: Text schreiben, rendern,
zusammenschneiden, hochladen, auf dem Handy abspielen.
Ziel: Die ganze Kette einmal manuell durchlaufen.

**Phase 4 — Automatisierung** (Code fertig, Einrichtung offen)
Routine-Session auf dem PC: ComfyUI per `run_nvidia_gpu.bat` starten, Feeds
holen, Texte mit festen Rubriken generieren, alle Zeilen über die ComfyUI-API
rendern, Schnitt, Upload, ComfyUI beenden, PC herunterfahren.
Ziel: Ein Tag läuft ohne Handgriff.

**Phase 5 — App ausbauen** (gebaut, Test mit echten Daten offen)
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

**Phase 6 — Feinschliff** (Monitoring gebaut: status.json in der App, ntfy optional)
Morning Show ausbauen, Rubriken nachjustieren, Feeds nach ein paar Tagen
Hören anpassen.

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
