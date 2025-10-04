# app.py (JDC evaluation tool v3 – robuste Links + Keyboard-Input)
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
#   (Du hast das schon: base_url = "https://deine-app.streamlit.app")
# --------------------------------------------------------------------
BASE_URL = st.secrets.get("base_url", "https://<YOUR-APP>.streamlit.app")

# --------------------------------------------------------------------
# WERTUNGSKATEGORIEN & GEWICHTUNG
# - CATEGORIES: Reihenfolge/Labels der 5 Kategorien
# - DOUBLE_CATS: Welche Kategorien zählen doppelt (x2) für die Gesamtpunkte
#   → Max 70 Punkte (2 doppelt, 3 einfach)
# --------------------------------------------------------------------
CATEGORIES = [
    "Synchronität",
    "Schwierigkeit der Choreographie",
    "Choreographie",
    "Bilder und Linien",
    "Ausdruck und Bühnenpräsenz",
]
DOUBLE_CATS = ["Synchronität", "Schwierigkeit der Choreographie"]

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
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # ----- age groups & crews -----
    def get_age_groups(self) -> List[str]:
        # Liste aller Alterskategorien (z. B. Kids/Juniors/Adults)
        return list(self.data.get("age_groups", []))

    def get_crews(self, age_group: str) -> List[str]:
        # Crew-Liste einer Alterskategorie
        return list(self.data.get("crews_by_age", {}).get(age_group, []))

    def ensure_start_numbers(self):
        # Startnummern pro Alterskategorie sicherstellen
        # - Vergibt Startnummern in Reihenfolge der Crews (1..n)
        # - Entfernt verwaiste Einträge
        sn = self.data.setdefault("start_numbers", {})
        for ag in self.get_age_groups():
            crews = self.get_crews(ag)
            m = sn.setdefault(ag, {})
            # assign in order if missing
            for i, crew in enumerate(crews, start=1):
                m.setdefault(crew, i)
            # remove stale
            for k in list(m.keys()):
                if k not in crews:
                    del m[k]
        self.save()

    def get_start_no(self, age_group: str, crew: str) -> Optional[int]:
        # Startnummer einer Crew (None, wenn unbekannt)
        return self.data.get("start_numbers", {}).get(age_group, {}).get(crew)

    def set_age_groups(self, groups: List[str]):
        # Alterskategorien setzen (und interne Strukturen konsistent halten)
        self.data["age_groups"] = groups
        cba = self.data.setdefault("crews_by_age", {})
        for g in groups:
            cba.setdefault(g, [])
        for g in list(cba.keys()):
            if g not in groups:
                del cba[g]
        self.ensure_start_numbers()

    def add_crew(self, age_group: str, crew: str):
        # Crew hinzufügen (Startnummern werden danach gesichert)
        cba = self.data.setdefault("crews_by_age", {})
        lst = cba.setdefault(age_group, [])
        if crew and crew not in lst:
            lst.append(crew)
            self.ensure_start_numbers()

    def remove_crew(self, age_group: str, crew: str):
        # Crew entfernen (Startnummern werden danach gesichert)
        cba = self.data.setdefault("crews_by_age", {})
        lst = cba.setdefault(age_group, [])
        if crew in lst:
            lst.remove(crew)
            self.ensure_start_numbers()

    def rename_crew(self, age_group: str, old: str, new: str):
        # Crew umbenennen (Startnummer bleibt erhalten)
        if not new or old == new:
            return
        crews = self.data.setdefault("crews_by_age", {}).setdefault(age_group, [])
        if old in crews and new not in crews:
            idx = crews.index(old)
            crews[idx] = new
            # preserve start number mapping
            sn = self.data.setdefault("start_numbers", {}).setdefault(age_group, {})
            sn[new] = sn.get(old, sn.get(new, None)) or (idx + 1)
            if old in sn:
                del sn[old]
            self.save()

    # ----- jurors -----
    def get_jurors(self) -> List[Dict]:
        # Liste aller Juroren inkl. PINs
        return list(self.data.get("jurors", []))

    def set_jurors(self, jurors: List[Dict]):
        # Jurorenliste setzen (normalisiert, ohne Duplikate nach Name)
        clean = []
        seen = set()
        for j in jurors:
            name = (j.get("name") or "").strip()
            pin = str(j.get("pin") or "").strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                clean.append({"name": name, "pin": pin})
        self.data["jurors"] = clean
        self.save()

