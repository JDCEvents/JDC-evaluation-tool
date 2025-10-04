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
tabs = st.tabs(["Bewerten", "Leaderboard", "Daten & Export", "Orga"])

# ---------- TAB 0: BEWERTEN ----------
with tabs[0]:
    st.subheader("Bewertung abgeben")

    # Wenn Juror: erst nach Login freischalten
    if not orga_mode and not locked_judge:
        st.info("Nach erfolgreicher PIN-Eingabe erscheint hier deine Bewertungsmaske.")
    else:
        # Kopf-Auswahl
        col0, col1, col2 = st.columns([1, 1, 1])
        with col0:
            age_group = st.selectbox("Alterskategorie", age_groups, index=0 if age_groups else None, key="age_group_sel")
        with col1:
            crews_for_age = cfg.get_crews(age_group) if age_group else []
            crew = st.selectbox("Crew", crews_for_age, index=0 if crews_for_age else None, key="crew_sel")
        with col2:
            round_choice = st.radio("Runde", ["1", "ZW"], horizontal=True, key="round_sel")

        # Reset bei Crew-Wechsel
        if "last_crew" not in st.session_state:
            st.session_state["last_crew"] = ""
        if crew != st.session_state["last_crew"]:
            reset_vote_state()
            st.session_state["last_crew"] = crew

        # Eingabefelder (Keyboard 1–10)
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

        if not orga_mode:
            st.success(f"Hallo {st.session_state.get('judge_authed_name')} 👋 – du bist eingeloggt.")

        if invalid_fields:
            st.info("Bitte alle Kategorien mit **1–10** ausfüllen. Offen/ungültig: " + ", ".join(invalid_fields))

        # Save nur wenn gültig
        judge_name = st.session_state.get("judge_authed_name") if not orga_mode else None
        all_set = (crew and age_group and (orga_mode or judge_name) and all(values_int[c] is not None for c in CATEGORIES))

        if st.button("Speichern / Aktualisieren", type="primary", disabled=not all_set):
            row = {
                "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
                "round": round_choice,
                "age_group": age_group,
                "crew": crew,
                "judge": judge_name if judge_name else "Orga",
            }
            for c in CATEGORIES:
                row[c] = int(values_int[c])
            backend.upsert_row(["round", "age_group", "crew", "judge"], row)
            st.success(
                f"Bewertung gespeichert: {crew} (Startnr. {cfg.get_start_no(age_group, crew)}), "
                f"{age_group}, Runde {round_choice}, Juror {row['judge']}."
            )
            reset_vote_state()

# ---------- TAB 1: LEADERBOARD ----------
with tabs[1]:
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

