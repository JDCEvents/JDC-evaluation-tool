# app.py (JDC evaluation tool v4 – Private Judge Links + PIN-Login, keine Links sichtbar)
# --------------------------------------------------------------------
# WOFÜR IST DIESE DATEI?
# - Hauptdatei deiner Streamlit-App (UI, Logik, Validierung, Speicher).
# - Neu: Juror:innen bekommen NUR ihren privaten Link (?judge=Name)
#   und geben die PIN AUF DER SEITE ein (keine PIN in der URL mehr).
# - Orga-Modus bleibt via ?orga=1&orgapin=XXXX; nur dort gibt es alle
#   Admin-Controls (Finalisten N, Links-Übersicht optional, Datenpflege).
# --------------------------------------------------------------------

import streamlit as st
import pandas as pd
import datetime as dt
from typing import List, Dict, Optional
import pathlib, json

# --------------------------------------------------------------------
# BASIS-URL FÜR INTERNE LINKS (nur im Orga-Modus sichtbar, optional)
# - In Secrets als base_url setzen (Settings → Secrets):
#   base_url = "https://deine-app.streamlit.app"
# --------------------------------------------------------------------
BASE_URL = st.secrets.get("base_url", "https://<YOUR-APP>.streamlit.app")

# --------------------------------------------------------------------
# WERTUNGSKATEGORIEN & GEWICHTUNG
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
# CONFIG-MANAGER (persistente Inhalte in config.json)
# - Alterskategorien, Crews, Startnummern, Juror:innen
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
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                pass

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # ----- age groups & crews -----
    def get_age_groups(self) -> List[str]:
        return list(self.data.get("age_groups", []))

    def get_crews(self, age_group: str) -> List[str]:
        return list(self.data.get("crews_by_age", {}).get(age_group, []))

    def ensure_start_numbers(self):
        sn = self.data.setdefault("start_numbers", {})
        for ag in self.get_age_groups():
            crews = self.get_crews(ag)
            m = sn.setdefault(ag, {})
            # fehlende Startnummern in Listenreihenfolge vergeben
            for i, crew in enumerate(crews, start=1):
                m.setdefault(crew, i)
            # veraltete Einträge entfernen
            for k in list(m.keys()):
                if k not in crews:
                    del m[k]
        self.save()

    def get_start_no(self, age_group: str, crew: str) -> Optional[int]:
        return self.data.get("start_numbers", {}).get(age_group, {}).get(crew)

    def set_age_groups(self, groups: List[str]):
        self.data["age_groups"] = groups
        cba = self.data.setdefault("crews_by_age", {})
        for g in groups:
            cba.setdefault(g, [])
        for g in list(cba.keys()):
            if g not in groups:
                del cba[g]
        self.ensure_start_numbers()

    def add_crew(self, age_group: str, crew: str):
        cba = self.data.setdefault("crews_by_age", {})
        lst = cba.setdefault(age_group, [])
        if crew and crew not in lst:
            lst.append(crew)
            self.ensure_start_numbers()

    def remove_crew(self, age_group: str, crew: str):
        cba = self.data.setdefault("crews_by_age", {})
        lst = cba.setdefault(age_group, [])
        if crew in lst:
            lst.remove(crew)
            self.ensure_start_numbers()

    def rename_crew(self, age_group: str, old: str, new: str):
        if not new or old == new:
            return
        crews = self.data.setdefault("crews_by_age", {}).setdefault(age_group, [])
        if old in crews and new not in crews:
            idx = crews.index(old)
            crews[idx] = new
            # Startnummer beibehalten
            sn = self.data.setdefault("start_numbers", {}).setdefault(age_group, {})
            sn[new] = sn.get(old, sn.get(new, None)) or (idx + 1)
            if old in sn:
                del sn[old]
            self.save()

    # ----- jurors -----
    def get_jurors(self) -> List[Dict]:
        return list(self.data.get("jurors", []))

    def set_jurors(self, jurors: List[Dict]):
        clean, seen = [], set()
        for j in jurors:
            name = (j.get("name") or "").strip()
            pin = str(j.get("pin") or "").strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                clean.append({"name": name, "pin": pin})
        self.data["jurors"] = clean
        self.save()

cfg = ConfigManager("config.json")

# --------------------------------------------------------------------
# PINS-LADELOGIK: Secrets überschreiben config.json
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
        JUDGE_PINS.update(dict(st.secrets["judge_pins"]))
    except Exception:
        pass
JUDGES = list(JUDGE_PINS.keys())
ORGA_PIN = st.secrets.get("orga_pin", "") or ""

