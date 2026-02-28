@echo off
set GEMINI_API_KEY=AIzaSyDyfQ6ffvUvoGfwsvODV7RN_8tmqYP6kl8
cd /d C:\Users\amotrychenko\Desktop\CardRecognition
venv\Scripts\python.exe -m uvicorn src.api:app --host 0.0.0.0 --port 8000