# ---------- TAB 2: DATEN & EXPORT (gruppiert, dunkle Separatoren, Orga-Edit + Auto-Total + Konsistenz-Fix) ----------
with tabs[2]:
    st.subheader("Daten & Export")

    df_all = backend.load().copy()

    # -------- Helper / Normalisierung --------
    def _to_str(x):
        if pd.isna(x):
            return ""
        return str(x).strip()

    if not df_all.empty:
        # Runde vereinheitlichen ("1" / "ZW")
        df_all["round"] = df_all["round"].apply(_to_str).replace({"1.0": "1", "ZW.0": "ZW"})
        for cc in ["age_group", "crew", "judge", "timestamp"]:
            if cc in df_all.columns:
                df_all[cc] = df_all[cc].apply(_to_str)

    # Crew-Index aus Config: Crew -> (age_group, start_no)
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

    def _compute_weighted_local(row: Dict) -> int:
        total = 0
        for c in CATEGORIES:
            v = row.get(c, 0)
            try:
                v = int(v)
            except Exception:
                v = 0
            total += v * (2 if c in DOUBLE_CATS else 1)
        return int(total)

    # --- Separatoren: schmale, dunkle Trennzeilen ---
    def _with_separators(df: pd.DataFrame, group_col="crew") -> pd.DataFrame:
        """Fügt nach jeder Gruppe (Crew) eine schmale Separator-Zeile ein.
        - Deko-Spalten = " "
        - Numerische Spalten (Kategorien, Startnummer, TotalWeighted) bleiben None (damit Editor numerisch bleibt)
        """
        if df.empty:
            return df
        numeric_cols = set([*CATEGORIES, "Startnummer", "TotalWeighted"])
        deco_cols = [c for c in df.columns if c not in numeric_cols and c != group_col and c != "_sep"]

        blocks = []
        for _, g in df.groupby(group_col, sort=False):
            blocks.append(g)
            sep = {c: None for c in g.columns}
            sep[group_col] = ""  # leere Crew → optische Trennung
            for c in deco_cols:
                sep[c] = " "
            sep["_sep"] = True
            blocks.append(pd.DataFrame([sep]))
        return pd.concat(blocks, ignore_index=True)

    def _highlight_sep(row):
        if row.get("_sep", False):
            return ["background-color: #2b2b2b"] * len(row)  # dezent dunkelgrau
        return [""] * len(row)

    # -------- Anzeige / Logik --------
    if df_all.empty:
        st.info("Noch keine Daten vorhanden.")
        st.download_button(
            "Leere CSV herunterladen",
            data=df_all.to_csv(index=False).encode("utf-8"),
            file_name="scores_export.csv",
            mime="text/csv",
        )
    else:
        # Filter
        if orga_mode:
            colA, colB = st.columns([1, 1])
            with colA:
                age_filter = st.selectbox("Alterskategorie", ["Alle"] + age_groups, index=0, key="raw_age_filter")
            with colB:
                round_filter = st.selectbox("Runde", ["Alle", "1", "ZW"], index=0, key="raw_round_filter")
        else:
            age_filter = st.selectbox("Alterskategorie", ["Alle"] + age_groups, index=0, key="raw_age_filter_public")
            round_filter = "Alle"

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

        # Separatoren + Live-Total (Anzeige)
        df_view["_sep"] = False
        df_sep = _with_separators(df_view, group_col="crew")

        tmp = df_sep.copy()
        tmp["TotalWeighted"] = tmp.apply(
            lambda r: _compute_weighted_local(r) if not (isinstance(r.get("_sep", False), bool) and r["_sep"]) else None,
            axis=1,
        )

        # -------- Orga: Editor + Vorschau + Speichern --------
        if orga_mode:
            edit_mode = st.toggle("Bearbeiten aktivieren (nur Kategorien 1–10)", value=False)

            # Editor (nur Kategorien editierbar)
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

            grid = st.data_editor(
                tmp,
                use_container_width=True,
                hide_index=True,
                column_config=column_cfg,
                disabled=not edit_mode,
                key="orga_editor",
            )

            # Live-Total nach Edits neu berechnen
            grid_preview = grid.copy()
            mask_real = ~grid_preview["_sep"].fillna(False)
            grid_preview.loc[mask_real, "TotalWeighted"] = grid_preview[mask_real].apply(
                lambda r: _compute_weighted_local(r), axis=1
            )

            # Vorschau mit grauen Separatoren (read-only, für klare Trennung)
            st.markdown("**Vorschau (mit Trennzeilen):**")
            st.dataframe(grid_preview.style.apply(_highlight_sep, axis=1), use_container_width=True)

            # Konsistenz-Fix anbieten, falls nötig
            if needs_fix_rows:
                st.warning(f"Konsistenz: {len(needs_fix_rows)} Zeile(n) mit fehlender/falscher Startnummer/Alterskategorie erkannt.")
                if st.button("Konsistenz reparieren & speichern"):
                    df_fixed = df_all.copy()
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

            # Speichern der Kategorie-Edits
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
                    if st.button("Änderungen speichern", type="primary", disabled=save_disabled):
                        edited_df = grid_preview[mask_real].copy()
                        updates = 0
                        for _, r in edited_df.iterrows():
                            row = {
                                "timestamp": r.get("timestamp"),
                                "round": r.get("round"),
                                "age_group": r.get("age_group"),
                                "crew": r.get("crew"),
                                "judge": r.get("judge"),
                            }
                            for c in CATEGORIES:
                                row[c] = int(r[c])
                            backend.upsert_row(["round", "age_group", "crew", "judge"], row)
                            updates += 1
                        st.success(f"Änderungen gespeichert ({updates} Zeilen aktualisiert).")
                        st.rerun()

                if invalid_count > 0:
                    st.warning("Bitte alle bearbeiteten Kategorien mit **1–10** füllen (keine leeren/ungültigen Werte).")

            # Export (gefiltert, ohne Separatoren)
            export_df = df_view.copy()
            csv_bytes = export_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "CSV herunterladen (gefiltert, ohne Separatoren)",
                data=csv_bytes,
                file_name="scores_export.csv",
                mime="text/csv",
            )

        else:
            # Nicht-Orga: reine Anzeige mit Separatoren
            df_pub = df_view.copy()
            df_pub["_sep"] = False
            df_pub = _with_separators(df_pub, group_col="crew")
            st.dataframe(df_pub.style.apply(_highlight_sep, axis=1), use_container_width=True)
            st.download_button(
                "CSV herunterladen",
                data=df_pub.drop(columns=["_sep"], errors="ignore").to_csv(index=False).encode("utf-8"),
                file_name="scores_export.csv",
                mime="text/csv",
            )