# --------------------------------------------------------------------
# CSV-BACKEND: Lokaler CSV-Speicher "data.csv"
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
        return int(sum((row.get(c, 0) or 0) * (2 if c in DOUBLE_CATS else 1) for c in CATEGORIES))

    def upsert_row(self, key_cols: List[str], row: Dict):
        """Wird beim normalen Speichern (Jury & Orga-Notfall) benutzt:
        aktualisiert nach Key-Kombination oder legt neuen Datensatz an."""
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

    def update_scores_by_timestamp_and_judge(self, ts: str, judge: str, new_scores: Dict):
        """
        ORGA-Korrektur: überschreibt NUR die Kategorien (1–10) und TotalWeighted
        der Zeile mit (timestamp==ts AND judge==judge). Legt KEINE neue Zeile an.
        """
        df = self.load()
        if df.empty:
            return
        if "timestamp" not in df.columns or "judge" not in df.columns:
            return

        mask = (df["timestamp"].astype(str) == str(ts)) & (df["judge"].astype(str) == str(judge))
        if not mask.any():
            return

        idx = mask[mask].index[0]

        # Kategorien setzen
        for c in CATEGORIES:
            if c in new_scores:
                try:
                    df.at[idx, c] = int(new_scores[c])
                except Exception:
                    df.at[idx, c] = 0

        # TotalWeighted neu berechnen (gleich wie _compute_weighted)
        total = 0
        for c in CATEGORIES:
            try:
                v = int(df.at[idx, c])
            except Exception:
                v = 0
            total += v * (2 if c in DOUBLE_CATS else 1)
        df.at[idx, "TotalWeighted"] = int(total)

        df.to_csv(self.path, index=False)

backend = CSVBackend("data.csv")


# --------------------------------------------------------------------
# Leaderboard
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
# Query-Param-Helper (robust für String/Liste)
# --------------------------------------------------------------------
def _qp_get(name: str):
    val = st.query_params.get(name)
    if isinstance(val, list):
        return val[0]
    return val

# --------------------------------------------------------------------
# Orga-Check (nur Orga sieht Admin-Controls/Sidebar-Settings)
# --------------------------------------------------------------------
def is_orga_mode() -> bool:
    val = (_qp_get("orga") or "").strip()
    pin = (_qp_get("orgapin") or "").strip()
    if val not in ("1", "true", "True"):
        return False
    return (pin == ORGA_PIN) if ORGA_PIN else bool(pin)

# --------------------------------------------------------------------
# Judge-Login:
# - Privatlink: ?judge=Fiona (keine PIN in URL)
# - Seite zeigt PIN-Feld; nach korrekter Eingabe wird Session freigeschaltet
# --------------------------------------------------------------------
def judge_login() -> Optional[str]:
    # Wenn bereits eingeloggt, zurückgeben
    if st.session_state.get("judge_authed_name"):
        return st.session_state["judge_authed_name"]

    # Namen aus privatem Link
    j_name = (_qp_get("judge") or "").strip()
    if not j_name:
        # Kein Name in URL → Info anzeigen
        st.info("Bitte nutze deinen **privaten Jury-Link** (z. B. `…/?judge=Fiona`).")
        return None

    # PIN-Datenquelle (Secrets/config)
    expected_pin = str(JUDGE_PINS.get(j_name, "")).strip()
    if not expected_pin:
        st.error("Unbekannter Juror oder kein PIN hinterlegt. Bitte Orga kontaktieren.")
        return None

    st.markdown(f"#### Hallo {j_name}! Bitte gib deine **4-stellige PIN** ein, um fortzufahren.")
    pin_input = st.text_input("PIN", type="password", max_chars=4, key="pin_prompt")
    if st.button("Anmelden"):
        if pin_input == expected_pin:
            st.session_state["judge_authed_name"] = j_name
            st.success("Erfolgreich angemeldet.")
            st.rerun()
        else:
            st.error("Falscher PIN.")
    return None

# --------------------------------------------------------------------
# UI-Helfer
# --------------------------------------------------------------------
def reset_vote_state():
    # Statt Keys aktiv auf "" zu setzen (führt in Streamlit 1.50 zu Problemen),
    # löschen wir sie einfach. Beim nächsten Rendern starten die Felder automatisch leer.
    for c in CATEGORIES:
        st.session_state.pop(f"cat_{c}", None)

# --------------------------------------------------------------------
# Seite konfigurieren
# --------------------------------------------------------------------
st.set_page_config(page_title="JDC Scoring 2026", page_icon="🧮", layout="wide")
st.title("🧮 JDC Scoring 2026")

orga_mode = is_orga_mode()
locked_judge = None if orga_mode else judge_login()  # Juror:innen: Login-Flow

# --------------------------------------------------------------------
# Sidebar:
# - Für Juror:innen KEINE Links/Settings anzeigen.
# - Für Orga: Finalisten-N + optional Links-Expander.
# --------------------------------------------------------------------
if orga_mode:
    st.sidebar.header("Orga-Setup")
    finalists_n = st.sidebar.selectbox("Direkt ins Finale (Top N)", [5, 6, 7], index=0)
    with st.sidebar.expander("(Optional) Links anzeigen"):
        st.caption("Nur für Orga sichtbar – zum Verteilen/Checken:")
        st.write("Orga-Link:")
        st.code(f"{BASE_URL}/?orga=1&orgapin={ORGA_PIN or '<PIN setzen>'}")
        st.write("Jury-Privatlinks (ohne PIN):")
        for name in JUDGES:
            st.code(f"{BASE_URL}/?judge={name}")
