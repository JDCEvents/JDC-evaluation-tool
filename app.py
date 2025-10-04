# app.py (JDC evaluation tool v3)
# --------------------------------------------------------------------
# WOFÜR IST DIESE DATEI?
# - Dies ist die HAUPTDATEI deiner Streamlit-App.
# - Hier steckt die komplette UI, Logik, Validierung und das Zusammenspiel
#   zwischen Frontend (Formulare/Tabs) und dem lokalen CSV-Speicher.
# - Design-/Textänderungen nimmst du i.d.R. HIER vor (nicht in config.json).
# --------------------------------------------------------------------

import streamlit as st
import pandas as pd
import datetime as dt
from typing import List, Dict, Optional
import pathlib, json

# --------------------------------------------------------------------
# BASIS-URL FÜR LINKS IN DER SIDEBAR
# - Wird in der Sidebar genutzt, um komplette Orga-/Jury-Links anzuzeigen.
# - Setz das in Streamlit "Secrets" (Settings → Secrets) als "base_url",
#   dann verschwindet der Platzhalter <YOUR-APP>.
# --------------------------------------------------------------------
BASE_URL = st.secrets.get("base_url", "https://<YOUR-APP>.streamlit.app")

# --------------------------------------------------------------------
# WERTUNGSKATEGORIEN & GEWICHTUNG
# - CATEGORIES: Reihenfolge/Labels der 5 Kategorien
# - DOUBLE_CATS: Welche Kategorien zählen doppelt (x2) für die Gesamtpunkte
#   → Max 70 Punkte (2 doppelt, 3 einfach)
# --------------------------------------------------------------------
CATEGORIES = ["Synchronität","Schwierigkeit der Choreographie","Choreographie","Bilder und Linien","Ausdruck und Bühnenpräsenz"]
DOUBLE_CATS = ["Synchronität","Schwierigkeit der Choreographie"]

# --------------------------------------------------------------------
# CONFIG-MANAGER
# - Verantwortlich für: Alterskategorien, Crews, Startnummern, Juroren.
# - Daten werden in "config.json" gespeichert (persistente Inhalte).
# - Hier veränderst du z. B. das Datenmodell (nicht nötig für Styling).
# --------------------------------------------------------------------
class ConfigManager:
    def __init__(self, path="config.json"):
        self.path = pathlib.Path(path)
        self.data = {
            "age_groups": [],
            "crews_by_age": {},
            "start_numbers": {},
            "jurors": []  # list of {"name":..., "pin":...}
        }
        self.load()
        self.ensure_start_numbers()

    def load(self):
        # config.json einlesen (falls vorhanden)
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                pass

    def save(self):
        # config.json speichern
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False,_
