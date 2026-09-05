Stimmen fuer das direct-Backend (Standard):

- `a_ref.wav`, `b_ref.wav`: Referenzaufnahmen, einmal per Voice Design erzeugt
  (`foxtts.py line -v A_design -t "Text" -o voices/a_ref.wav`). Nicht im Repo.
- `ref_texte.txt`: die gesprochenen Texte der Referenzen, exakt so auch als
  `ref_text` in `foxtts.json` eintragen. Die Produktionsstimmen A und B klonen
  aus diesen Dateien, damit die Stimme ueber hunderte Zeilen gleich bleibt.

Neue Stimme: Beschreibung und Seed unter `X_design` in `foxtts.json`, Referenz
rendern, anhoeren, dann `X` als clone darauf zeigen lassen.

Nur fuer das comfy-Backend: hier laegen die Workflows pro Stimme (`a.json`,
`b.json`), exportiert aus ComfyUI ueber "Save (API Format)". Pruefen mit
`python foxtts.py probe voices/a.json`.