else:
    # Juror:innen sehen keine Sidebar-Settings
    finalists_n = 5  # Default; Orga kann dies im Orga-Modus anpassen

age_groups = cfg.get_age_groups()

# Tabs definieren – feste Reihenfolge für Orga vs. Judge (benannte Variablen statt Indizes)
if orga_mode:
    tab_bewerten, tab_leaderboard, tab_bewertungen, tab_orga = st.tabs(
        ["Bewerten", "Leaderboard", "Bewertungen", "Organisation"]
    )
else:
    tab_bewerten, tab_bewertungen = st.tabs(["Bewerten", "Bewertungen"])



# Helfer: „Anheften“-Button oben in jedem Tab einblenden
def pin_this_tab(tab_name: str, key_suffix: str):
    col_pin, _ = st.columns([1, 8])
    with col_pin:
        if st.button("Ansicht anheften (bei Reload beibehalten)", key=f"pin_{key_suffix}"):
            st.query_params["tab"] = tab_name
            st.success("Ansicht angeheftet – Reload bleibt auf dieser Seite.")


# ---------- TAB: BEWERTEN ----------
with tab_bewerten:
    st.subheader("Bewertung abgeben")

    # Nicht-Orga: erst PIN-Login (privater Link ?judge=Name)
    if not orga_mode and not locked_judge:
        st.info("Nach erfolgreicher PIN-Eingabe erscheint hier deine Bewertungsmaske.")
    else:
        # --- Kopf-Auswahl ---
        col0, col1, col2 = st.columns([1, 1, 1])
        with col0:
            age_group = st.selectbox("Alterskategorie", age_groups, index=0 if age_groups else None, key="age_group_sel")
        with col1:
            crews_for_age = cfg.get_crews(age_group) if age_group else []
            crew = st.selectbox("Crew", crews_for_age, index=0 if crews_for_age else None, key="crew_sel")
        with col2:
            round_choice = st.radio("Runde", ["1", "ZW"], horizontal=True, key="round_sel")

        # Orga darf einen Juror wählen (Eingabe im Namen dieses Jurors)
        judge_name = None
        if orga_mode:
            juror_names = [j["name"] for j in cfg.get_jurors()]
            if not juror_names:
                st.warning("Keine Juroren in der Config. Lege welche im Orga-Tab an.")
            judge_name = st.selectbox("Juror (im Namen von)", ["—"] + juror_names, index=0, key="orga_judge_sel")
        else:
            judge_name = st.session_state.get("judge_authed_name")
            if judge_name:
                st.success(f"Hallo {judge_name} 👋 – du bist eingeloggt.")

        # Reset bei Crew-Wechsel
        if "last_crew" not in st.session_state:
            st.session_state["last_crew"] = ""
        if crew != st.session_state["last_crew"]:
            reset_vote_state()
            st.session_state["last_crew"] = crew

        # --- Eingabefelder (Tastatur 1–10) ---
        st.markdown("### Kategorien (bitte jede Kategorie als Zahl 1–10 eingeben)")
        values_raw, values_int, invalid_fields = {}, {}, []

        def _parse_score(s: str):
            s = (s or "").strip()
            if not s or not s.isdigit():
                return None
            v = int(s)
            return v if 1 <= v <= 10 else None

        for c in CATEGORIES:
            key = f"cat_{c}"
            if key not in st.session_state:
                st.session_state[key] = ""
            values_raw[c] = st.text_input(label=c, value=st.session_state[key], key=key, placeholder="1–10")
            parsed = _parse_score(values_raw[c])
            values_int[c] = parsed
            if parsed is None:
                invalid_fields.append(c)

        if invalid_fields:
            st.info("Bitte alle Kategorien mit **1–10** ausfüllen. Offen/ungültig: " + ", ".join(invalid_fields))

        # --- Speichern / Aktualisieren ---
        # Wer ist der Juror, in dessen Namen gespeichert wird?
        if orga_mode:
            effective_judge = None if judge_name in (None, "—") else judge_name
        else:
            effective_judge = judge_name  # aus PIN-Login

        all_set = (
            crew
            and age_group
            and (effective_judge is not None)  # Orga muss Juror wählen; Judge-Modus bereits eingeloggt
            and all(values_int[c] is not None for c in CATEGORIES)
        )

        if orga_mode and effective_judge is None:
            st.warning("Bitte oben einen **Juror** auswählen, in dessen Namen du speicherst.")

        if st.button("Speichern / Aktualisieren", type="primary", disabled=not all_set, key="btn_save_scores"):
            row = {
                "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
                "round": round_choice,
                "age_group": age_group,
                "crew": crew,
                "judge": effective_judge,
            }
            for c in CATEGORIES:
                row[c] = int(values_int[c])

            # Upsert nach (round, age_group, crew, judge) – wie gehabt
            backend.upsert_row(["round", "age_group", "crew", "judge"], row)

            st.success(
                f"Bewertung gespeichert: {crew} (Startnr. {cfg.get_start_no(age_group, crew)}), "
                f"{age_group}, Runde {round_choice}, Juror {row['judge']}."
            )
            reset_vote_state()

