# FoxRadio

Android-App, die zu festen Uhrzeiten Audio-Blöcke über die gerade laufende Musik legt
(YouTube Music, Spotify, Radio-App, egal). Die Musik wird ausgeblendet oder leiser
gemacht, der Block läuft, danach geht die Musik weiter. Gesamtkonzept: `docs/PLAN.md`.

Stand: Phase 1, Testträger. Spielt einen festen Testblock (Jingle plus Uhrzeitansage
per Android-Sprachausgabe). Playlist-Download und echte Inhalte kommen später.

## APK holen

Jeder Push baut per GitHub Actions eine Debug-APK und hängt sie an ein Release.
Pro Branch gibt es ein Release mit Tag `apk-<branch>`, das bei jedem Build ersetzt wird.

1. Am Handy die Releases-Seite des Repos öffnen und die APK laden.
2. Installation aus unbekannten Quellen für den Browser erlauben, wenn gefragt.
3. Updates einfach drüber installieren. Alle Builds sind mit demselben Debug-Keystore
   signiert (`app/debug.keystore`), Deinstallieren ist nicht nötig.

Android Studio wird nicht gebraucht. Lokal bauen geht mit `./gradlew assembleDebug`,
wenn Android SDK und JDK 17 vorhanden sind.

## Einrichtung auf Xiaomi (Mi 10T Lite 5G)

MIUI und HyperOS beenden Hintergrund-Apps aggressiv. Ohne diese Schritte kommen
die Blöcke nicht zuverlässig:

1. App öffnen. Unter "Berechtigungen" muss alles auf "erteilt" stehen.
   Die Buttons öffnen jeweils die passende Systemseite.
2. Autostart: Button "Xiaomi Autostart öffnen", FoxRadio einschalten.
   Alternativ: Sicherheit, Berechtigungen, Autostart.
3. Akku: Einstellungen, Apps, Apps verwalten, FoxRadio, Akkusparmodus,
   "Keine Einschränkungen".
4. Exakte Wecker: Falls "fehlt", Button "Exakte Wecker freigeben".

## Testablauf (Phase 1)

1. YouTube Music oder eine Radio-App starten, Musik läuft.
2. FoxRadio öffnen, "Testblock jetzt abspielen". Erwartung im Modus
   "Fadeout + Pause": Musik blendet in etwa 1,5 Sekunden aus und pausiert,
   Jingle und Ansage laufen, Musik setzt wieder ein und blendet in 2 Sekunden auf.
3. Modus auf "Nur leiser" stellen und wiederholen. Erwartung: Musik läuft leise
   weiter, Block liegt drüber.
4. "Test in 2 Minuten": Handy sperren, Musik laufen lassen. Prüft den Weg über
   den Wecker aus dem Hintergrund. Das ist der Fall, der auf Xiaomi scheitern kann.
5. Sendeplan aktivieren. Blöcke kommen 07:00 bis 16:00 zur vollen Stunde,
   standardmäßig nur Montag bis Freitag.
6. Das Protokoll unten in der App zeigt, was passiert ist: Wecker ausgelöst,
   Audio Focus erhalten, Fehler.

## PC-Seite: Stimmen rendern (Phase 2)

`pc/foxtts.py` rendert Dialogzeilen über die ComfyUI-API mit Qwen3-TTS und
schneidet sie zu einem Block. Läuft mit der eingebetteten Python von ComfyUI,
weil dort PyAV und numpy schon dabei sind:

```
cd FoxRadio
copy pc\foxtts.example.json pc\foxtts.json
C:\Users\marco\Desktop\ComfyUI_windows_portable\python_embeded\python.exe pc\foxtts.py status
```

Einrichtung:
1. In ComfyUI den Dev-Modus einschalten (Einstellungen), pro Stimme einen
   Workflow bauen: Qwen3-TTS-Knoten (Voice Design oder Voice Clone) plus
   SaveAudio. Über "Save (API Format)" als `pc/voices/a.json` und
   `pc/voices/b.json` speichern.
2. `python pc\foxtts.py probe pc\voices\a.json` zeigt die Knoten und welcher
   Text-Eingang ersetzt wird. Erkennt er den falschen, in `foxtts.json` bei
   der Stimme `text_node` und `text_input` setzen.
3. `python pc\foxtts.py block pc\scripts\testdialog.txt -o work\test.mp3`
   rendert den Testdialog. Daneben entsteht `test.json` mit Renderzeit pro
   Zeile und dem Echtzeitfaktor, das ist die Messung für die Modellwahl.

Das Skript startet ComfyUI über `run_nvidia_gpu.bat`, wenn die API nicht
antwortet. Skriptformat: `A: Text`, `B: Text`, Leerzeile ist eine längere
Pause, `#` ist Kommentar.

## Projekt

- `app/src/main/java/de/alchemyfox/foxradio/`
  - `AudioEngine` Fade über die Medienlautstärke, Audio Focus, Jingle, Ansage
  - `PlaybackService` Foreground Service, spielt genau einen Block
  - `Scheduler` Sendeschema und AlarmManager
  - `AlarmReceiver`, `BootReceiver` Wecker und Neuplanung nach Neustart
  - `TtsSpeaker` Android-Sprachausgabe
  - `MainActivity` Test-Buttons, Modus, Sendeplan, Berechtigungen, Protokoll
- Build: Gradle 8.14.5, Android Gradle Plugin 8.13.2, Kotlin 2.3.21,
  compileSdk 35, minSdk 26.
- `pc/foxtts.py` ComfyUI-Client, Schnitt, MP3. `pc/scripts/` Dialog-Skripte,
  `pc/voices/` Workflows pro Stimme (nicht im Repo bis sie stehen)
- CI: `.github/workflows/android.yml`