# Globale Config-Instanz
cfg = ConfigManager("config.json")

# --------------------------------------------------------------------
# PINS-LADELOGIK
# - Reihenfolge: Secrets (judge_pins) überschreiben config.json
# - Ergebnis: Mapping JUDGE_PINS {Name -> PIN}, JUDGES (Namen-Liste)
# - ORGA_PIN: optional aus Secrets (orga_pin)
# --------------------------------------------------------------------
def load_judge_pins_from_config():
    pins = {}
    for j in cfg.get_jurors():
        if j.get("name") and j.get("pin"):
            pins[j["name"]] = j["pin"]
    return pins

JUDGE_PINS = load_judge_pins_from_config()
if "judge_pins" in st.secrets:
    try:
        sec = dict(st.secrets["judge_pins"])
        # override by secrets
        JUDGE_PINS.update(sec)
    except Exception:
        pass
JUDGES = list(JUDGE_PINS.keys())

ORGA_PIN = st.secrets.get("orga_pin", "") or ""  # optionaler Orga-PIN via Secrets

# --------------------------------------------------------------------
# CSV-BACKEND
# - Lokaler CSV-Speicher "data.csv" für alle Votes.
# - upsert_row: identifiziert Einträge über (round, age_group, crew, judge)
# - _compute_weighted: berechnet Gesamtpunkte inkl. doppelter Kategorien
# --------------------------------------------------------------------
class CSVBackend:
    def __init__(self, path: str = "data.csv"):
        self.path = path
        if not pathlib.Path(self.path).exists():
            df = pd.DataFrame(
                columns=["timestamp", "round", "age_group", "crew", "judge", *CATEGORIES, "TotalWeighted"]
            )
            df.to_csv(self.path, index=False)

    def load(self) -> pd.DataFrame:
        # CSV laden, Spalten sicherstellen
        try:
            df = pd.read_csv(self.path)
            if "TotalWeighted" not in df.columns:
                df["TotalWeighted"] = 0
            if "age_group" not in df.columns:
                df["age_group"] = ""
            return df
        except Exception:
            return pd.DataFrame(
                columns=["timestamp", "round", "age_group", "crew", "judge", *CATEGORIES, "TotalWeighted"]
            )

    def _compute_weighted(self, row: Dict) -> int:
        # Gesamtpunkte mit Gewichtung (x2 für DOUBLE_CATS)
        return int(sum((row.get(c, 0) or 0) * (2 if c in DOUBLE_CATS else 1) for c in CATEGORIES))

    def upsert_row(self, key_cols: List[str], row: Dict):
        # Entweder vorhandene Zeile (nach key_cols) aktualisieren oder neue Zeile anhängen
        row = dict(row)
        row["TotalWeighted"] = self._compute_weighted(row)
        df = self.load()
        if df.empty:
            df = pd.DataFrame([row])
        else:
            mask = pd.Series([True] * len(df))
            for k in key_cols:
                mask = mask & (df[k] == row[k])
            if mask.any():
                idx = mask[mask].index[0]
                for k, v in row.items():
                    df.at[idx, k] = v
            else:
                df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        df.to_csv(self.path, index=False)

# Eine Backend-Instanz für die App
backend = CSVBackend("data.csv")