# ---------- TAB: LEADERBOARD (nur Orga) ----------
if orga_mode:
    with tab_leaderboard:
    st.subheader("Leaderboard")
    df_all = backend.load()
    colf1, colf2 = st.columns([1, 2])
    with colf1:
        round_view = st.radio("Runde", ["1", "ZW"], horizontal=True, key="round_view")
        age_view = st.selectbox("Alterskategorie", age_groups, index=0 if age_groups else None, key="age_view")

    if not df_all.empty and age_view:
        df_view = df_all[(df_all["round"] == round_view) & (df_all["age_group"] == age_view)].copy()
    else:
        df_view = pd.DataFrame()

    if not df_view.empty:
        df_view["Startnummer"] = df_view["crew"].map(lambda x: cfg.get_start_no(age_view, x))

    board = compute_leaderboard(df_view.copy())
    st.dataframe(board, use_container_width=True)

    # Finalisten/ZW nur Info – Steuerung (Top N) ist Orga-only (Sidebar)
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

# ---------- TAB: BEWERTUNGEN ----------
with tab_bewertungen:
    st.subheader("Bewertungen")

    df_all = backend.load().copy()

    # ======= Gemeinsame kleine Helfer =======
    def _to_str(x):
        if pd.isna(x):
            return ""
        return str(x).strip()

    def _compute_weighted_local(row: Dict) -> int:
        total = 0
        for c in CATEGORIES:
            try:
                v = int(row.get(c, 0))
            except Exception:
                v = 0
            total += v * (2 if c in DOUBLE_CATS else 1)
        return int(total)

    # ======= ORGA-VARIANTE =======
    if orga_mode:
        # Normalisierung
        if not df_all.empty:
            df_all["round"] = df_all["round"].apply(_to_str).replace({"1.0": "1", "ZW.0": "ZW"})
            for cc in ["age_group", "crew", "judge", "timestamp"]:
                if cc in df_all.columns:
                    df_all[cc] = df_all[cc].apply(_to_str)

        # Crew-Index: Crew -> (age_group, start_no)
        def _build_crew_index():
            idx = {}
            for ag in cfg.get_age_groups():
                for c in cfg.get_crews(ag):
                    sn = cfg.get_start_no(ag, c)
                    if c not in idx:
                        idx[c] = (ag, sn)
                    else:
                        idx[c] = None  # sollte nicht passieren; markiere ambivalent
            return idx

        CREW_INDEX = _build_crew_index()

        def _derive_ag_sn(ag_in, crew):
            """Gibt (age_group, start_no, changed_flag) zurück.
            Falls age_group leer/falsch ist, nimm die aus der Config."""
            if crew in CREW_INDEX and CREW_INDEX[crew]:
                ag_cfg, sn_cfg = CREW_INDEX[crew]
                if not ag_in or ag_in != ag_cfg:
                    return ag_cfg, sn_cfg, True
                return ag_in, sn_cfg, False
            return ag_in, None, False

        # Separatoren (für Read-only Vorschau—nicht im Editor möglich)
        def _with_separators(df: pd.DataFrame, group_col="crew") -> pd.DataFrame:
            """Fügt nach jeder Gruppe (Crew) eine schmale Separator-Zeile ein.
            Numerische Spalten bleiben None; Deko-Spalten werden ' ' gesetzt."""
            if df.empty:
                return df
            numeric_cols = set([*CATEGORIES, "Startnummer", "TotalWeighted"])
            deco_cols = [c for c in df.columns if c not in numeric_cols and c != group_col and c != "_sep"]

            blocks = []
            for _, g in df.groupby(group_col, sort=False):
                blocks.append(g)
                sep = {c: None for c in g.columns}
                sep[group_col] = ""
                for c in deco_cols:
                    sep[c] = " "
                sep["_sep"] = True
                blocks.append(pd.DataFrame([sep]))
            return pd.concat(blocks, ignore_index=True)

        def _highlight_sep(row):
            if row.get("_sep", False):
                return ["background-color: #2b2b2b"] * len(row)
            return [""] * len(row)

        if df_all.empty:
            st.info("Noch keine Daten vorhanden.")
            st.download_button(
                "Leere CSV herunterladen",
                data=df_all.to_csv(index=False).encode("utf-8"),
                file_name="scores_export.csv",
                mime="text/csv",
                key="dl_empty_csv",
            )
        else:
            # Filter
            colA, colB = st.columns([1, 1])
            with colA:
                age_filter = st.selectbox("Alterskategorie", ["Alle"] + age_groups, index=0, key="raw_age_filter")
            with colB:
                round_filter = st.selectbox("Runde", ["Alle", "1", "ZW"], index=0, key="raw_round_filter")

            df_view = df_all.copy()
            if age_filter != "Alle":
                df_view = df_view[df_view["age_group"] == age_filter]
            if round_filter != "Alle":
                df_view = df_view[df_view["round"] == round_filter]

            # Konsistenzableitung (im View, ohne Speichern): setze age_group aus Config & hole Startnummer
            needs_fix_rows = []
            if not df_view.empty:
                new_ag, new_sn, flags = [], [], []
                for _, r in df_view.iterrows():
                    ag_new, sn_new, changed = _derive_ag_sn(r.get("age_group", ""), r.get("crew", ""))
                    new_ag.append(ag_new or r.get("age_group", ""))
                    new_sn.append(sn_new)
                    flags.append(changed or (sn_new is None))
                df_view["age_group"] = new_ag
                df_view["Startnummer"] = new_sn
                needs_fix_rows = [i for i, f in enumerate(flags) if f]

            # Sortierung & Spalten
            df_view = df_view.sort_values(
                by=["Startnummer", "crew", "judge", "timestamp"],
                ascending=True,
                kind="mergesort",
            ).reset_index(drop=True)

            nice_order = ["Startnummer", "age_group", "round", "crew", "judge", "timestamp", *CATEGORIES, "TotalWeighted"]
            df_view = df_view[[c for c in nice_order if c in df_view.columns]]

            # Separator-Flag
            df_view["_sep"] = False
            df_sep = _with_separators(df_view, group_col="crew")

            # Totals live berechnen (auch wenn editiert wurde)
            tmp = df_sep.copy()
            tmp["TotalWeighted"] = tmp.apply(
                lambda r: _compute_weighted_local(r) if not (isinstance(r.get("_sep", False), bool) and r["_sep"]) else None,
                axis=1,
            )

            # Bearbeitung standardmäßig AKTIV:
            edit_mode = st.toggle("Bearbeiten aktivieren (nur Kategorien 1–10)", value=True, key="edit_mode_tab2")

            # Editor (nur Kategorien editierbar). Hinweis: Styling in data_editor nicht möglich.
            editable_cols = [c for c in CATEGORIES if c in tmp.columns]
            column_cfg = {
                "Startnummer": st.column_config.NumberColumn("Startnummer", disabled=True),
                "age_group": st.column_config.TextColumn("Alterskategorie", disabled=True),
                "round": st.column_config.TextColumn("Runde", disabled=True),
                "crew": st.column_config.TextColumn("Crew", disabled=True),
                "judge": st.column_config.TextColumn("Juror", disabled=True),
                "timestamp": st.column_config.TextColumn("Zeitstempel", disabled=True),
                "TotalWeighted": st.column_config.NumberColumn("Total (gewichtet)", disabled=True),
                "_sep": st.column_config.CheckboxColumn("_sep", disabled=True),
                **{c: st.column_config.NumberColumn(c, min_value=1, max_value=10, step=1) for c in editable_cols},
            }

            if edit_mode:
                grid = st.data_editor(
                    tmp,
                    use_container_width=True,
                    hide_index=True,
                    column_config=column_cfg,
                    disabled=False,
                    key="orga_editor",
                )
            else:
                # Read-only mit grauen Separatoren
                grid = tmp  # für Konsistenz mit späterer Verarbeitung
                st.dataframe(tmp.style.apply(_highlight_sep, axis=1), use_container_width=True)

            # Live-Total nach Edits neu berechnen
            grid_preview = (grid.copy() if isinstance(grid, pd.DataFrame) else pd.DataFrame(grid).copy())
            if "_sep" in grid_preview.columns:
                mask_real = ~grid_preview["_sep"].fillna(False)
            else:
                mask_real = pd.Series([True] * len(grid_preview))
            grid_preview.loc[mask_real, "TotalWeighted"] = grid_preview[mask_real].apply(
                lambda r: _compute_weighted_local(r), axis=1
            )

            # Speichern der Kategorie-Edits (überschreibt bestehende Zeile per timestamp+judge)
            if edit_mode:
                def _valid_row(rr):
                    for c in CATEGORIES:
                        try:
                            v = int(rr[c])
                            if not (1 <= v <= 10):
                                return False
                        except Exception:
                            return False
                    return True

                invalid_mask = mask_real & (~grid_preview.apply(_valid_row, axis=1))
                invalid_count = int(invalid_mask.sum())

                col_save, _ = st.columns([1, 5])
                with col_save:
                    save_disabled = invalid_count > 0
                    if st.button("Änderungen speichern", type="primary", disabled=save_disabled, key="save_edits_tab2"):
                        edited_df = grid_preview[mask_real].copy()
                        updates = 0
                        for _, r in edited_df.iterrows():
                            backend.update_scores_by_timestamp_and_judge(
                                ts=str(r.get("timestamp")),
                                judge=str(r.get("judge")),
                                new_scores={c: int(r[c]) for c in CATEGORIES}
                            )
                            updates += 1
                        st.success(f"Änderungen gespeichert ({updates} Zeilen aktualisiert).")
                        st.rerun()

                if invalid_count > 0:
                    st.warning("Bitte alle bearbeiteten Kategorien mit **1–10** füllen (keine leeren/ungültigen Werte).")

                # Konsistenz-Fix (age_group / Startnummer geradeziehen)
                if needs_fix_rows:
                    st.warning(f"Konsistenz: {len(needs_fix_rows)} Zeile(n) mit fehlender/falscher Startnummer/Alterskategorie erkannt.")
                    if st.button("Konsistenz reparieren & speichern", key="btn_fix_consistency"):
                        df_fixed = backend.load().copy()
                        ag_list, sn_list = [], []
                        for _, r in df_fixed.iterrows():
                            ag_new, sn_new, _ = _derive_ag_sn(r.get("age_group", ""), r.get("crew", ""))
                            ag_list.append(ag_new or r.get("age_group", ""))
                            sn_list.append(sn_new)
                        df_fixed["age_group"] = ag_list
                        # TotalWeighted sicher neu berechnen
                        for c in CATEGORIES:
                            if c in df_fixed.columns:
                                df_fixed[c] = pd.to_numeric(df_fixed[c], errors="coerce").fillna(0).astype(int)
                        df_fixed["TotalWeighted"] = df_fixed.apply(_compute_weighted_local, axis=1)
                        pathlib.Path(backend.path).write_text(df_fixed.to_csv(index=False), encoding="utf-8")
                        st.success("Konsistenz-Fix gespeichert.")
                        st.rerun()

            # Export (gefiltert, ohne Separatoren)
            export_df = df_view.copy()
            csv_bytes = export_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "CSV herunterladen (gefiltert)",
                data=csv_bytes,
                file_name="scores_export.csv",
                mime="text/csv",
                key="dl_filtered_csv",
            )

    # ======= JURY-VARIANTE =======
    else:
        judge_name = st.session_state.get("judge_authed_name")
        if not judge_name:
            st.info("Bitte zuerst mit deinem PIN einloggen.")
        else:
            st.success(f"Hallo {judge_name}, hier sind deine Bewertungen.")

            if df_all.empty:
                st.info("Du hast noch keine Bewertungen gespeichert.")
            else:
                # Nur Bewertungen dieses Jurors
                df_judge = df_all[df_all["judge"] == judge_name].copy()

                # Filter: Alterskategorie + Runde
                col1, col2 = st.columns([1, 1])
                with col1:
                    age_filter = st.selectbox("Alterskategorie", ["Alle"] + age_groups, index=0, key="judge_age_filter")
                with col2:
                    round_filter = st.selectbox("Runde", ["Alle", "1", "ZW"], index=0, key="judge_round_filter")

                if age_filter != "Alle":
                    df_judge = df_judge[df_judge["age_group"] == age_filter]
                if round_filter != "Alle":
                    df_judge = df_judge[df_judge["round"] == round_filter]

                # Sortierung: nach Startnummer, Crew, Timestamp
                if not df_judge.empty:
                    df_judge["Startnummer"] = df_judge.apply(
                        lambda r: cfg.get_start_no(r["age_group"], r["crew"]), axis=1
                    )
                    df_judge = df_judge.sort_values(
                        by=["Startnummer", "crew", "timestamp"], ascending=True, kind="mergesort"
                    ).reset_index(drop=True)

                    # Nur relevante Spalten anzeigen (keine Separatoren, keine Editierung)
                    nice_order = ["Startnummer", "age_group", "round", "crew", "timestamp", *CATEGORIES, "TotalWeighted"]
                    df_judge = df_judge[[c for c in nice_order if c in df_judge.columns]]

                    st.dataframe(df_judge, use_container_width=True)

                    # Download-Option nur für die eigenen Daten
                    st.download_button(
                        "Meine Bewertungen als CSV herunterladen",
                        data=df_judge.to_csv(index=False).encode("utf-8"),
                        file_name=f"scores_{judge_name}.csv",
                        mime="text/csv",
                        key="dl_my_csv",
                    )
                else:
                    st.info("Keine Bewertungen für die gewählten Filter vorhanden.")

