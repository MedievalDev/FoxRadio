#!/usr/bin/env python3
"""Erzeugt eine .htpasswd-Zeile (bcrypt, von Apache 2.4 unterstuetzt).

    python make_htpasswd.py marco > .htpasswd

Braucht 'pip install bcrypt'. Alternativ die Verzeichnisschutz-Funktion im
Hosting-Panel benutzen, die legt .htaccess und .htpasswd selbst an.
"""
import getpass
import sys

try:
    import bcrypt
except ImportError:
    sys.exit("pip install bcrypt")

user = sys.argv[1] if len(sys.argv) > 1 else input("Benutzer: ")
pw = getpass.getpass("Passwort: ")
print(f"{user}:{bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()}")