# --------------------------------------------------------------------
# LEADERBOARD-BERECHNUNG
# - Aggregiert pro Crew über alle Juroren.
# - Sortiert mit Tiebreakern (Tens, DoubleCatSum, MedianJudge, MaxJudge).
# --------------------------------------------------------------------
def compute_leaderboard(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Rank", "Crew", "Judges", "Total", "Tens", "DoubleCatSum", "MedianJudge", "MaxJudge"])
    for c in CATEGORIES:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    df["JudgeTotal"] = sum(df[c] * (2 if c in DOUBLE_CATS else 1) for c in CATEGORIES)
    df["TensHere"] = df.apply(lambda r: sum(1 for c in CATEGORIES if r[c] == 10), axis=1)
    df["DoubleHere"] = df.apply(lambda r: sum(r[c] for c in DOUBLE_CATS), axis=1)
    agg = (
        df.groupby("crew", as_index=False)
        .agg(
            Judges=("JudgeTotal", "count"),
            Total=("JudgeTotal", "sum"),
            Tens=("TensHere", "sum"),
            DoubleCatSum=("DoubleHere", "sum"),
            MedianJudge=("JudgeTotal", "median"),
            MaxJudge=("JudgeTotal", "max"),
        )
        .rename(columns={"crew": "Crew"})
    )
    agg = agg.sort_values(
        by=["Total", "Tens", "DoubleCatSum", "MedianJudge", "MaxJudge", "Crew"],
        ascending=[False, False, False, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    agg.insert(0, "Rank", agg.index + 1)
    return agg

# --------------------------------------------------------------------
# QUERY-PARAM-HELPER (WICHTIG!)
# - _qp_get macht die App robust gegenüber Streamlit-Versionen:
#   Manche Versionen liefern Strings, andere Listen bei st.query_params.
# - So verhindern wir den Bug, dass nur der erste Buchstabe gelesen wird.
# --------------------------------------------------------------------
def _qp_get(name: str):
    """Holt einen Query-Parameter robust (unterstützt String oder Liste)."""
    val = st.query_params.get(name)
    if isinstance(val, list):
        return val[0]
    return val

# --------------------------------------------------------------------
# AUTH / PARAMETER-LOCKS
# - get_locked_judge: Prüft judge+pin aus URL (?judge=NAME&pin=XXXX).
#   → Gibt den Jurorennamen zurück, falls PIN korrekt; sonst Fehlermeldung.
# - is_orga_mode: Prüft Orga-Modus (?orga=1&orgapin=XXXX), vergleicht Secrets.
# --------------------------------------------------------------------
def get_locked_judge() -> Optional[str]:
    j = (_qp_get("judge") or "").strip()
    pin = (_qp_get("pin") or "").strip()
    if not j:
        return None
    expected = str(JUDGE_PINS.get(j, "")).strip()
    if not expected or pin != expected:
        st.error("Falscher oder fehlender PIN für diesen Juror.")
        return None
    return j

def is_orga_mode() -> bool:
    val = (_qp_get("orga") or "").strip()
    pin = (_qp_get("orgapin") or "").strip()
    if val not in ("1", "true", "True"):
        return False
    # Secrets-PIN hat Vorrang; wenn leer, jede nicht-leere Eingabe akzeptieren (optional)
    orga_pin_config = st.secrets.get("orga_pin", "")
    return (pin == orga_pin_config) if orga_pin_config else bool(pin)

# --------------------------------------------------------------------
# UI-HILFE
# - reset_vote_state: Setzt alle Kategorien auf leer "" (statt '—').
#   → Wird beim Crew-Wechsel genutzt, damit nichts „hängen bleibt“.
# --------------------------------------------------------------------
def reset_vote_state():
    # Setzt alle Kategorie-Felder auf leer (""), damit man per Tab durchspringen kann
    for c in CATEGORIES:
        st.session_state[f"cat_{c}"] = ""

# --------------------------------------------------------------------
# SEITENKONFIG & HEADER
# - page_title/page_icon/layout: Oberflächen-Einstellungen
# - HIER kannst du Branding (Titel/Icon) anpassen.
# --------------------------------------------------------------------
st.set_page_config(page_title="JDC Scoring 2026", page_icon="🧮", layout="wide")
st.title("🧮 JDC Scoring 2026")

# --------------------------------------------------------------------
# PERSÖNLICHE BEGRÜSSUNG FÜR JUROR-ANSICHT
# - Wenn Link korrekt ist (judge+pin), wird hier der Name gezeigt.
# --------------------------------------------------------------------
locked_judge = get_locked_judge()
if locked_judge:
    st.success(f"Hallo {locked_judge} 👋 – schön dich bei uns zu haben!")
else:
    st.info("Tipp: Verwende personalisierte Links: ?judge=Name&pin=XXXX.")

# --------------------------------------------------------------------
# SIDEBAR: REGLEN & LINKS
# - finalists_n: wie viele direkt ins Finale
# - Expander: Vollständige Orga-/Jury-Links (nutzt BASE_URL + Pins)
# --------------------------------------------------------------------
st.sidebar.header("Setup / Regeln")
finalists_n = st.sidebar.selectbox("Direkt ins Finale (Top N)", [5, 6, 7], index=0)

with st.sidebar.expander("Links (vollständige URLs)"):
    # Orga-Link (nur wenn orga_pin in Secrets gesetzt ist)
    orga_pin = st.secrets.get("orga_pin", "")
    if orga_pin:
        st.write("Orga:")
        st.code(f"{BASE_URL}/?orga=1&orgapin={orga_pin}")
    st.write("Jury:")
    for name, pin in JUDGE_PINS.items():
        st.code(f"{BASE_URL}/?judge={name}&pin={pin}")

# Aktuelle Alterskategorien (aus config.json)
age_groups = cfg.get_age_groups()

# --------------------------------------------------------------------
# TABS (Navigations-Reiter)
# - 0: Bewerten (für Juroren)
# - 1: Leaderboard (Aggregiert)
# - 2: Daten & Export (Rohdaten, Filter, Sortierung, Download)
# - 3: Orga (Verwaltung Juroren/Crews + Notfall-Bewertungen)
# --------------------------------------------------------------------
tabs = st.tabs(["Bewerten", "Leaderboard", "Daten & Export", "Orga"])

# ---------- TAB 0: BEWERTEN (Juroren-Frontend) ----------
with tabs[0]:
    st.subheader("Bewertung abgeben")

    # --- Kopfzeile: Auswahl Alterskategorie / Crew / Runde ---
    col0, col1, col2 = st.columns([1, 1, 1])
    with col0:
        # Alterskategorie wählen (Dropdown aus config.json)
        age_group = st.selectbox("Alterskategorie", age_groups, index=0 if age_groups else None, key="age_group_sel")
    with col1:
        # Crew-Liste dynamisch pro Alterskategorie
        crews_for_age = cfg.get_crews(age_group) if age_group else []
        crew = st.selectbox("Crew", crews_for_age, index=0 if crews_for_age else None, key="crew_sel")
    with col2:
        # Runde: 1 (Hauptrunde) oder ZW (Zwischenrunde)
        round_choice = st.radio("Runde", ["1", "ZW"], horizontal=True, key="round_sel")

    # --- Reset der Kategorien, wenn die Crew gewechselt wird ---
    if "last_crew" not in st.session_state:
        st.session_state["last_crew"] = ""
    if crew != st.session_state["last_crew"]:
        reset_vote_state()
        st.session_state["last_crew"] = crew

    # --- Kategorien-Eingabe (nur Tastatur, leere Felder erlaubt) ---
    # - Textfelder, damit per Tastatur + Tab schnell eingegeben werden kann
    # - Leere Felder initial; Speichern erst, wenn alle 1–10 sind
    st.markdown("### Kategorien (bitte jede Kategorie als Zahl 1–10 eingeben)")
    values_raw = {}
    values_int = {}
    invalid_fields = []

    def _parse_score(s: str):
        s = (s or "").strip()
        if not s:
            return None
        if not s.isdigit():
            return None
        v = int(s)
        return v if 1 <= v <= 10 else None

    for c in CATEGORIES:
        key = f"cat_{c}"
        # Initial leer setzen, wenn noch nicht vorhanden
        if key not in st.session_state:
            st.session_state[key] = ""
        # Textfeld (freie Tastatur-Eingabe), mit Platzhalter
        values_raw[c] = st.text_input(
            label=c,
            value=st.session_state[key],
            key=key,
            placeholder="1–10"
        )
        parsed = _parse_score(values_raw[c])
        values_int[c] = parsed
        if parsed is None:
            invalid_fields.append(c)

    # Hinweis, falls etwas fehlt/ungültig ist
    if invalid_fields:
        st.info("Bitte alle Kategorien mit Ziffern **1–10** ausfüllen. Offen/ungültig: " + ", ".join(invalid_fields))

    # --- Validierung & Speichern ---
    # - Button nur aktiv, wenn:
    #   * Juror via Link korrekt eingeloggt (locked_judge)
    #   * Crew/Alterskategorie gewählt
    #   * alle Kategorien 1–10 (nicht leer)
    if not locked_judge:
        st.warning("Bitte öffne deinen persönlichen Link (mit PIN).")

    all_set = (
        locked_judge is not None
        and crew
        and age_group
        and all(values_int[c] is not None for c in CATEGORIES)
    )

    if st.button("Speichern / Aktualisieren", type="primary", disabled=not all_set):
        # Vote-Zeile bauen
        row = {
            "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
            "round": round_choice,
            "age_group": age_group,
            "crew": crew,
            "judge": locked_judge,
        }
        for c in CATEGORIES:
            row[c] = int(values_int[c])
        backend.upsert_row(["round", "age_group", "crew", "judge"], row)
        st.success(
            f"Bewertung gespeichert: {crew} (Startnr. {cfg.get_start_no(age_group, crew)}), "
            f"{age_group}, Runde {round_choice}, Juror {locked_judge}."
        )
        # Nach Speichern alles zurücksetzen, damit nichts „hängen bleibt“
        reset_vote_state()

# ---------- TAB 1: LEADERBOARD (Aggregierte Sicht) ----------
with tabs[1]:
    st.subheader("Leaderboard")
    df_all = backend.load()

    # Filter: Runde & Alterskategorie
    colf1, colf2 = st.columns([1, 2])
    with colf1:
        round_view = st.radio("Runde", ["1", "ZW"], horizontal=True, key="round_view")
        age_opts = age_groups
        age_view = st.selectbox("Alterskategorie", age_opts, index=0 if age_opts else None, key="age_view")

    # Daten subsetten
    if not df_all.empty and age_view:
        df_view = df_all[(df_all["round"] == round_view) & (df_all["age_group"] == age_view)].copy()
    else:
        df_view = pd.DataFrame()

    # Startnummer ergänzen (für Anzeige / Orientierung)
    if not df_view.empty:
        df_view["Startnummer"] = df_view["crew"].map(lambda x: cfg.get_start_no(age_view, x))

    # Tabelle berechnen & ausgeben
    board = compute_leaderboard(df_view.copy())
    st.dataframe(board, use_container_width=True)

    # Zusatzausgabe: Finalisten + Zwischenrunde
    if round_view == "1" and not board.empty:
        finalists = board.head(finalists_n)
        rest = board.iloc[finalists_n:]
        st.markdown(f"**Direkt im Finale (Top {finalists_n}) – {age_view}**")
        st.dataframe(finalists[["Rank", "Crew", "Total", "Judges"]], use_container_width=True)
        if not rest.empty:
            st.markdown(f"**Zwischenrunde ({age_view})**")
            st.dataframe(rest[["Rank", "Crew", "Total", "Judges"]], use_container_width=True)
    if round_view == "ZW" and not board.empty:
        winner = board.iloc[0]
        st.markdown(f"🏆 **Sieger Zwischenrunde ({age_view})**: **{winner['Crew']}** (Total {int(winner['Total'])}) → **Finale**")

# ---------- TAB 2: DATEN & EXPORT (Rohdaten + Filter/Sort) ----------
with tabs[2]:
    st.subheader("Daten & Export")
    df_all = backend.load()

    # Filter & Sortierung der Rohdaten
    if not df_all.empty:
        # Alterskategorie-Filter (Alle/Kids/Juniors/Adults …)
        age_filter = st.selectbox("Alterskategorie filtern", ["Alle"] + age_groups, index=0, key="raw_age_filter")
        if age_filter != "Alle":
            df_all = df_all[df_all["age_group"] == age_filter]
        # Startnummer ergänzen (für Sortierung)
        df_all["Startnummer"] = df_all.apply(lambda r: cfg.get_start_no(r["age_group"], r["crew"]), axis=1)
        # Sortierfeld wählen: Startnummer / timestamp / TotalWeighted
        sort_by = st.selectbox("Sortieren nach", ["Startnummer", "timestamp", "TotalWeighted"], index=0, key="raw_sort_by")
        ascending = st.checkbox("Aufsteigend sortieren", value=True)
        df_all = df_all.sort_values(by=sort_by, ascending=ascending, kind="mergesort")

    # Rohdaten-Tabelle rendern
    st.dataframe(df_all, use_container_width=True)

    # CSV-Export aller (gefilterten/sortierten) Daten
    csv_bytes = df_all.to_csv(index=False).encode("utf-8")
    st.download_button("CSV herunterladen", data=csv_bytes, file_name="scores_export.csv", mime="text/csv")

# ---------- TAB 3: ORGA (Verwaltung + Notfall-Bewertung) ----------
with tabs[3]:
    st.subheader("Orga")

    # Orga-Schutz: ?orga=1&orgapin=XXXX (XXXX = Secrets orga_pin)
    def is_orga_mode_local() -> bool:
        val = (_qp_get("orga") or "").strip()
        pin = (_qp_get("orgapin") or "").strip()
        orga_pin_secret = st.secrets.get("orga_pin", "")
        if val not in ("1", "true", "True"):
            return False
        return (pin == orga_pin_secret) if orga_pin_secret else bool(pin)

    if not is_orga_mode_local():
        # Hinweistext, wie man den Orga-Modus aktiviert
        st.info("Orga-Modus aktivieren: URL mit `?orga=1&orgapin=XXXX`.")
    else:
        st.success("Orga-Modus aktiv.")

        # ---- Juroren verwalten (Namen + PINs) ----
        # - Hier kannst du Juroren hinzufügen, umbenennen, löschen.
        # - Änderungen werden in config.json gespeichert.
        st.markdown("### Juroren verwalten (Namen & PINs)")
        jur_df = pd.DataFrame(cfg.get_jurors())
        if jur_df.empty:
            st.warning("Noch keine Juroren in der Config. Füge neue hinzu.")
        st.dataframe(jur_df, use_container_width=True)

        # Juror hinzufügen
        with st.form("add_juror"):
            colj1, colj2 = st.columns([2, 1])
            with colj1:
                new_jname = st.text_input("Name")
            with colj2:
                new_jpin = st.text_input("PIN (4-stellig)", max_chars=4)
            submitted = st.form_submit_button("+ Juror hinzufügen")
            if submitted and new_jname.strip() and new_jpin.strip():
                new_list = cfg.get_jurors() + [{"name": new_jname.strip(), "pin": new_jpin.strip()}]
                cfg.set_jurors(new_list)
                st.success("Juror hinzugefügt. Seite neu laden.")

        # Juror umbenennen
        if not jur_df.empty:
            with st.form("rename_juror"):
                rcol1, rcol2, _ = st.columns([2, 2, 1])
                with rcol1:
                    old_j = st.selectbox("Juror auswählen", jur_df["name"].tolist())
                with rcol2:
                    new_j = st.text_input("Neuer Name")
                submitted = st.form_submit_button("Umbenennen")
                if submitted and old_j and new_j.strip():
                    updated = []
                    for j in cfg.get_jurors():
                        if j["name"] == old_j:
                            updated.append({"name": new_j.strip(), "pin": j["pin"]})
                        else:
                            updated.append(j)
                    cfg.set_jurors(updated)
                    st.success("Juror umbenannt. Seite neu laden.")

        # Juror entfernen
        if not jur_df.empty:
            with st.form("remove_juror"):
                dcol1, _ = st.columns([3, 1])
                with dcol1:
                    del_j = st.selectbox("Juror entfernen", ["—"] + jur_df["name"].tolist())
                submitted = st.form_submit_button("Entfernen")
                if submitted and del_j != "—":
                    updated = [j for j in cfg.get_jurors() if j["name"] != del_j]
                    cfg.set_jurors(updated)
                    st.success("Juror entfernt. Seite neu laden.")

        st.markdown("---")
        # ---- Alterskategorien & Crews ----
        # - Alterskategorien als CSV-Liste bearbeiten
        # - Crews je Kategorie anzeigen, hinzufügen, umbenennen, entfernen
        # - Startnummern bleiben konsistent
        st.markdown("### Alterskategorien & Crews verwalten")
        groups_str = ",".join(cfg.get_age_groups())
        new_groups = st.text_input("Alterskategorien (kommagetrennt)", groups_str)
        if st.button("Speichern (Kategorien)"):
            groups = [g.strip() for g in new_groups.split(",") if g.strip()]
            if groups:
                cfg.set_age_groups(groups)
                st.success("Alterskategorien gespeichert – Seite neu laden.")

        ag = st.selectbox("Alterskategorie auswählen", cfg.get_age_groups(), key="orga_ag")
        if ag:
            current = cfg.get_crews(ag)
            df_crews = (
                pd.DataFrame({"Startnummer": [cfg.get_start_no(ag, c) for c in current], "Crew": current})
                .sort_values("Startnummer")
            )
            st.dataframe(df_crews, use_container_width=True)

            # Crew hinzufügen
            new_crew = st.text_input("Neue Crew hinzufügen", "", key="orga_newcrew")
            if st.button("+ Hinzufügen", disabled=not new_crew.strip()):
                cfg.add_crew(ag, new_crew.strip())
                st.success(f"Crew '{new_crew.strip()}' hinzugefügt. Seite neu laden.")

            # Crew umbenennen
            if current:
                with st.form("rename_crew"):
                    rc1, rc2 = st.columns([2, 2])
                    with rc1:
                        oldc = st.selectbox("Crew umbenennen", current)
                    with rc2:
                        newc = st.text_input("Neuer Name")
                    submitted = st.form_submit_button("Umbenennen")
                    if submitted and oldc and newc.strip():
                        cfg.rename_crew(ag, oldc, newc.strip())
                        st.success("Crew umbenannt. Seite neu laden.")

            # Crew entfernen
            if current:
                with st.form("remove_crew"):
                    dc1, _ = st.columns([3, 1])
                    with dc1:
                        delc = st.selectbox("Crew entfernen", ["—"] + current)
                    submitted = st.form_submit_button("Entfernen")
                    if submitted and delc != "—":
                        cfg.remove_crew(ag, delc)
                        st.success("Crew entfernt. Seite neu laden.")

        st.markdown("---")
        # ---- Orga-Backup-Bewertung ----
        # - Identisch zur Juroren-Bewertung, nur für den Notfall, wenn Judges nicht bewerten können
        st.markdown("### Orga-Backup-Bewertung (nur Notfall)")
        # Use juror names from config
        juror_names = [j["name"] for j in cfg.get_jurors()]
        col0, col1, col2 = st.columns([1, 1, 1])
        with col0:
            age_group2 = st.selectbox("Alterskategorie (Orga)", cfg.get_age_groups(), key="age_group_org")
        with col1:
            round_choice2 = st.radio("Runde (Orga)", ["1", "ZW"], horizontal=True, key="round_org")
        with col2:
            judge2 = st.selectbox("Juror (Orga)", juror_names, key="judge_org")
        crew2 = st.text_input("Crew (Orga – manuell oder aus Liste)")
        nums2 = {}
        for c in CATEGORIES:
            nums2[c] = st.selectbox(f"{c} (Orga)", ["—"] + [str(i) for i in range(1, 11)], key=f"org_{c}")
        all_set_org = crew2.strip() and age_group2 and all(v != "—" for v in nums2.values())
        if st.button("Orga-Bewertung speichern", disabled=not all_set_org):
            row = {
                "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
                "round": round_choice2,
                "age_group": age_group2,
                "crew": crew2.strip(),
                "judge": judge2,
            }
            for c in CATEGORIES:
                row[c] = int(nums2[c])
            backend.upsert_row(["round", "age_group", "crew", "judge"], row)
            st.success("Orga-Bewertung gespeichert.")