# ---------- TAB 3: ORGANISATION ----------
if orga_mode:
    with tab_orga:

    st.subheader("Organisation")

    if not orga_mode:
        st.info("Orga-Modus aktivieren: URL mit `?orga=1&orgapin=XXXX`.")
    else:
        st.success("Orga-Modus aktiv.")

        # --- Juror:innen verwalten -------------------------------------------------
        st.markdown("### Juroren verwalten (Namen & PINs)")
        jur_df = pd.DataFrame(cfg.get_jurors())
        if jur_df.empty:
            st.warning("Noch keine Juroren in der Config. Füge neue hinzu.")
        st.dataframe(jur_df, use_container_width=True)

        # Juror hinzufügen
        with st.form("add_juror_form"):
            colj1, colj2 = st.columns([2, 1])
            with colj1:
                new_jname = st.text_input("Name", key="jur_add_name")
            with colj2:
                new_jpin = st.text_input("PIN (4-stellig)", max_chars=4, key="jur_add_pin")
            if st.form_submit_button("+ Juror hinzufügen", help="Neuen Juror mit PIN anlegen"):
                if new_jname.strip() and new_jpin.strip():
                    cfg.set_jurors(cfg.get_jurors() + [{"name": new_jname.strip(), "pin": new_jpin.strip()}])
                    st.success("Juror hinzugefügt. Seite neu laden.")
                else:
                    st.error("Bitte Name und 4-stellige PIN angeben.")

        # Juror umbenennen
        if not jur_df.empty:
            with st.form("rename_juror_form"):
                rcol1, rcol2, _ = st.columns([2, 2, 1])
                with rcol1:
                    old_j = st.selectbox("Juror auswählen", jur_df["name"].tolist(), key="jur_rename_old")
                with rcol2:
                    new_j = st.text_input("Neuer Name", key="jur_rename_new")
                if st.form_submit_button("Umbenennen"):
                    if old_j and new_j.strip():
                        updated = []
                        for j in cfg.get_jurors():
                            updated.append({"name": new_j.strip(), "pin": j["pin"]} if j["name"] == old_j else j)
                        cfg.set_jurors(updated)
                        st.success("Juror umbenannt. Seite neu laden.")
                    else:
                        st.error("Bitte alten Juror wählen und neuen Namen eintragen.")

        # Juror entfernen
        if not jur_df.empty:
            with st.form("remove_juror_form"):
                dcol1, _ = st.columns([3, 1])
                with dcol1:
                    del_j = st.selectbox("Juror entfernen", ["—"] + jur_df["name"].tolist(), key="jur_remove_name")
                if st.form_submit_button("Entfernen"):
                    if del_j != "—":
                        cfg.set_jurors([j for j in cfg.get_jurors() if j["name"] != del_j])
                        st.success("Juror entfernt. Seite neu laden.")
                    else:
                        st.error("Bitte einen Juror auswählen.")

        st.markdown("---")

        # --- Alterskategorien & Crews verwalten -----------------------------------
        st.markdown("### Alterskategorien & Crews verwalten")

        groups_str = ",".join(cfg.get_age_groups())
        new_groups = st.text_input("Alterskategorien (kommagetrennt)", groups_str, key="ag_edit_list")
        if st.button("Speichern (Kategorien)", key="btn_save_groups"):
            groups = [g.strip() for g in new_groups.split(",") if g.strip()]
            if groups:
                cfg.set_age_groups(groups)
                st.success("Alterskategorien gespeichert – Seite neu laden.")
            else:
                st.error("Mindestens eine Kategorie angeben.")

        ag = st.selectbox("Alterskategorie auswählen", cfg.get_age_groups(), key="orga_ag_sel")
        if ag:
            current = cfg.get_crews(ag)
            df_crews = pd.DataFrame(
                {"Startnummer": [cfg.get_start_no(ag, c) for c in current], "Crew": current}
            ).sort_values("Startnummer", kind="mergesort")
            st.dataframe(df_crews, use_container_width=True)

            # Crew hinzufügen
            new_crew = st.text_input("Neue Crew hinzufügen", "", key="orga_new_crew")
            if st.button("+ Hinzufügen", key="btn_add_crew", disabled=not new_crew.strip()):
                cfg.add_crew(ag, new_crew.strip())
                st.success(f"Crew '{new_crew.strip()}' hinzugefügt. Seite neu laden.")

            # Crew umbenennen
            if current:
                with st.form("rename_crew_form"):
                    rc1, rc2 = st.columns([2, 2])
                    with rc1:
                        oldc = st.selectbox("Crew umbenennen", current, key="crew_rename_old")
                    with rc2:
                        newc = st.text_input("Neuer Name", key="crew_rename_new")
                    if st.form_submit_button("Umbenennen"):
                        if oldc and newc.strip():
                            cfg.rename_crew(ag, oldc, newc.strip())
                            st.success("Crew umbenannt. Seite neu laden.")
                        else:
                            st.error("Bitte bestehende Crew wählen und neuen Namen eintragen.")

            # Crew entfernen
            if current:
                with st.form("remove_crew_form"):
                    dc1, _ = st.columns([3, 1])
                    with dc1:
                        delc = st.selectbox("Crew entfernen", ["—"] + current, key="crew_remove_sel")
                    if st.form_submit_button("Entfernen"):
                        if delc != "—":
                            cfg.remove_crew(ag, delc)
                            st.success("Crew entfernt. Seite neu laden.")
                        else:
                            st.error("Bitte eine Crew auswählen.")

        st.markdown("---")

        # --- Orga-Backup-Bewertung (Notfall) --------------------------------------
        st.markdown("### Orga-Backup-Bewertung (nur Notfall)")
        juror_names = [j["name"] for j in cfg.get_jurors()]
        col0, col1, col2 = st.columns([1, 1, 1])
        with col0:
            age_group2 = st.selectbox("Alterskategorie (Orga)", cfg.get_age_groups(), key="age_group_org")
        with col1:
            round_choice2 = st.radio("Runde (Orga)", ["1", "ZW"], horizontal=True, key="round_org")
        with col2:
            judge2 = st.selectbox("Juror (Orga)", juror_names, key="judge_org")
        crew2 = st.text_input("Crew (Orga – manuell oder aus Liste)", key="crew_org_input")

        nums2 = {}
        for c in CATEGORIES:
            nums2[c] = st.selectbox(f"{c} (Orga)", ["—"] + [str(i) for i in range(1, 11)], key=f"org_score_{c}")

        all_set_org = crew2.strip() and age_group2 and all(v != "—" for v in nums2.values())
        if st.button("Orga-Bewertung speichern", key="btn_orgasave", disabled=not all_set_org):
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

        st.markdown("---")

        # --- Gefahrzone: 4-stufiger Bestätigungs-Flow zum Voll-Reset --------------
        st.markdown("### ❌ Gefahrzone: Alle Wertungsdaten löschen (nur Orga)")

        if "wipe_confirm_step" not in st.session_state:
            st.session_state["wipe_confirm_step"] = 0

        step = st.session_state["wipe_confirm_step"]

        if step == 0:
            if st.button("Alle Wertungsdaten löschen", key="wipe_step0"):
                st.session_state["wipe_confirm_step"] = 1
                st.rerun()

        elif step == 1:
            st.warning("❓ Bist du dir absolut sicher, dass du **ALLE** Wertungen löschen willst?")
            cols = st.columns(2)
            with cols[0]:
                if st.button("Ja, weiter", key="wipe_yes1"):
                    st.session_state["wipe_confirm_step"] = 2
                    st.rerun()
            with cols[1]:
                if st.button("Abbrechen", key="wipe_cancel1"):
                    st.session_state["wipe_confirm_step"] = 0
                    st.rerun()

        elif step == 2:
            st.error("⚠️ Mit diesem Schritt werden **ALLE** bisher abgegebenen Daten von den Judges gelöscht!")
            cols = st.columns(2)
            with cols[0]:
                if st.button("Ja, ich möchte trotzdem fortfahren", key="wipe_yes2"):
                    st.session_state["wipe_confirm_step"] = 3
                    st.rerun()
            with cols[1]:
                if st.button("Abbrechen", key="wipe_cancel2"):
                    st.session_state["wipe_confirm_step"] = 0
                    st.rerun()

        elif step == 3:
            st.error("🚨 **LETZTE WARNUNG!** JETZT werden wirklich ALLE Daten gelöscht.")

            # Backup-Export (empfohlen)
            try:
                _df_backup = backend.load().copy()
            except Exception:
                _df_backup = pd.DataFrame(columns=["timestamp","round","age_group","crew","judge", *CATEGORIES, "TotalWeighted"])
            csv_backup = _df_backup.to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇️ Aktuelle Daten als CSV sichern (empfohlen)",
                data=csv_backup,
                file_name="scores_backup.csv",
                mime="text/csv",
                key="wipe_backup_download",
                help="Lade ein Backup der aktuellen Wertungen herunter, bevor du alles löschst."
            )

            st.write("")

            cols = st.columns(2)
            with cols[0]:
                if st.button("JETZT HIER ALLE Daten löschen", key="wipe_delete"):
                    import os
                    try:
                        if pathlib.Path(backend.path).exists():
                            os.remove(backend.path)
                        backend = CSVBackend("data.csv")  # neue leere CSV sofort erzeugen
                        st.success("✅ Alle Wertungen wurden gelöscht. Die Datenbank ist jetzt leer.")
                        st.session_state["wipe_confirm_step"] = 0
                        st.rerun()
                    except Exception as e:
                        st.error(f"Fehler beim Löschen: {e}")
            with cols[1]:
                if st.button("Abbrechen", key="wipe_cancel3"):
                    st.session_state["wipe_confirm_step"] = 0
                    st.rerun()
