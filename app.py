# app.py (JDC evaluation tool)
import streamlit as st
import pandas as pd
import datetime as dt
from typing import List, Dict, Optional
import pathlib, json, io

CATEGORIES = ["Synchronität","Schwierigkeit der Choreographie","Choreographie","Bilder und Linien","Ausdruck und Bühnenpräsenz"]
DOUBLE_CATS = ["Synchronität","Schwierigkeit der Choreographie"]

JUDGE_PINS = None
ORGA_PIN = None
try:
    if "judge_pins" in st.secrets:
        JUDGE_PINS = dict(st.secrets["judge_pins"])
except Exception:
    JUDGE_PINS = None
try:
    if "orga_pin" in st.secrets:
        ORGA_PIN = str(st.secrets["orga_pin"])
except Exception:
    ORGA_PIN = None

class ConfigManager:
    def __init__(self, path="config.json"):
        self.path = pathlib.Path(path)
        self.data = {"age_groups": [], "crews_by_age": {}}
        self.load()
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
    def get_age_groups(self) -> List[str]:
        return list(self.data.get("age_groups", []))
    def get_crews(self, age_group: str) -> List[str]:
        return list(self.data.get("crews_by_age", {}).get(age_group, []))
    def set_age_groups(self, groups: List[str]):
        self.data["age_groups"] = groups
        cba = self.data.setdefault("crews_by_age", {})
        for g in groups:
            cba.setdefault(g, [])
        for g in list(cba.keys()):
            if g not in groups:
                del cba[g]
        self.save()
    def add_crew(self, age_group: str, crew: str):
        cba = self.data.setdefault("crews_by_age", {})
        lst = cba.setdefault(age_group, [])
        if crew and crew not in lst:
            lst.append(crew)
            lst.sort(key=lambda x: x.lower())
            self.save()
    def remove_crew(self, age_group: str, crew: str):
        cba = self.data.setdefault("crews_by_age", {})
        lst = cba.setdefault(age_group, [])
        if crew in lst:
            lst.remove(crew)
            self.save()

cfg = ConfigManager("config.json")

class CSVBackend:
    def __init__(self, path: str = "data.csv"):
        self.path = path
        if not pathlib.Path(self.path).exists():
            df = pd.DataFrame(columns=["timestamp","round","age_group","crew","judge", *CATEGORIES, "TotalWeighted"])
            df.to_csv(self.path, index=False)
    def load(self) -> pd.DataFrame:
        try:
            df = pd.read_csv(self.path)
            if "TotalWeighted" not in df.columns: df["TotalWeighted"] = 0
            if "age_group" not in df.columns: df["age_group"] = ""
            return df
        except Exception:
            return pd.DataFrame(columns=["timestamp","round","age_group","crew","judge", *CATEGORIES, "TotalWeighted"])
    def _compute_weighted(self, row: Dict) -> int:
        return int(sum((row.get(c,0) or 0) * (2 if c in DOUBLE_CATS else 1) for c in CATEGORIES))
    def upsert_row(self, key_cols: List[str], row: Dict):
        row = dict(row)
        row["TotalWeighted"] = self._compute_weighted(row)
        df = self.load()
        if df.empty:
            df = pd.DataFrame([row])
        else:
            mask = pd.Series([True]*len(df))
            for k in key_cols: mask = mask & (df[k] == row[k])
            if mask.any():
                idx = mask[mask].index[0]
                for k,v in row.items(): df.at[idx, k] = v
            else:
                df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        df.to_csv(self.path, index=False)

