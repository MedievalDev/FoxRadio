# FoxRadio

Persönliches Radioprogramm, das sich über die laufende Musik auf dem Handy legt.
Nachts produziert der PC aus festen Feeds Dialog-Blöcke mit zwei Qwen3-TTS-Stimmen
(ComfyUI), lädt sie auf den Webspace, die Android-App holt sie morgens und spielt
sie zur vollen Stunde über YouTube Music, Spotify oder eine Radio-App. Die
Meldungen gibt es in der App auch zum Nachlesen mit Bild und zum Nachhören.

Gesamtkonzept und Entscheidungen: `docs/PLAN.md`. Was noch am PC zu tun ist:
`docs/HANDOFF.md`.

## Teile

| Ordner | Was | Läuft wo |
|---|---|---|
| `app/` | Android-App (Kotlin, Material 3) | Handy |
| `pc/` | Nachtlauf: Feeds, Texte, Stimmen, Schnitt, Upload | PC mit ComfyUI |
| `docs/` | Plan und Übergabe | |
| `.github/workflows/` | Baut die APK bei jedem Push | GitHub Actions |

## App

Jeder Push baut eine Debug-APK und hängt sie an das Release `apk-<branch>`
(wird ersetzt). Am Handy von der Releases-Seite laden und drüber installieren,
alle Builds haben denselben Debug-Schlüssel. Die Versionsnummer unten in der
App ist die Build-Nummer.

Was die App macht:
- **Sendeplan** 07:00 bis 16:00 zur vollen Stunde, Mo bis Fr (umschaltbar).
  Spielt den vorgeladenen Block des Slots. Fehlt er oder läuft keine Musik,
  bleibt es still, mit Eintrag im Protokoll.
- **Zwei Modi**: Fadeout plus Pause (Medienlautstärke stufenweise runter, Audio
  Focus, Block, wieder einblenden) oder Ducking.
- **Sync** täglich 06:45 und per Button: `playlist.json`, `articles.json`,
  `status.json`, Blöcke und Bilder vom Webspace in den App-Speicher.
- **Heute**: Stand des Nachtlaufs, Artikelliste mit Bild, Rubrik, Teaser,
  Artikelseite mit Text, Quelle und Nachhören des passenden Abschnitts.
- **Test**: Testblock sofort (Jingle plus Uhrzeit per Android-Sprachausgabe)
  und Test in 2 Minuten für den Hintergrundfall.

Einrichtung auf Xiaomi (Mi 10T Lite 5G): In der App unter Berechtigungen alle
Punkte auf grün bringen (exakte Wecker, Akku-Optimierung, Benachrichtigungen),
dazu Xiaomi Autostart einschalten. Unter Verbindung Adresse, Benutzer und
Passwort des geschützten Webspace-Ordners eintragen, dann "Jetzt laden".

## PC: Nachtlauf

Alles in `pc/`, nur Standardbibliothek plus PyAV und numpy, die in der
eingebetteten Python von ComfyUI schon drin sind:

```
set PY=C:\Users\marco\Desktop\ComfyUI_windows_portable\python_embeded\python.exe
%PY% pc\feeds.py check                       Quellen prüfen
%PY% pc\feeds.py weather                     Wetter Ellwangen
%PY% pc\foxtts.py probe pc\voices\a.json     Workflow prüfen
%PY% pc\foxtts.py block pc\scripts\testdialog.txt -o pc\work\test.mp3
%PY% pc\night.py run --backend fake --no-upload --no-shutdown     Probelauf
%PY% pc\night.py run                         echter Lauf
```

| Datei | Aufgabe |
|---|---|
| `feeds.py`, `feeds.json` | RSS/Atom-Quellen, Anthropic-News, og:image, Wetter über Open-Meteo |
| `writer.py`, `writer.example.json` | Meldungen auf Sendeplätze verteilen, Dialogskripte mit fester Rubrikenstruktur. Backend `claude-cli` (Claude Code headless), `api` (Anthropic-SDK) oder `fake` |
| `foxtts.py`, `foxtts.example.json` | ComfyUI-API: pro Zeile rendern, FLAC dekodieren, mit Pausen schneiden, MP3 |
| `night.py`, `night.example.json`, `night.bat` | Orchestrierung, Artikel-Audio-Offsets, Bilder, `playlist.json`, `articles.json`, `status.json`, Upload per FTP oder Ordner, ntfy bei Fehlern, optional Shutdown |
| `scripts/testdialog.txt` | Testdialog für den Stimmenvergleich |
| `voices/` | Workflows pro Stimme (API-Format aus ComfyUI), nicht im Repo |

Die `*.example.json` als `*.json` kopieren und ausfüllen. `night.bat` in die
Windows-Aufgabenplanung um 05:00 eintragen, mit "Computer aufwecken".

Dateiformat auf dem Webspace (Ordner mit .htaccess):

```
playlist.json            {date, blocks:[{slot,file,kind,duration_s,title}]}
articles.json            {date, articles:[{id,slot,rubric,title,teaser,body,source_name,source_url,image,audio_file,audio_start_s,audio_end_s}]}
status.json              {ok,date,generated_at,message,blocks}
2026-09-08/0700.mp3      Blöcke des Tages
2026-09-08/img/*.jpg     Artikelbilder
```

## Build

Gradle 8.14.5, Android Gradle Plugin 8.13.2, Kotlin 2.3.21, Material 1.14.0,
compileSdk 35, minSdk 26. Lokal: `./gradlew assembleDebug` mit Android SDK
und JDK 17. CI: `.github/workflows/android.yml`.
