@echo off
rem FoxRadio Nachtlauf. In der Windows-Aufgabenplanung um 05:00 eintragen
rem ("Computer aufwecken, um diese Aufgabe auszufuehren" anhaken).
set PY=C:\Users\marco\Desktop\ComfyUI_windows_portable\python_embeded\python.exe
cd /d %~dp0
if not exist work mkdir work
"%PY%" night.py run >> work\night.log 2>&1
