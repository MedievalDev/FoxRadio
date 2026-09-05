# Übergabe an die lokale Session

Stand 2026-09-05. Aus der Cloud gebaut und getestet: App komplett (Overlay,
Sendeplan, Sync, Artikel), PC-Pipeline komplett gegen Mock-Server. Die lokale
Session hat Schritt 1 (Feeds) erledigt und in Schritt 2 das direkte
TTS-Backend gebaut. Was fehlt, braucht den PC, den Webspace und das Handy. Reihenfolge einhalten,
jeder Schritt ist für sich prüfbar.

## 1. Feeds prüfen (10 Minuten)

```
set PY=C:\Users\marco\Desktop\ComfyUI_windows_portable\python_embeded\python.exe
%PY% pc\feeds.py check
%PY% pc\feeds.py weather
```

Die URLs in `pc/feeds.json` waren aus der Cloud nicht erreichbar und sind
ungeprüft. Tote Quellen ersetzen oder streichen. Für `anthropic.com/news`
prüfen, ob `parse_anthropic_news` in `pc/feeds.py` Titel und Datum findet,
sonst die Regex an die echte Seite anpassen. Ergebnis mit
`%PY% pc\feeds.py fetch -o pc\work\feeds.json` ansehen.

## 2. Stimmen (Phase 2)

Stand der lokalen Session (Commit 89b977a): Der ComfyUI-Node rendert mit dem
transformers 5.9 von ComfyUI nicht. Qwen3-TTS läuft deshalb direkt aus dem
ComfyUI-Ordner in einem eigenen Arbeitsprozess mit der isolierten Umgebung
`qwen_tts_env` (Backend `direct`, Standard in `foxtts.example.json`). Das
Modell bleibt geladen, sdpa-Attention, Echtzeitfaktor 2,2. Damit passen 300
Zeilen à fünf Sekunden in etwa 55 Minuten, also in das Fenster 05:00 bis 06:30.

1. `pc\foxtts.example.json` nach `pc\foxtts.json`, Pfade unter `direct` prüfen.
2. Referenzen erzeugen, je Stimme einmal:
   `%PY% pc\foxtts.py line -v A_design -t "<Satz>" -o pc\voices\a_ref.wav`
   und dasselbe mit `B_design` nach `b_ref.wav`. Anhören. Passt die Stimme
   nicht: `instruct` oder `seed` unter `A_design` und `B_design` ändern,
   wiederholen. Den gesprochenen Satz in `pc\voices\ref_texte.txt` und
   exakt so als `ref_text` bei `A` und `B` eintragen.
3. Testdialog: `%PY% pc\foxtts.py block pc\scripts\testdialog.txt -o pc\work\test.mp3`,
   anhören, `test.json` daneben zeigt Renderzeit pro Zeile und den Faktor.
   0.6B oder 1.7B über `model_size` bei `A` und `B`.
4. Musikbett: eigene, rechtefreie Musikdateien nach `pc\music\` legen, pro
   Block wird eine zufällig gewählt und mit minus 20 dB untergelegt. Ohne
   Dateien läuft der Block ohne Musik. Lautstärke über `music.gain_db`.

Nur falls `direct` nicht läuft: Backend `comfy` mit exportierten Workflows,
fertige Vorlagen für drei Node-Pakete in `pc/voices/templates/`, Anleitung
dort. `foxtts.py probe` und `voice-design` gehören zu diesem Weg.

## 3. Texte (Phase 4)

`pc\writer.example.json` nach `pc\writer.json`. Standard ist `claude-cli`,
das nutzt `claude -p` mit dem Abo. Prüfen, dass `claude` im PATH ist und
`claude -p --output-format json` funktioniert. Testen:

```
%PY% pc\writer.py plan --feeds pc\work\feeds.json
%PY% pc\writer.py write --feeds pc\work\feeds.json --out pc\work\scripts --only 07:00
```

Skript lesen. Wenn der Dialog kippt (Floskeln, Erfundenes), Prompt in
`build_prompt` nachschärfen, nicht lockern. Alternative Backend `api`
braucht `pip install anthropic` in der ComfyUI-Python und `ANTHROPIC_API_KEY`.

## 4. Webspace

Auf alchemy-fox.de einen Ordner `foxradio` anlegen, mit `.htaccess` und
`.htpasswd` schützen (Basic Auth). Vorlage in `pc/webspace/htaccess.example`,
Passwortdatei mit `pc/webspace/make_htpasswd.py` oder über den
Verzeichnisschutz im Hosting-Panel. Upload: Strato nimmt weder FTP noch FTPS,
nur SSH. In `pc\night.json` daher `method: sftp` mit SSH-Zugang (paramiko,
Commit 4e3578c), Vorlage `night.example.json`, `remote_dir` ist der Ordner.
Der Basic-Auth-Zugang der App steht als `web_user` und `web_password` mit in
`night.json`. Test:

```
%PY% pc\night.py upload-status "Test"
```

Danach muss `https://alchemy-fox.de/foxradio/status.json` mit Passwort
abrufbar sein.

## 5. Probelauf und erster echter Lauf

```
%PY% pc\night.py run --backend fake --no-upload --no-shutdown
%PY% pc\night.py run --no-shutdown
```

Ergebnis in `pc\work\<datum>\`: Skripte, MP3 pro Slot, `playlist.json`,
`articles.json`, `img\`. Einen Block anhören.

## 6. Handy

In der App unter Verbindung Adresse `https://alchemy-fox.de/foxradio`,
Benutzer und Passwort eintragen, "Jetzt laden". Die Heute-Karte muss den
Tag zeigen, Artikel lesen, Nachhören probieren. Sendeplan an. Am nächsten
Arbeitstag um 07:00 mit laufender Musik testen. Protokoll in der App zeigt,
was der Wecker gemacht hat.

## 7. Automatik

- `pc\night.bat` in der Windows-Aufgabenplanung: täglich 05:00, "Computer
  aufwecken, um diese Aufgabe auszuführen" an, "Nur ausführen, wenn Benutzer
  angemeldet" beachten, sonst startet die ComfyUI-Konsole nicht sichtbar.
- Wake-on-RTC im BIOS oder SwitchBot, damit der PC um 05:00 überhaupt an ist.
- In `night.json` `"shutdown": true`, wenn der Lauf sauber durchläuft.
- Optional `"ntfy_topic"` setzen und die ntfy-App am Handy abonnieren,
  dann kommt bei Fehlern eine Nachricht. Die App zeigt den Status auch so.

## Offen und Annahmen

- Wetter kommt aus dem Nachtlauf, also von 05:00. Live-Wetter am Handy
  bleibt Option.
- Sendetage Mo bis Fr, in der App umschaltbar. Der Nachtlauf läuft jeden
  Tag, an dem die Aufgabe feuert.
- Feed-Auswahl und Rubrik-Zuteilung in `writer.plan_blocks` sind ein
  Startpunkt und sollen nach ein paar Tagen Hören nachjustiert werden.
- Bilder kommen aus og:image der Artikel, keine Rechteprüfung, nur für dich.
