# JDC Evaluation Tool

Bereit für **Streamlit Community Cloud**. Repo-Name: **JDC-evaluation-tool** (wie gewünscht).

## Start (lokal)
```bash
pip install -r requirements.txt
python3 -m streamlit run app.py
```

## Online (Streamlit Cloud)
1. GitHub öffnen → Repo **JDC-evaluation-tool** → Upload: `app.py`, `requirements.txt`, `README.md`, `juror_offline.html`, `config.json`
2. share.streamlit.io → **New app** → Repo: *JDC-evaluation-tool*, Branch: *main*, App file: **app.py**
3. Deploy → du erhältst eine URL wie `https://deinname-jdc-evaluation-tool.streamlit.app`
4. Juroren-Links: `...?judge=J1` etc. Orga: `...?orga=1`

## Offline-Formular (Fallback)
- Datei `juror_offline.html` lokal öffnen → Bewertungen offline speichern → CSV exportieren
- In der Online-App: Tab **Daten & Export** → **Offline-Import (CSV)**

