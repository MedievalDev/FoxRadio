#!/usr/bin/env python3
"""Schneidet ein Stueck aus einer Audiodatei und legt es als Jingle ab.

    python schneide_jingle.py quelle.mp3 jingles/news.wav 12.4 3.0
                              Quelle     Ziel            ab s  Dauer s

Blendet 80 ms ein und 250 ms aus, damit es nicht knackt, und normalisiert
auf -1 dB. Braucht die ComfyUI-Python (PyAV und numpy).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import foxtts  # noqa: E402


def main(argv):
    if len(argv) < 4:
        sys.exit(__doc__)
    quelle, ziel, ab = argv[0], argv[1], float(argv[2])
    dauer = float(argv[3]) if len(argv) > 3 else 3.0
    import numpy as np
    cfg = foxtts.load_config()
    sr = cfg["sample_rate"]
    audio = foxtts.decode_audio(quelle, sr)
    a, b = int(ab * sr), int((ab + dauer) * sr)
    if a >= len(audio):
        sys.exit(f"{quelle} ist nur {len(audio) / sr:.1f}s lang")
    stueck = audio[a:min(b, len(audio))].astype(np.float32)
    ein, aus = int(0.08 * sr), int(0.25 * sr)
    if len(stueck) > ein + aus:
        stueck[:ein] *= np.linspace(0.0, 1.0, ein)
        stueck[-aus:] *= np.linspace(1.0, 0.0, aus)
    ziel = foxtts.resolve_path(ziel)
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    foxtts.write_audio(ziel, foxtts.normalize(stueck.astype(np.int16)), sr, cfg["mp3_bitrate"])
    print(f"{ziel}: {len(stueck) / sr:.2f}s aus {quelle} ab {ab:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