def compute_leaderboard(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Rank","Crew","Judges","Total","Tens","DoubleCatSum","MedianJudge","MaxJudge"])
    for c in CATEGORIES:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    df["JudgeTotal"] = sum(df[c] * (2 if c in DOUBLE_CATS else 1) for c in CATEGORIES)
    df["TensHere"] = df.apply(lambda r: sum(1 for c in CATEGORIES if r[c]==10), axis=1)
    df["DoubleHere"] = df.apply(lambda r: sum(r[c] for c in DOUBLE_CATS), axis=1)
    agg = df.groupby("crew", as_index=False).agg(
        Judges=("JudgeTotal","count"),
        Total=("JudgeTotal","sum"),
        Tens=("TensHere","sum"),
        DoubleCatSum=("DoubleHere","sum"),
        MedianJudge=("JudgeTotal","median"),
        MaxJudge=("JudgeTotal","max")
    ).rename(columns={"crew":"Crew"})
    agg = agg.sort_values(by=["Total","Tens","DoubleCatSum","MedianJudge","MaxJudge","Crew"],
                          ascending=[False,False,False,False,False,True], kind="mergesort").reset_index(drop=True)
    agg.insert(0,"Rank",agg.index+1)
    return agg

def get_locked_judge() -> Optional[str]:
    params = st.query_params
    j = params.get("judge", [None])[0]
    pin = params.get("pin", [None])[0]
    if not j: return None
    if JUDGE_PINS:
        expected = JUDGE_PINS.get(j)
        if expected is None or pin != expected:
            st.error("Falscher oder fehlender PIN für diesen Juror.")
            return None
    return j

def is_orga_mode() -> bool:
    params = st.query_params
    val = params.get("orga", [None])[0]
    pin = params.get("orgapin", [None])[0]
    if val not in ("1","true","True"): return False
    if ORGA_PIN: return pin == ORGA_PIN
    return True

st.set_page_config(page_title="JDC Evaluation Tool", page_icon="🧮", layout="wide")
st.title("🧮 JDC Evaluation Tool")

st.sidebar.header("Setup / Regeln")
finalists_n = st.sidebar.selectbox("Direkt ins Finale (Top N)", [5,6,7], index=0)
judges_list = [j.strip() for j in st.sidebar.text_input("Juroren (kommagetrennt)", "J1,J2,J3,J4,J5").split(",") if j.strip()]

age_groups = cfg.get_age_groups()
backend = CSVBackend("data.csv")
locked_judge = get_locked_judge()
if locked_judge and locked_judge not in judges_list: judges_list.append(locked_judge)

with st.sidebar.expander("Juroren-Links"):
    st.write("Nutze `?judge=NAME` (optional `&pin=XXXX`).")
    for j in judges_list: st.code(f"?judge={j}", language="")

tabs = st.tabs(["Bewerten", "Leaderboard", "Daten & Export", "Orga"])

with tabs[0]:
    st.subheader("Bewertung abgeben")
    col0, col1, col2, col3 = st.columns([1,1,1,1])
    with col0: age_group = st.selectbox("Alterskategorie", age_groups, index=0 if age_groups else None)
    with col1: round_choice = st.radio("Runde", ["1", "ZW"], horizontal=True)
    with col2:
        if locked_judge:
            st.text_input("Juror (fixiert)", locked_judge, disabled=True)
            judge = locked_judge
        else:
            judge = st.selectbox("Juror", judges_list)
    with col3: timestamp = dt.datetime.now().isoformat(timespec="seconds")
    crews_for_age = cfg.get_crews(age_group) if age_group else []
    crew_mode = st.radio("Crew-Eingabe", ["Aus Liste wählen", "Andere (manuell)"], horizontal=True)
    if crew_mode == "Aus Liste wählen":
        crew = st.selectbox("Crew", crews_for_age) if crews_for_age else st.text_input("Crew (Liste leer)", "")
    else:
        crew = st.text_input("Crew (manuell)", "").strip()
    st.markdown("### Kategorien (1–10)")
    nums = {c: st.number_input(c, min_value=1, max_value=10, value=7, step=1) for c in CATEGORIES}
    if st.button("Speichern / Aktualisieren", type="primary", disabled=(not crew or not judge or not age_group)):
        row = {"timestamp": timestamp, "round": round_choice, "age_group": age_group, "crew": crew.strip(), "judge": judge}
        for c in CATEGORIES: row[c] = int(nums.get(c, 0))
        backend.upsert_row(["round","age_group","crew","judge"], row)
        st.success(f"Bewertung gespeichert: {crew} ({age_group}), Runde {round_choice}, Juror {judge}.")

with tabs[1]:
    st.subheader("Leaderboard")
    df_all = backend.load()
    colf1, colf2 = st.columns([1,3])
    with colf1:
        round_view = st.radio("Runde", ["1", "ZW"], horizontal=True, key="round_view")
        age_opts = sorted(df_all["age_group"].dropna().unique().tolist()) if not df_all.empty else []
        age_view = st.selectbox("Alterskategorie", age_opts, index=0 if age_opts else None)
    df_view = df_all[(df_all["round"] == round_view) & (df_all["age_group"] == age_view)] if (not df_all.empty and age_view) else pd.DataFrame()
    board = compute_leaderboard(df_view.copy())
    st.dataframe(board, use_container_width=True)
    if round_view == "1" and not board.empty:
        finalists = board.head(finalists_n); rest = board.iloc[finalists_n:]
        st.markdown(f"**Direkt im Finale (Top {finalists_n}) – {age_view}**")
        st.dataframe(finalists[["Rank","Crew","Total","Judges"]], use_container_width=True)
        if not rest.empty:
            st.markdown(f"**Zwischenrunde ({age_view})**")
            st.dataframe(rest[["Rank","Crew","Total","Judges"]], use_container_width=True)
    if round_view == "ZW" and not board.empty:
        winner = board.iloc[0]
        st.markdown(f"🏆 **Sieger Zwischenrunde ({age_view})**: **{winner['Crew']}** (Total {int(winner['Total'])}) → **Finale**")

with tabs[2]:
    st.subheader("Daten & Export")
    df_all = backend.load()
    st.markdown("**Alle Rohdaten (inkl. Alterskategorie & Gesamtpunktzahl pro Vote)**")
    st.dataframe(df_all, use_container_width=True)
    csv_bytes = df_all.to_csv(index=False).encode("utf-8")
    st.download_button("CSV herunterladen", data=csv_bytes, file_name="scores_export.csv", mime="text/csv")
    st.markdown("**Offline-Import (CSV)** – lade hier die CSV aus dem Offline-Formular hoch:")
    up = st.file_uploader("CSV-Datei wählen", type=["csv"])
    if up is not None:
        try:
            imp = pd.read_csv(up)
            needed = {"timestamp","round","age_group","crew","judge", *CATEGORIES}
            if not needed.issubset(set(imp.columns)):
                st.error("CSV enthält nicht die erwarteten Spalten.")
            else:
                count = 0
                for _,r in imp.iterrows():
                    row = {k: r.get(k, "") for k in ["timestamp","round","age_group","crew","judge"]}
                    for c in CATEGORIES:
                        row[c] = int(pd.to_numeric(r.get(c, 0), errors="coerce") or 0)
                    backend.upsert_row(["round","age_group","crew","judge"], row)
                    count += 1
                st.success(f"{count} Bewertungen importiert und zusammengeführt.")
        except Exception as e:
            st.error(f"Import fehlgeschlagen: {e}")

with tabs[3]:
    st.subheader("Orga")
    def is_orga_mode() -> bool:
        params = st.query_params
        val = params.get("orga", [None])[0]
        pin = params.get("orgapin", [None])[0]
        if val not in ("1","true","True"): return False
        if ORGA_PIN: return pin == ORGA_PIN
        return True
    if not is_orga_mode():
        st.info("Orga-Modus aktivieren: URL mit `?orga=1` (optional `&orgapin=XXXX`).")
    else:
        st.success("Orga-Modus aktiv.")
        st.markdown("### Alterskategorien & Crews verwalten")
        groups_str = st.text_input("Alterskategorien (kommagetrennt)", ",".join(cfg.get_age_groups()))
        if st.button("Speichern (Kategorien)"):
            groups = [g.strip() for g in groups_str.split(",") if g.strip()]
            if groups:
                cfg.set_age_groups(groups)
                st.success("Alterskategorien gespeichert – Seite neu laden.")
        ag = st.selectbox("Alterskategorie auswählen", cfg.get_age_groups())
        if ag:
            st.write(f"Aktuelle Crews in **{ag}**:")
            current = cfg.get_crews(ag)
            st.dataframe(pd.DataFrame({"Crew": current}), use_container_width=True)
            new_crew = st.text_input("Neue Crew hinzufügen", "")
            if st.button("+ Hinzufügen", disabled=not new_crew.strip()):
                cfg.add_crew(ag, new_crew.strip())
                st.success(f"Crew '{new_crew.strip()}' hinzugefügt. Seite neu laden.")
            if current:
                del_target = st.selectbox("Crew entfernen", ["—"] + current)
                if del_target != "—" and st.button("Entfernen"):
                    cfg.remove_crew(ag, del_target)
                    st.success(f"Crew '{del_target}' entfernt. Seite neu laden.")
        st.markdown("---")
        st.markdown("### Orga-Backup-Bewertung (nur Notfall)")
        col0, col1, col2 = st.columns([1,1,1])
        with col0: age_group2 = st.selectbox("Alterskategorie (Orga)", cfg.get_age_groups(), key="age_group_org")
        with col1: round_choice2 = st.radio("Runde (Orga)", ["1","ZW"], horizontal=True, key="round_org")
        with col2: judge2 = st.selectbox("Juror (Orga)", judges_list, key="judge_org")
        crew2 = st.text_input("Crew (Orga – manuell oder aus Liste)")
        nums2 = {c: st.number_input(f"{c} (Orga)", min_value=1, max_value=10, value=7, step=1, key=f"org_{c}") for c in CATEGORIES}
        if st.button("Orga-Bewertung speichern"):
            row = {"timestamp": dt.datetime.now().isoformat(timespec="seconds"),
                   "round": round_choice2, "age_group": age_group2, "crew": crew2.strip(), "judge": judge2}
            for c in CATEGORIES: row[c] = int(nums2.get(c, 0))
            backend.upsert_row(["round","age_group","crew","judge"], row)
            st.success("Orga-Bewertung gespeichert.")
