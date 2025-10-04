
# app.py (JDC evaluation tool v3)
import streamlit as st
import pandas as pd
import datetime as dt
from typing import List, Dict, Optional
import pathlib, json

BASE_URL = st.secrets.get("base_url", "https://<YOUR-APP>.streamlit.app")

CATEGORIES = ["Synchronität","Schwierigkeit der Choreographie","Choreographie","Bilder und Linien","Ausdruck und Bühnenpräsenz"]
DOUBLE_CATS = ["Synchronität","Schwierigkeit der Choreographie"]

# ---------------- Config (age groups, crews, start numbers, jurors) ----------------
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
            # assign in order if missing
            for i, crew in enumerate(crews, start=1):
                m.setdefault(crew, i)
            # remove stale
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
        if not new or old == new: return
        crews = self.data.setdefault("crews_by_age", {}).setdefault(age_group, [])
        if old in crews and new not in crews:
            idx = crews.index(old)
            crews[idx] = new
            # preserve start number mapping
            sn = self.data.setdefault("start_numbers", {}).setdefault(age_group, {})
            sn[new] = sn.get(old, sn.get(new, None)) or (idx+1)
            if old in sn: del sn[old]
            self.save()

    # ----- jurors -----
    def get_jurors(self) -> List[Dict]:
        return list(self.data.get("jurors", []))

    def set_jurors(self, jurors: List[Dict]):
        # normalize and de-duplicate by name
        clean = []
        seen = set()
        for j in jurors:
            name = (j.get("name") or "").strip()
            pin  = str(j.get("pin") or "").strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                clean.append({"name": name, "pin": pin})
        self.data["jurors"] = clean
        self.save()

cfg = ConfigManager("config.json")

# ---------------- Secrets precedence for PINs ----------------
# 1) Secrets judge_pins override config pins
# 2) Config pins otherwise used
# 3) (No fallback hardcoded here; config ships with defaults)

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

ORGA_PIN = st.secrets.get("orga_pin", "") or ""  # optionally set via secrets

# ---------------- Storage ----------------
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

backend = CSVBackend("data.csv")

# ---------------- Helpers ----------------
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
    if not j:
        return None
    expected = JUDGE_PINS.get(j)
    if expected is None or pin != expected:
        st.error("Falscher oder fehlender PIN für diesen Juror.")
        return None
    return j

def is_orga_mode() -> bool:
    params = st.query_params
    val = params.get("orga", [None])[0]
    pin = params.get("orgapin", [None])[0]
    if val not in ("1","true","True"):
        return False
    # Accept either secrets OR, if empty, a config-defined orga pin (optional)
    orga_pin_config = st.secrets.get("orga_pin", "")
    return (pin == orga_pin_config) if orga_pin_config else bool(pin)

def reset_vote_state():
    for c in CATEGORIES:
        st.session_state[f"cat_{c}"] = '—'

# ---------------- UI ----------------
st.set_page_config(page_title="JDC Scoring 2026", page_icon="🧮", layout="wide")
st.title("🧮 JDC Scoring 2026")

locked_judge = get_locked_judge()
if locked_judge:
    st.success(f"Hallo {locked_judge} 👋 – deine Seite ist personalisiert.")
else:
    st.info("Tipp: Verwende personalisierte Links: ?judge=Name&pin=XXXX.")

st.sidebar.header("Setup / Regeln")
finalists_n = st.sidebar.selectbox("Direkt ins Finale (Top N)", [5,6,7], index=0)

# -------- Full Links in sidebar (with names, not 'j') --------
with st.sidebar.expander("Links (vollständige URLs)"):
    # Orga full link (if orga_pin in secrets)
    orga_pin = st.secrets.get("orga_pin", "")
    if orga_pin:
        st.write("Orga:")
        st.code(f"{BASE_URL}/?orga=1&orgapin={orga_pin}")
    st.write("Jury:")
    for name, pin in JUDGE_PINS.items():
        st.code(f"{BASE_URL}/?judge={name}&pin={pin}")

age_groups = cfg.get_age_groups()

tabs = st.tabs(["Bewerten", "Leaderboard", "Daten & Export", "Orga"])

