# Übergabe an die lokale Session

Stand 2026-09-05, mittags. Aus der Cloud gebaut: App komplett (Overlay,
Sendeplan, Sync, Artikel), PC-Pipeline gegen Mock-Server. Am PC seitdem
erledigt: Feeds, Stimmen (abgenommen), Webspace, echter Lauf mit Upload,
Aufgabe um 01:00 mit Shutdown, Live-Wetter in der App (Build 8). Offen:
Handy einrichten (Schritt 6), Musik nach `pc\music\`, Aufwachen um 01:00
(BIOS oder SwitchBot). Reihenfolge einhalten, jeder Schritt ist für sich prüfbar.

```
set PY=C:\Users\marco\Desktop\ComfyUI_windows_portable\python_embeded\python.exe
```

## 1. Feeds — erledigt (Commit 3bc9351)

`%PY% pc\feeds.py check` läuft grün, `fetch` liefert 30 Meldungen ohne Fehler.
Tot waren GameStar (Pfad korrigiert), itch.io, RPG Codex und RPGWatch (403,
auch mit Browser-Kennung), Kickstarter-Feeds ignorieren die Kategorie und
liefern Bücher. Indie kommt jetzt von RPGamer, Turn Based Lovers, Indie Games
Plus, Alpha Beta Gamer, IndieDB News, einem Reddit-Multi-Feed (Top des Tages)
und drei GitHub-Suchen (`type: github`, Trainer und Hacks werden gefiltert).
`parse_anthropic_news` liest Titel, Datum und Teaser aus den echten Elementen.

Merken: Reddit erlaubt nur eine Anfrage je Minute (`check` direkt vor `fetch`
schlägt dort fehl, im Nachtlauf egal), GitHub zehn je Minute (2 s Pause im
Code). Je Quelle gibt es `max` und `since_hours`, der Rubrik-Deckel geht reihum
über die Quellen. Nachjustieren nach ein paar Tagen Hören: Golem allgemein
bringt Uhren-Tests und Windparks, Hacker News bringt US-Politik.

## 2. Stimmen — läuft, Abnahme offen (Commit 89b977a)

Der installierte Node 1038lab/ComfyUI-QwenTTS rendert in diesem ComfyUI
nicht: sein `qwen_tts` braucht transformers 4.57, ComfyUI hat 5.9 (Krea 2,
WanVideo). Der Patch `qwen_tts_transformers5_patches.diff` lässt den Import
durch, die Generierung bricht dann in der Attention. Deshalb Backend `direct`
in `foxtts.py`: ein Arbeitsprozess in der ComfyUI-Python mit der isolierten
`qwen_tts_env` (transformers 4.57.3) davor, Modell bleibt geladen, Aufträge als
JSON-Zeilen. ComfyUI muss dafür nicht laufen.

- Stimmen in `pc\foxtts.json`: `A_design`/`B_design` (Voice Design, fester
  Seed) erzeugen die Referenzen `pc\voices\a_ref.wav` und `b_ref.wav`, `A`/`B`
  klonen daraus (`ref_text` exakt wie gesprochen, steht in
  `voices\ref_texte.txt`). A: sachlicher Mann, B: warme Frauenstimme (Marcos
  Beschreibung und Seed aus `qwen3_tts_speak.py`).
- Neue Stimme: Beschreibung unter `X_design`, dann
  `%PY% pc\foxtts.py line -v X_design -t "Text" -o pc\voices\x_ref.wav`,
  anhören, `X` als clone darauf zeigen lassen.
- Renderzeit: Faktor 1,4 bis 1,7 mit `attention: sdpa` (ohne sdpa 4 bis 5),
  gemessen mit 28 % Fremdlast durch den UE4-Editor. 80 Zeilen des Probelaufs
  in 431 s. Reserve, falls es nachts knapp wird: `generate_voice_clone` kann
  Listen, mehrere Zeilen derselben Stimme in einem Aufruf.
- Nur 1.7B-Modelle sind installiert (Base, CustomVoice, VoiceDesign). Die
  Frage 0.6B stellt sich erst, wenn 0.6B-Base geladen wird.
- Musikbett: Dateien in `pc\music\` (gitignored), eine wird je Block zufällig
  gewählt, -20 dB, Ein- und Ausblendung, 0,8 s Vorlauf, 1,5 s Nachlauf. Zurzeit
  liegt dort nur ein synthetischer `test_pad.wav`.
- Offen: Marco hört `pc\work\test.mp3` und sagt, ob A und B bleiben.

Das comfy-Backend mit exportierten Workflows bleibt im Code, Vorlagen in
`pc\voices\templates\`, für den Fall, dass der Node irgendwann läuft.

## 3. Texte — erledigt

`pc\writer.json` ist angelegt (Backend `claude-cli`, Login erneuert). Der
07:00-Block hatte 35 Zeilen und 7 Artikel in 125 s, Form und Fakten stimmten;
schwach war nur das Material, deshalb die skip-Muster in Schritt 1. Läuft
`claude -p` auf `401 OAuth access token has expired`: im Terminal `claude`
starten und `/login`. Aufruf:

```
%PY% pc\writer.py write --feeds pc\work\feeds.json --weather pc\work\weather.json --out pc\work\scripts --only 07:00
```

Skript lesen. Wenn der Dialog kippt (Floskeln, Erfundenes), Prompt in
`build_prompt` nachschärfen, nicht lockern. Mit `--backend fake` läuft die
Pipeline schon durch (geprüft). Alternative `api` braucht `pip install
anthropic` in der ComfyUI-Python und `ANTHROPIC_API_KEY`.

## 4. Webspace — erledigt (Commit 4e3578c)

`https://alchemy-fox.de/foxradio/` liegt an, `.htaccess` mit absolutem Pfad
`/home/www/Dokus/foxradio/.htpasswd`, Benutzer `marco`. Ohne Passwort 401,
mit Passwort 200. Zugang in `pc\night.json` unter `web_user`/`web_password`
(gitignored), das trägt Marco in die App ein.

