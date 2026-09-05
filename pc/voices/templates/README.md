# Workflow-Vorlagen (API-Format)

Für die drei gängigen Qwen3-TTS-Node-Pakete, Namen und Eingänge aus dem
Quellcode der Pakete (Stand 2026-09-05). Welches Paket installiert ist, steht
in ComfyUI unter Custom Nodes. Vorlagen mit dem passenden Präfix nehmen:

| Präfix | Paket | Design-Node | Clone-Node |
|---|---|---|---|
| `dario_` | DarioFT/ComfyUI-Qwen3-TTS | `Qwen3Loader` + `Qwen3VoiceDesign` | `Qwen3Loader` (Base) + `Qwen3VoiceClone` |
| `fly_` | flybirdxx/ComfyUI-Qwen-TTS | `FB_Qwen3TTSVoiceDesign` | `FB_Qwen3TTSVoiceClone` |
| `ailab_` | 1038lab/ComfyUI-QwenTTS | `AILab_Qwen3TTSVoiceDesign` | `AILab_Qwen3TTSVoiceClone` |

Warum zwei Schritte: Voice Design erzeugt aus einer Beschreibung eine Stimme,
aber nicht garantiert dieselbe bei jeder Zeile. Deshalb einmal designen, das
Ergebnis als Referenz speichern, und alle Zeilen per Voice Clone mit dieser
Referenz rendern. So bleibt die Stimme über 300 Zeilen stabil.

Ablauf pro Stimme (Beispiel A mit dem DarioFT-Paket):

1. `instruct` in `dario_design.json` anpassen. Vorschläge stehen drin:
   A sachlich, klar; B lockerer, wärmer. Annahme: beides Männerstimmen, frei
   änderbar.
2. Referenz erzeugen, landet direkt im ComfyUI-Eingangsordner:
   `python pc\foxtts.py voice-design pc\voices\templates\dario_design.json -o C:\...\ComfyUI_windows_portable\ComfyUI\input\ref_a.wav`
   Anhören. Gefällt sie nicht: Beschreibung oder `seed` ändern, wiederholen.
3. `dario_clone.json` nach `pc\voices\a.json` kopieren, darin `ref_text` auf
   den Satz setzen, den `voice-design` gesprochen hat (steht in der Ausgabe),
   `audio` in `LoadAudio` heißt `ref_a.wav`.
4. Für B dasselbe mit `ref_b.wav` und `pc\voices\b.json`.
5. `python pc\foxtts.py probe pc\voices\a.json`, dann der Testdialog.

`SaveAudio` (FLAC) ist in ComfyUI als veraltet markiert, funktioniert aber.
Ersatz wäre `SaveAudioAdvanced` mit `format`.