# ---------- Bewerten ----------
with tabs[0]:
    st.subheader("Bewertung abgeben")
    col0, col1, col2 = st.columns([1,1,1])
    with col0:
        age_group = st.selectbox("Alterskategorie", age_groups, index=0 if age_groups else None, key="age_group_sel")
    with col1:
        crews_for_age = cfg.get_crews(age_group) if age_group else []
        crew = st.selectbox("Crew", crews_for_age, index=0 if crews_for_age else None, key="crew_sel")
    with col2:
        round_choice = st.radio("Runde", ["1", "ZW"], horizontal=True, key="round_sel")

    # Reset scores on crew change
    if "last_crew" not in st.session_state:
        st.session_state["last_crew"] = ""
    if crew != st.session_state["last_crew"]:
        reset_vote_state()
        st.session_state["last_crew"] = crew

    st.markdown("### Kategorien (bitte jede Kategorie auswählen)")
    options = ['—'] + [str(i) for i in range(1,11)]
    values = {}
    for c in CATEGORIES:
        key = f"cat_{c}"
        if key not in st.session_state:
            st.session_state[key] = '—'
        values[c] = st.selectbox(c, options, index=options.index(st.session_state[key]) if st.session_state[key] in options else 0, key=key)

    if not locked_judge:
        st.warning("Bitte öffne deinen persönlichen Link (mit PIN).")
    all_set = locked_judge is not None and crew and age_group and all(v != '—' for v in values.values())

    if st.button("Speichern / Aktualisieren", type="primary", disabled=not all_set):
        row = {"timestamp": dt.datetime.now().isoformat(timespec="seconds"),
                "round": round_choice,
                "age_group": age_group,
                "crew": crew,
                "judge": locked_judge}
        for c in CATEGORIES:
            row[c] = int(values[c])
        backend.upsert_row(["round","age_group","crew","judge"], row)
        st.success(f"Bewertung gespeichert: {crew} (Startnr. {cfg.get_start_no(age_group, crew)}), {age_group}, Runde {round_choice}, Juror {locked_judge}.")
        reset_vote_state()

# ---------- Leaderboard ----------
with tabs[1]:
    st.subheader("Leaderboard")
    df_all = backend.load()
    colf1, colf2 = st.columns([1,2])
    with colf1:
        round_view = st.radio("Runde", ["1","ZW"], horizontal=True, key="round_view")
        age_opts = age_groups
        age_view = st.selectbox("Alterskategorie", age_opts, index=0 if age_opts else None, key="age_view")
    if not df_all.empty and age_view:
        df_view = df_all[(df_all["round"]==round_view) & (df_all["age_group"]==age_view)].copy()
    else:
        df_view = pd.DataFrame()
    if not df_view.empty:
        df_view["Startnummer"] = df_view["crew"].map(lambda x: cfg.get_start_no(age_view, x))
    board = compute_leaderboard(df_view.copy())
    st.dataframe(board, use_container_width=True)
    if round_view=="1" and not board.empty:
        finalists = board.head(finalists_n); rest = board.iloc[finalists_n:]
        st.markdown(f"**Direkt im Finale (Top {finalists_n}) – {age_view}**")
        st.dataframe(finalists[["Rank","Crew","Total","Judges"]], use_container_width=True)
        if not rest.empty:
            st.markdown(f"**Zwischenrunde ({age_view})**")
            st.dataframe(rest[["Rank","Crew","Total","Judges"]], use_container_width=True)
    if round_view=="ZW" and not board.empty:
        winner = board.iloc[0]
        st.markdown(f"🏆 **Sieger Zwischenrunde ({age_view})**: **{winner['Crew']}** (Total {int(winner['Total'])}) → **Finale**")

# ---------- Daten & Export ----------
with tabs[2]:
    st.subheader("Daten & Export")
    df_all = backend.load()
    if not df_all.empty:
        age_filter = st.selectbox("Alterskategorie filtern", ["Alle"] + age_groups, index=0, key="raw_age_filter")
        if age_filter != "Alle":
            df_all = df_all[df_all["age_group"]==age_filter]
        df_all["Startnummer"] = df_all.apply(lambda r: cfg.get_start_no(r["age_group"], r["crew"]), axis=1)
        sort_by = st.selectbox("Sortieren nach", ["Startnummer","timestamp","TotalWeighted"], index=0, key="raw_sort_by")
        ascending = st.checkbox("Aufsteigend sortieren", value=True)
        df_all = df_all.sort_values(by=sort_by, ascending=ascending, kind="mergesort")
    st.dataframe(df_all, use_container_width=True)
    csv_bytes = df_all.to_csv(index=False).encode("utf-8")
    st.download_button("CSV herunterladen", data=csv_bytes, file_name="scores_export.csv", mime="text/csv")