# ---------- TAB 3: ORGA ----------
with tabs[3]:
    st.subheader("Orga")

    if not orga_mode:
        st.info("Orga-Modus aktivieren: URL mit `?orga=1&orgapin=XXXX`.")
    else:
        st.success("Orga-Modus aktiv.")

        # Juror:innen verwalten
        st.markdown("### Juroren verwalten (Namen & PINs)")
        jur_df = pd.DataFrame(cfg.get_jurors())
        if jur_df.empty:
            st.warning("Noch keine Juroren in der Config. Füge neue hinzu.")
        st.dataframe(jur_df, use_container_width=True)

        with st.form("add_juror"):
            colj1, colj2 = st.columns([2, 1])
            with colj1: new_jname = st.text_input("Name")
            with colj2: new_jpin = st.text_input("PIN (4-stellig)", max_chars=4)
            if st.form_submit_button("+ Juror hinzufügen") and new_jname.strip() and new_jpin.strip():
                cfg.set_jurors(cfg.get_jurors() + [{"name": new_jname.strip(), "pin": new_jpin.strip()}])
                st.success("Juror hinzugefügt. Seite neu laden.")

        if not jur_df.empty:
            with st.form("rename_juror"):
                rcol1, rcol2, _ = st.columns([2, 2, 1])
                with rcol1: old_j = st.selectbox("Juror auswählen", jur_df["name"].tolist())
                with rcol2: new_j = st.text_input("Neuer Name")
                if st.form_submit_button("Umbenennen") and old_j and new_j.strip():
                    updated = []
                    for j in cfg.get_jurors():
                        updated.append({"name": new_j.strip(), "pin": j["pin"]} if j["name"] == old_j else j)
                    cfg.set_jurors(updated)
                    st.success("Juror umbenannt. Seite neu laden.")

        if not jur_df.empty:
            with st.form("remove_juror"):
                dcol1, _ = st.columns([3, 1])
                with dcol1: del_j = st.selectbox("Juror entfernen", ["—"] + jur_df["name"].tolist())
                if st.form_submit_button("Entfernen") and del_j != "—":
                    cfg.set_jurors([j for j in cfg.get_jurors() if j["name"] != del_j])
                    st.success("Juror entfernt. Seite neu laden.")

        st.markdown("---")
        # Alterskategorien & Crews
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
            df_crews = pd.DataFrame(
                {"Startnummer": [cfg.get_start_no(ag, c) for c in current], "Crew": current}
            ).sort_values("Startnummer")
            st.dataframe(df_crews, use_container_width=True)

            new_crew = st.text_input("Neue Crew hinzufügen", "", key="orga_newcrew")
            if st.button("+ Hinzufügen", disabled=not new_crew.strip()):
                cfg.add_crew(ag, new_crew.strip())
                st.success(f"Crew '{new_crew.strip()}' hinzugefügt. Seite neu laden.")

            if current:
                with st.form("rename_crew"):
                    rc1, rc2 = st.columns([2, 2])
                    with rc1: oldc = st.selectbox("Crew umbenennen", current)
                    with rc2: newc = st.text_input("Neuer Name")
                    if st.form_submit_button("Umbenennen") and oldc and newc.strip():
                        cfg.rename_crew(ag, oldc, newc.strip())
                        st.success("Crew umbenannt. Seite neu laden.")

            if current:
                with st.form("remove_crew"):
                    dc1, _ = st.columns([3, 1])
                    with dc1: delc = st.selectbox("Crew entfernen", ["—"] + current)
                    if st.form_submit_button("Entfernen") and delc != "—":
                        cfg.remove_crew(ag, delc)
                        st.success("Crew entfernt. Seite neu laden.")

        st.markdown("---")
        # Orga-Backup-Bewertung (falls Judges nicht bewerten können)
        st.markdown("### Orga-Backup-Bewertung (nur Notfall)")
        juror_names = [j["name"] for j in cfg.get_jurors()]
        col0, col1, col2 = st.columns([1, 1, 1])
        with col0: age_group2 = st.selectbox("Alterskategorie (Orga)", cfg.get_age_groups(), key="age_group_org")
        with col1: round_choice2 = st.radio("Runde (Orga)", ["1", "ZW"], horizontal=True, key="round_org")
        with col2: judge2 = st.selectbox("Juror (Orga)", juror_names, key="judge_org")
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