Strato nimmt kein FTP und kein FTPS an, nur SSH. `night.py` lädt deshalb per
SFTP hoch (`method: sftp`, Host `5017972395.ssh.w2.strato.hosting`, nicht
`ssh.strato.de`). Dafür braucht die Python, mit der `night.bat` läuft,
paramiko: `%PY% -m pip install paramiko` — wartet auf Marcos OK. Getestet ist
der Upload mit der normalen Python 3.13, dort ist paramiko drin:
`upload-status` schreibt `status.json`, mit Passwort abrufbar.

## 5. Probelauf und erster echter Lauf — erledigt

`run --backend fake --no-upload --no-shutdown` ist durch: 10 Blöcke, 25
Artikel mit Nachhör-Offsets, 28 Bilder, `playlist.json`, `articles.json`,
`status.json` in `pc\work\2026-09-05\`. Der echte Lauf (`run --no-shutdown`)
ist ebenfalls durch: 10 Blöcke, 25 Artikel, 35 Minuten von Feeds bis Upload,
alles auf dem Webspace. Der Worker folgt seitdem Marcos Skill `qwen3-tts`
(Klon-Prompt je Stimme einmal, Token-Deckel, Längenprüfung mit Neuversuch,
satzweise): Testdialog Faktor 1,7 statt 5,0, keine verworfenen Stücke.

## 6. Handy — offen

In der App unter Verbindung Adresse `https://alchemy-fox.de/foxradio`,
Benutzer `marco` und das Passwort aus `night.json` eintragen, "Jetzt laden".
Die Heute-Karte muss den Tag zeigen, Artikel lesen, Nachhören probieren.
Sendeplan an. Am nächsten Arbeitstag um 07:00 mit laufender Musik testen.
Protokoll in der App zeigt, was der Wecker gemacht hat.

## 7. Automatik — eingerichtet

- Aufgabe "FoxRadio Nachtlauf" ist angelegt (PowerShell `Register-ScheduledTask`):
  täglich 01:00 (Marco ist um vier oft schon am PC), `pc\night.bat`, Benutzer
  marco, nur bei Anmeldung, "Computer aufwecken" an, Zeitlimit drei Stunden.
  ComfyUI wird nicht mehr gebraucht, nur die GPU.
- Wake-on-RTC im BIOS oder SwitchBot, damit der PC um 01:00 überhaupt an ist.
- `"shutdown": true` steht seit dem sauberen Lauf in `night.json` (120 s Vorlauf).
- Optional `"ntfy_topic"` setzen und die ntfy-App am Handy abonnieren.

## Offen und Annahmen

- Wetter: kein Wetter mehr in den Skripten. Die App holt es vor jedem Block
  von Open-Meteo und spricht es mit der Android-Stimme (Schalter "Live-Wetter",
  `Weather.kt`); ohne Netz gilt der letzte Stand bis drei Stunden, sonst entfällt es.
- Sendetage Mo bis Fr, in der App umschaltbar. Der Nachtlauf läuft jeden
  Tag, an dem die Aufgabe feuert.
- Feed-Auswahl und Rubrik-Zuteilung in `writer.plan_blocks` sind ein
  Startpunkt und sollen nach ein paar Tagen Hören nachjustiert werden.
- Bilder kommen aus og:image der Artikel, keine Rechteprüfung, nur für dich.
- Die Cloud-Session hat parallel auf denselben Branch gepusht (Vorlagen,
  Webspace-Helfer); beides ist drin. Nicht zwei Sessions gleichzeitig auf
  dem Branch arbeiten lassen.