# ---------- Orga ----------
with tabs[3]:
    st.subheader("Orga")
    def is_orga_mode() -> bool:
        params = st.query_params
        val = params.get("orga", [None])[0]
        pin = params.get("orgapin", [None])[0]
        orga_pin_secret = st.secrets.get("orga_pin", "")
        if val not in ("1","true","True"): return False
        return (pin == orga_pin_secret) if orga_pin_secret else bool(pin)

    if not is_orga_mode():
        st.info("Orga-Modus aktivieren: URL mit `?orga=1&orgapin=XXXX`.")
    else:
        st.success("Orga-Modus aktiv.")

        # ---- Juroren verwalten (Namen + PINs) ----
        st.markdown("### Juroren verwalten (Namen & PINs)")
        jur_df = pd.DataFrame(cfg.get_jurors())
        if jur_df.empty:
            st.warning("Noch keine Juroren in der Config. Füge neue hinzu.")
        st.dataframe(jur_df, use_container_width=True)
        with st.form("add_juror"):
            colj1, colj2 = st.columns([2,1])
            with colj1: new_jname = st.text_input("Name")
            with colj2: new_jpin  = st.text_input("PIN (4-stellig)", max_chars=4)
            submitted = st.form_submit_button("+ Juror hinzufügen")
            if submitted and new_jname.strip() and new_jpin.strip():
                new_list = cfg.get_jurors() + [{"name": new_jname.strip(), "pin": new_jpin.strip()}]
                cfg.set_jurors(new_list)
                st.success("Juror hinzugefügt. Seite neu laden.")
        # Rename juror
        if not jur_df.empty:
            with st.form("rename_juror"):
                rcol1, rcol2, rcol3 = st.columns([2,2,1])
                with rcol1: old_j = st.selectbox("Juror auswählen", jur_df["name"].tolist())
                with rcol2: new_j = st.text_input("Neuer Name")
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
        # Remove juror
        if not jur_df.empty:
            with st.form("remove_juror"):
                dcol1, dcol2 = st.columns([3,1])
                with dcol1: del_j = st.selectbox("Juror entfernen", ["—"] + jur_df["name"].tolist())
                submitted = st.form_submit_button("Entfernen")
                if submitted and del_j != "—":
                    updated = [j for j in cfg.get_jurors() if j["name"] != del_j]
                    cfg.set_jurors(updated)
                    st.success("Juror entfernt. Seite neu laden.")

        st.markdown("---")
        # ---- Alterskategorien & Crews ----
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
            df_crews = pd.DataFrame({"Startnummer":[cfg.get_start_no(ag,c) for c in current], "Crew": current}).sort_values("Startnummer")
            st.dataframe(df_crews, use_container_width=True)
            # Add
            new_crew = st.text_input("Neue Crew hinzufügen", "", key="orga_newcrew")
            if st.button("+ Hinzufügen", disabled=not new_crew.strip()):
                cfg.add_crew(ag, new_crew.strip())
                st.success(f"Crew '{new_crew.strip()}' hinzugefügt. Seite neu laden.")
            # Rename
            if current:
                with st.form("rename_crew"):
                    rc1, rc2 = st.columns([2,2])
                    with rc1: oldc = st.selectbox("Crew umbenennen", current)
                    with rc2: newc = st.text_input("Neuer Name")
                    submitted = st.form_submit_button("Umbenennen")
                    if submitted and oldc and newc.strip():
                        cfg.rename_crew(ag, oldc, newc.strip())
                        st.success("Crew umbenannt. Seite neu laden.")
            # Remove
            if current:
                with st.form("remove_crew"):
                    dc1, dc2 = st.columns([3,1])
                    with dc1: delc = st.selectbox("Crew entfernen", ["—"] + current)
                    submitted = st.form_submit_button("Entfernen")
                    if submitted and delc != "—":
                        cfg.remove_crew(ag, delc)
                        st.success("Crew entfernt. Seite neu laden.")

        st.markdown("---")
        st.markdown("### Orga-Backup-Bewertung (nur Notfall)")
        # Use juror names from config
        juror_names = [j["name"] for j in cfg.get_jurors()]
        col0, col1, col2 = st.columns([1,1,1])
        with col0: age_group2 = st.selectbox("Alterskategorie (Orga)", cfg.get_age_groups(), key="age_group_org")
        with col1: round_choice2 = st.radio("Runde (Orga)", ["1","ZW"], horizontal=True, key="round_org")
        with col2: judge2 = st.selectbox("Juror (Orga)", juror_names, key="judge_org")
        crew2 = st.text_input("Crew (Orga – manuell oder aus Liste)")
        nums2 = {}
        for c in CATEGORIES:
            nums2[c] = st.selectbox(f"{c} (Orga)", ['—'] + [str(i) for i in range(1,11)], key=f"org_{c}")
        all_set_org = crew2.strip() and age_group2 and all(v!='—' for v in nums2.values())
        if st.button("Orga-Bewertung speichern", disabled=not all_set_org):
            row = {"timestamp": dt.datetime.now().isoformat(timespec="seconds"),
                   "round": round_choice2, "age_group": age_group2, "crew": crew2.strip(), "judge": judge2}
            for c in CATEGORIES: row[c] = int(nums2[c])
            backend.upsert_row(["round","age_group","crew","judge"], row)
            st.success("Orga-Bewertung gespeichert.")
