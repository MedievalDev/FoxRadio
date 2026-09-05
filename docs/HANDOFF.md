# Übergabe an die lokale Session

Stand 2026-09-05. Aus der Cloud gebaut und getestet: App komplett (Overlay,
Sendeplan, Sync, Artikel), PC-Pipeline komplett gegen Mock-Server. Was fehlt,
braucht den PC mit ComfyUI, den Webspace und das Handy. Reihenfolge einhalten,
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

## 2. Stimmen in ComfyUI (Phase 2)

Vorlagen für die drei gängigen Node-Pakete liegen fertig in
`pc/voices/templates/` (Namen und Eingänge aus dem Quellcode der Pakete).
Es muss nichts mehr in der ComfyUI-Oberfläche zusammengeklickt werden.

1. ComfyUI starten. Unter Custom Nodes nachsehen, welches Qwen3-TTS-Paket
   installiert ist: DarioFT (`dario_`), flybirdxx (`fly_`) oder 1038lab
   (`ailab_`). Ist es ein anderes, einen Design-Workflow per Hand bauen und
   über "Save (API Format)" exportieren, der Rest bleibt gleich.
2. `pc\foxtts.example.json` nach `pc\foxtts.json` kopieren.
3. Stimme A: `instruct` in der `*_design.json` prüfen (Vorschlag steht drin),
   dann die Referenz erzeugen, direkt in den ComfyUI-Eingangsordner:
   `%PY% pc\foxtts.py voice-design pc\voices\templates\dario_design.json -o C:\Users\marco\Desktop\ComfyUI_windows_portable\ComfyUI\input\ref_a.wav`
   Anhören. Passt sie nicht: Beschreibung oder `seed` ändern, wiederholen.
4. `*_clone.json` nach `pc\voices\a.json` kopieren, `ref_text` auf den Satz
   setzen, den `voice-design` ausgegeben hat, `LoadAudio.audio` bleibt
   `ref_a.wav`.
5. Stimme B genauso mit `ref_b.wav` und `pc\voices\b.json`.
6. `%PY% pc\foxtts.py probe pc\voices\a.json` muss den Text-Knoten erkennen
   (bei allen Vorlagen geprüft).
7. `%PY% pc\foxtts.py block pc\scripts\testdialog.txt -o pc\work\test.mp3`,
   anhören, `test.json` daneben zeigt Renderzeit pro Zeile und Echtzeitfaktor.
   Damit 0.6B oder 1.7B entscheiden (`model_size`, `model_choice` oder
   `repo_id` in der Clone-Vorlage). Ziel: 150 bis 300 Zeilen zwischen 05:00
   und 06:30, also Faktor unter etwa 1,5 bei 1.7B, sonst 0.6B.
8. Modell-Entladen ist in den Vorlagen aus (`unload_model_after_generate`,
   `unload_models`), sonst lädt jede Zeile das Modell neu.

Warum Design plus Clone: Voice Design liefert nicht bei jeder Zeile dieselbe
Stimme. Einmal designen, als Referenz speichern, alles per Clone rendern.

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
Verzeichnisschutz im Hosting-Panel. FTP-Zugang in `pc\night.json` eintragen
(`night.example.json` als Vorlage, `remote_dir` ist dieser Ordner). Test:

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
