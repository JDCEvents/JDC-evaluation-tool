# JDC Evaluation Tool v3

- **Fester Orga-Link** (vollständig in der Sidebar, wenn `orga_pin` in Secrets gesetzt ist)
- **5 Jury-Links mit 4-stelligen PINs** (in der Sidebar, Namen + PINs)
- **Personalisierte Begrüßung**: „Hallo <Name>“
- **Startnummern** pro Crew (per Reihenfolge vergeben)
- **Rohdaten-Filter** nach Kids/Juniors/Adults + Sortierung (Startnummer, timestamp, TotalWeighted)
- **Eingaben sind Pflicht**; Punkte resetten bei Crew-Wechsel
- **Orga-Tab**: Juroren **bearbeiten** (Namen & PIN), Crews **hinzufügen/umbenennen/entfernen**

## Secrets (optional in Streamlit Cloud)
```toml
base_url = "https://deine-app.streamlit.app"
orga_pin = "1234"        # damit der Orga-Link in der Sidebar vollständig erscheint
[judge_pins]             # optional: überschreibt die Pins aus config.json
Fiona = "1111"
Cosmo = "2222"
Paul  = "3333"
Jason = "4444"
Ceyda = "5555"
```
