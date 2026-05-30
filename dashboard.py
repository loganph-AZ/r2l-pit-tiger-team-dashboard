import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import json
import os
import re

# Page config
st.set_page_config(
    page_title="R2L PIT Tiger Team Data",
    page_icon="🐯",
    layout="wide"
)

st.title("🐯 R2L PIT Tiger Team Data")

# Print/PDF button and Up To Date info in top right
col_title, col_date, col_print = st.columns([4, 2, 1])
with col_date:
    # Find the most recent incident date across all data
    @st.cache_data
    def get_latest_date():
        nm = pd.read_csv("Near Miss Data.csv")
        nm_date = pd.to_datetime(nm["nearmiss_date"], errors="coerce").max()
        inc = pd.read_csv("PIT Incident Data.csv")
        inc_date = pd.to_datetime(inc["incident_date"], errors="coerce").max()
        fe = pd.read_csv("Fire Events.csv")
        fe_date = pd.to_datetime(fe["incident_date"], errors="coerce").max()
        latest = max([d for d in [nm_date, inc_date, fe_date] if pd.notna(d)])
        return latest.strftime("%m/%d/%Y")
    st.markdown(f"**Up To Date Until:** {get_latest_date()}")
with col_print:
    if st.button("📄 Print / PDF"):
        st.components.v1.html(
            "<script>window.parent.print();</script>",
            height=0
        )

# --- VERIFICATION FILE (persists decisions) ---
VERIFIED_FILE = "verified_flags.json"

def load_verified():
    if os.path.exists(VERIFIED_FILE):
        with open(VERIFIED_FILE, "r") as f:
            return json.load(f)
    return {"valid": [], "not_valid": []}

def save_verified(data):
    with open(VERIFIED_FILE, "w") as f:
        json.dump(data, f)

# Load data
@st.cache_data
def load_data():
    df = pd.read_csv("Near Miss Data.csv")
    df["nearmiss_date"] = pd.to_datetime(df["nearmiss_date"], errors="coerce")
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df["date_reported"] = pd.to_datetime(df["date_reported"], errors="coerce")
    return df

df = load_data()

# --- SITE TYPE CLASSIFICATION ---
SSD_DC_SITES = ["HDC3", "HGA6", "HIL3", "HLA6", "HMD3", "HMW3", "HNE1", "HPA1", "HTX3"]

def classify_site_type(site):
    if site in SSD_DC_SITES:
        return "SSD-DC"
    else:
        return "SSD-FC"

df["site_category"] = df["site"].apply(classify_site_type)

# Filter to only PIT and Fire near miss types
ALLOWED_NEARMISS_TYPES = ["PIT", "Fire"]
df = df[df["initial_info_nearmiss_type"].isin(ALLOWED_NEARMISS_TYPES)]


# ============================================================
# FLAGGING FUNCTION
# ============================================================
def is_flagged(description):
    """Check if a near miss description indicates it should be an incident. Returns (reason, keyword) or None."""
    if pd.isna(description):
        return None
    desc = description.lower()

    # PIT making contact with a pedestrian
    pedestrian_keywords = [
        "struck a pedestrian", "hit a pedestrian", "contact with a pedestrian",
        "struck an associate", "hit an associate", "contact with an associate",
        "struck the associate", "hit the associate", "struck aa",
        "hitting a pedestrian", "hitting an associate", "struck a aa",
        "pedestrian was struck", "pedestrian was hit",
        "made contact with a pedestrian", "made contact with an associate",
        "contact with aa", "struck the aa", "hit the aa",
        "hit a person", "struck a person"
    ]

    # Exclude pedestrian flag if no actual contact was made
    no_contact_pedestrian = [
        "almost struck", "nearly struck", "almost hit", "nearly hit",
        "no contact", "close call"
    ]

    # Loss of product
    product_loss_keywords = [
        "loss of product", "product damaged", "product loss",
        "damaged product", "damaged the product", "damaged cases",
        "damaged boxes", "damaged the cases", "damaged the boxes"
    ]

    # Damage to equipment or structure
    damage_keywords = [
        "damage to", "damaged the", "damaged a", "damaged rack",
        "damaged guard", "damaged railing", "damaged door",
        "damaged wall", "damaged column", "damaged sprinkler",
        "structural damage", "rack damage",
        "broke the", "broken rack", "broken guard", "broken railing",
        "cracked the", "bent the", "dented the", "punctured the",
        "destroyed the", "shattered the", "ripped the", "tore the",
        "causing damage", "resulted in damage", "visible damage"
    ]

    # PIT making contact with another PIT while both are being driven
    pit_on_pit_keywords = [
        "pit on pit", "pit-on-pit", "collided with another op",
        "collided with another pit", "struck another op",
        "struck another pit", "hit another op", "hit another pit",
        "contact with another op", "contact with another pit",
        "two ops collided", "two pits collided", "op collided with op",
        "t-boned", "t boned", "tboned", "rear-ended", "rear ended",
        "collided with the other op", "struck the other op",
        "hit the other op", "made contact with another op"
    ]

    for kw in pit_on_pit_keywords:
        if kw in desc:
            # Exclude if the other PIT was parked
            parked_keywords = ["parked op", "parked pit", "op that was parked",
                               "pit that was parked", "was parked next",
                               "parked beside", "parked next to"]
            is_parked = any(pk in desc for pk in parked_keywords)
            if is_parked:
                break

            # Exclude if no contact was actually made
            no_contact_keywords = [
                "no contact", "almost struck", "nearly struck",
                "almost hit", "nearly hit", "almost collided",
                "nearly collided", "close call", "near miss"
            ]
            is_no_contact = any(nc in desc for nc in no_contact_keywords)
            if is_no_contact:
                break

            # Must explicitly indicate both were moving
            both_moving_keywords = [
                "both traveling", "both driving", "both moving",
                "both operating", "both were traveling", "both were driving",
                "both were moving", "both were operating",
                "traveling in opposite", "traveling the same",
                "heading toward", "heading towards",
                "oncoming", "coming from the opposite",
                "pit on pit", "pit-on-pit"
            ]
            is_both_moving = any(mk in desc for mk in both_moving_keywords)
            if is_both_moving:
                return ("PIT-on-PIT contact (both driven)", kw)
            break

    for kw in pedestrian_keywords:
        if kw in desc:
            # Exclude if no actual contact was made
            if any(nc in desc for nc in no_contact_pedestrian):
                break
            return ("PIT contact with pedestrian", kw)
    for kw in product_loss_keywords:
        if kw in desc:
            return ("Loss of product", kw)
    for kw in damage_keywords:
        if kw in desc:
            # Exclude if the ONLY damage references are negated
            if "no damage" in desc or "no significant damage" in desc or "no visible damage" in desc or "no major damage" in desc or "no structural damage" in desc or "no structural damaged" in desc:
                cleaned = re.sub(r'no \w* ?damage\w*[^.;,]*', '', desc)
                cleaned = re.sub(r'no damage\w*[^.;,]*', '', cleaned)
                has_positive_damage = any(dkw in cleaned for dkw in damage_keywords)
                if not has_positive_damage:
                    break

            # Exclude if the damage is only to pallets
            pallet_only_patterns = [
                "damage to the pallet", "damage to a pallet", "damage to pallets",
                "damage to the wooden pallet", "damage to a wooden pallet",
                "damaged the pallet", "damaged a pallet", "damaged pallets",
                "damaged the wooden pallet", "damaged a wooden pallet",
                "broke the pallet", "broken pallet", "cracked the pallet",
                "bent the pallet", "dented the pallet", "punctured the pallet",
                "destroyed the pallet", "pallet damage", "pallet was damaged",
                "pallets were damaged", "damage to the wooden pallet",
                "resulted in damage to the wooden pallet",
                "resulted in damage to the pallet",
                "resulted in damage to a pallet"
            ]
            is_pallet_only = False
            for pk in pallet_only_patterns:
                if pk in desc:
                    is_pallet_only = True
                    break
            if is_pallet_only:
                desc_check = desc
                for pk in pallet_only_patterns:
                    desc_check = desc_check.replace(pk, "")
                has_other_damage = False
                for dkw in damage_keywords:
                    if dkw in desc_check:
                        has_other_damage = True
                        break
                if not has_other_damage:
                    break
            else:
                return ("Damage to equipment/structure", kw)

    return None


# --- PAGE SELECTOR ---
active_page = st.selectbox(
    "Dashboard View",
    ["📊 All PIT Incidents", "⚠️ PIT Incidents", "🚜 PIT Near Misses", "🚩 Flagged Near Misses", "🔥 Thermal Events"]
)


# ============================================================
# All PIT Incidents (Combined)
# ============================================================
if active_page == "📊 All PIT Incidents":
    # Load and normalize Near Miss data
    @st.cache_data
    def load_combined():
        # Near miss data
        nm = pd.read_csv("Near Miss Data.csv")
        nm["incident_date"] = pd.to_datetime(nm["nearmiss_date"], errors="coerce")
        nm["created_at"] = pd.to_datetime(nm["created_at"], errors="coerce")
        nm["incident_time_raw"] = nm["nearmiss_time"]
        nm["process_path"] = nm["initial_info_process_path"]
        nm["location_raw"] = nm["initial_info_location_event"]
        nm["description"] = nm["initial_info_incident_description"]
        nm["record_type"] = "Near Miss"
        nm_pit = nm[nm["initial_info_nearmiss_type"] == "PIT"]

        # PIT Incident data
        inc = pd.read_csv("PIT Incident Data.csv")
        inc["incident_date"] = pd.to_datetime(inc["incident_date"], errors="coerce")
        inc["created_at"] = pd.to_datetime(inc["created_at"], errors="coerce")
        inc["incident_time_raw"] = inc["incident_time"]
        inc["process_path"] = inc["initial_info_pit_process"]
        inc["location_raw"] = inc["initial_info_incident_location"]
        inc["description"] = inc["initial_info_incident_description"]
        inc["record_type"] = "Incident"

        # Common columns
        common_cols = ["site", "incident_date", "created_at", "incident_time_raw",
                       "process_path", "location_raw", "description", "record_type",
                       "initial_info_pit_type"]

        # Add pit_type column to near miss (doesn't have it)
        nm_pit["initial_info_pit_type"] = None

        nm_subset = nm_pit[[c for c in common_cols if c in nm_pit.columns]].copy()
        inc_subset = inc[[c for c in common_cols if c in inc.columns]].copy()

        combined = pd.concat([nm_subset, inc_subset], ignore_index=True)
        return combined

    cdf = load_combined()

    # Site type classification
    cdf["site_category"] = cdf["site"].apply(classify_site_type)

    # PIT incident type from description
    def classify_combined_incident_type(desc):
        if pd.isna(desc):
            return "Other/Unknown"
        d = desc.lower()
        ped_kw = ["pedestrian", "struck an associate", "hit an associate",
                  "struck the associate", "hit the associate", "struck aa",
                  "contact with an associate", "contact with a pedestrian",
                  "made contact with an associate", "made contact with a pedestrian"]
        pit_kw = ["pit on pit", "pit-on-pit", "another op", "another pit",
                  "other op", "other pit", "two ops", "two pits",
                  "op collided", "pit collided", "t-boned", "t boned",
                  "rear-ended", "rear ended", "op that was parked",
                  "parked op", "parked pit", "adjacent op", "neighboring op"]
        struct_kw = ["rack", "racking", "guard", "pillar", "column", "wall",
                     "door", "bollard", "barrier", "post", "beam", "structure",
                     "vna", "aisle", "sprinkler", "ceiling", "overhead",
                     "dock", "gate", "fence", "rail", "railing", "upright"]
        prod_kw = ["pallet", "product", "box", "case", "tote", "package",
                   "load", "freight", "cargo", "bin", "carton", "inventory"]
        for kw in ped_kw:
            if kw in d:
                return "PIT/Pedestrian"
        for kw in pit_kw:
            if kw in d:
                return "PIT/PIT"
        for kw in struct_kw:
            if kw in d:
                return "PIT/Structure"
        for kw in prod_kw:
            if kw in d:
                return "PIT/Product"
        return "Other/Unknown"

    cdf["pit_incident_type"] = cdf["description"].apply(classify_combined_incident_type)

    # Location cleaning
    cdf["location_clean"] = cdf["location_raw"].apply(
        lambda x: "VNA (Very Narrow Aisle)" if pd.notna(x) and ("vna" in x.lower() or "very narrow aisle" in x.lower())
        else ("PIT Highway" if pd.notna(x) and ("straight" in x.lower() or "drive lane" in x.lower() or "driveway" in x.lower())
        else ("Parking Lot" if pd.notna(x) and ("parking" in x.lower())
        else ("Stow Aisles" if pd.notna(x) and ("stow rack" in x.lower() or "stow aisle" in x.lower()) else x)))
    )

    # PIT equipment type
    def classify_combined_pit_equip(row):
        pt = row.get("initial_info_pit_type")
        desc = str(row.get("description", "")).lower()
        if pd.notna(pt):
            p = pt.lower()
            if any(k in p for k in ["order picker","vop","llop","stock-picker","stock picker","high-level"]):
                return "OP (Order Picker)"
            elif any(k in p for k in ["turret","turrent","vnatr"]):
                return "TT (Turret Truck)"
            elif any(k in p for k in ["center","crpt","center-controlled"]):
                return "Center Rider"
            elif any(k in p for k in ["tugger","tow tractor","tract"]):
                return "Tugger"
            elif any(k in p for k in ["standup","stand-up","counterbalance","cbtr","forklift"]):
                return "SU (Stand Up/Forklift)"
            elif any(k in p for k in ["reach","retr"]):
                return "Reach Truck"
            elif any(k in p for k in ["pallet","rppt","rpps","pedestrian"]):
                return "Pallet Truck"
            elif any(k in p for k in ["boom","cherry","lift"]):
                return "Boom Lift"
            elif any(k in p for k in ["scrubber","flscr"]):
                return "Floor Scrubber"
        # Fallback to description
        if "turret" in desc:
            return "TT (Turret Truck)"
        elif "order picker" in desc or " op " in desc or "their op" in desc or "the op" in desc or "an op" in desc:
            return "OP (Order Picker)"
        elif "center rider" in desc or "epj" in desc:
            return "Center Rider"
        elif "tugger" in desc or "tow motor" in desc:
            return "Tugger"
        elif "stand up" in desc or "standup" in desc or "forklift" in desc or "counterbalance" in desc:
            return "SU (Stand Up/Forklift)"
        elif "reach truck" in desc:
            return "Reach Truck"
        elif "pallet jack" in desc or "pallet truck" in desc:
            return "Pallet Truck"
        return "Unknown"

    cdf["pit_equipment_type"] = cdf.apply(classify_combined_pit_equip, axis=1)

    # Remove non-PIT incidents
    cdf = cdf[cdf["pit_equipment_type"] != "Unknown"]

    # Derived columns
    cdf["day_of_week"] = cdf["incident_date"].dt.day_name()
    cdf["incident_time_parsed"] = pd.to_datetime(cdf["incident_time_raw"], errors="coerce")
    cdf["hour"] = cdf["incident_time_parsed"].dt.hour
    cdf["hour_label"] = cdf["hour"].apply(lambda h: f"{int(h):02d}:00" if pd.notna(h) else None)
    cdf["days_to_report"] = (cdf["created_at"] - cdf["incident_date"]).dt.total_seconds() / 86400
    cdf["report_status"] = cdf["days_to_report"].apply(
        lambda x: "Late Report" if pd.notna(x) and x > 1 else ("Reported On Time" if pd.notna(x) else None)
    )
    cdf["year"] = cdf["incident_date"].dt.year.astype("Int64").astype(str).replace("<NA>", None)
    cdf["month_name"] = cdf["incident_date"].dt.month_name()

    # --- FILTERS (2 rows) ---
    afc1, afc2, afc3, afc4, afc5, afc6 = st.columns(6)
    with afc1:
        a_sel_type = st.multiselect("Record Type", ["Near Miss", "Incident"], default=[], key="all_rectype", placeholder="All")
    with afc2:
        a_sel_cats = st.multiselect("Site Type", sorted(cdf["site_category"].unique()), default=[], key="all_cat", placeholder="All")
    with afc3:
        a_sel_sites = st.multiselect("Site", sorted(cdf["site"].dropna().unique()), default=[], key="all_sites", placeholder="All")
    with afc4:
        a_sel_paths = st.multiselect("Process Path", sorted(cdf["process_path"].dropna().unique()), default=[], key="all_paths", placeholder="All")
    with afc5:
        a_sel_inc_types = st.multiselect("Incident Type", sorted(cdf["pit_incident_type"].unique()), default=[], key="all_inctype", placeholder="All")
    with afc6:
        a_sel_locations = st.multiselect("Location", sorted(cdf["location_clean"].dropna().unique()), default=[], key="all_loc", placeholder="All")

    afc7, afc8, afc9, afc10, afc11, afc12 = st.columns(6)
    with afc7:
        a_sel_equip = st.multiselect("PIT Type", sorted(cdf["pit_equipment_type"].unique()), default=[], key="all_equip", placeholder="All")
    with afc8:
        a_sel_days = st.multiselect("Day of Week", ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"], default=[], key="all_dow", placeholder="All")
    with afc9:
        a_sel_years = st.multiselect("Year", sorted(cdf["year"].dropna().unique()), default=[], key="all_year", placeholder="All")
    with afc10:
        a_sel_months = st.multiselect("Month", ["January","February","March","April","May","June","July","August","September","October","November","December"], default=[], key="all_month", placeholder="All")
    with afc11:
        a_min_date = cdf["incident_date"].min()
        a_max_date = cdf["incident_date"].max()
        if pd.notna(a_min_date) and pd.notna(a_max_date):
            a_date_range = st.date_input("Date Range", value=(a_min_date.date(), a_max_date.date()), min_value=a_min_date.date(), max_value=a_max_date.date(), key="all_date")
        else:
            a_date_range = None
    with afc12:
        a_chart_type = st.selectbox("Chart Style", ["Bar Charts", "Pie Charts"], key="all_chart_type")

    # Reclassify flagged near misses as incidents
    cdf["flag_result"] = cdf["description"].apply(is_flagged)
    cdf["is_flagged"] = cdf["flag_result"].apply(lambda x: True if x else False)
    cdf.loc[(cdf["record_type"] == "Near Miss") & (cdf["is_flagged"]), "record_type"] = "Incident"

    # Apply filters
    a_filtered = cdf.copy()
    if a_sel_type:
        a_filtered = a_filtered[a_filtered["record_type"].isin(a_sel_type)]
    if a_sel_cats:
        a_filtered = a_filtered[a_filtered["site_category"].isin(a_sel_cats)]
    if a_sel_sites:
        a_filtered = a_filtered[a_filtered["site"].isin(a_sel_sites)]
    if a_sel_paths:
        a_filtered = a_filtered[a_filtered["process_path"].isin(a_sel_paths)]
    if a_sel_inc_types:
        a_filtered = a_filtered[a_filtered["pit_incident_type"].isin(a_sel_inc_types)]
    if a_sel_locations:
        a_filtered = a_filtered[a_filtered["location_clean"].isin(a_sel_locations)]
    if a_sel_equip:
        a_filtered = a_filtered[a_filtered["pit_equipment_type"].isin(a_sel_equip)]
    if a_sel_days:
        a_filtered = a_filtered[a_filtered["day_of_week"].isin(a_sel_days)]
    if a_sel_years:
        a_filtered = a_filtered[a_filtered["year"].isin(a_sel_years)]
    if a_sel_months:
        a_filtered = a_filtered[a_filtered["month_name"].isin(a_sel_months)]
    if a_date_range and len(a_date_range) == 2:
        a_filtered = a_filtered[
            (a_filtered["incident_date"].dt.date >= a_date_range[0]) &
            (a_filtered["incident_date"].dt.date <= a_date_range[1])
        ]

    # --- KPI Header ---
    kpi1, kpi2, kpi3 = st.columns(3)
    with kpi1:
        st.metric("Total", len(a_filtered))
    with kpi2:
        st.metric("Incidents", len(a_filtered[a_filtered["record_type"] == "Incident"]))
    with kpi3:
        st.metric("Near Misses", len(a_filtered[a_filtered["record_type"] == "Near Miss"]))

    # --- Row 1: Site + Process Path + Incident Type ---
    r1c1, r1c2, r1c3 = st.columns(3)
    with r1c1:
        st.subheader("Site")
        site_counts = a_filtered["site"].value_counts().reset_index()
        site_counts.columns = ["Site", "Count"]
        if a_chart_type == "Bar Charts":
            fig = px.bar(site_counts.head(15), x="Site", y="Count", text="Count", color_discrete_sequence=["#232F3E"])
            fig.update_traces(textposition="outside")
        else:
            fig = px.pie(site_counts.head(15), values="Count", names="Site")
        st.plotly_chart(fig, use_container_width=True)
    with r1c2:
        st.subheader("Process Path")
        path_counts = a_filtered["process_path"].value_counts().reset_index()
        path_counts.columns = ["Process Path", "Count"]
        if a_chart_type == "Bar Charts":
            fig = px.bar(path_counts.head(10), x="Count", y="Process Path", orientation="h", text="Count", color_discrete_sequence=["#146EB4"])
            fig.update_layout(yaxis=dict(autorange="reversed"))
            fig.update_traces(textposition="outside")
        else:
            fig = px.pie(path_counts.head(10), values="Count", names="Process Path")
        st.plotly_chart(fig, use_container_width=True)
    with r1c3:
        st.subheader("Incident Type")
        type_counts = a_filtered["pit_incident_type"].value_counts().reset_index()
        type_counts.columns = ["Type", "Count"]
        if a_chart_type == "Bar Charts":
            fig = px.bar(type_counts, x="Type", y="Count", color="Type", text="Count",
                         color_discrete_map={"PIT/Pedestrian":"#D13212","PIT/PIT":"#FF9900","PIT/Structure":"#232F3E","PIT/Product":"#146EB4","Other/Unknown":"#879596"})
            fig.update_layout(showlegend=False)
            fig.update_traces(textposition="outside")
        else:
            fig = px.pie(type_counts, values="Count", names="Type", color="Type",
                         color_discrete_map={"PIT/Pedestrian":"#D13212","PIT/PIT":"#FF9900","PIT/Structure":"#232F3E","PIT/Product":"#146EB4","Other/Unknown":"#879596"})
        st.plotly_chart(fig, use_container_width=True)

    # --- Row 2: Location + PIT Type + Reporting Timeliness ---
    r2c1, r2c2, r2c3 = st.columns(3)
    with r2c1:
        st.subheader("Location")
        loc_counts = a_filtered["location_clean"].value_counts().reset_index()
        loc_counts.columns = ["Location", "Count"]
        if a_chart_type == "Bar Charts":
            fig = px.bar(loc_counts.head(10), x="Count", y="Location", orientation="h", text="Count", color_discrete_sequence=["#146EB4"])
            fig.update_layout(yaxis=dict(autorange="reversed"))
            fig.update_traces(textposition="outside")
        else:
            fig = px.pie(loc_counts.head(10), values="Count", names="Location")
        st.plotly_chart(fig, use_container_width=True)
    with r2c2:
        st.subheader("PIT Type")
        equip_counts = a_filtered["pit_equipment_type"].value_counts().reset_index()
        equip_counts.columns = ["PIT Type", "Count"]
        if a_chart_type == "Bar Charts":
            fig = px.bar(equip_counts, x="PIT Type", y="Count", text="Count", color_discrete_sequence=["#FF9900"])
            fig.update_traces(textposition="outside")
            fig.update_layout(xaxis_tickangle=-45)
        else:
            fig = px.pie(equip_counts, values="Count", names="PIT Type")
        st.plotly_chart(fig, use_container_width=True)
    with r2c3:
        st.subheader("Reporting Timeliness")
        rep_data = a_filtered.dropna(subset=["report_status"])
        rep_counts = rep_data["report_status"].value_counts().reset_index()
        rep_counts.columns = ["Status", "Count"]
        if a_chart_type == "Bar Charts":
            fig = px.bar(rep_counts, x="Status", y="Count", text="Count", color="Status",
                         color_discrete_map={"Late Report":"#D13212","Reported On Time":"#1D8102"})
            fig.update_traces(textposition="outside")
            fig.update_layout(showlegend=False)
        else:
            fig = px.pie(rep_counts, values="Count", names="Status", color="Status",
                         color_discrete_map={"Late Report":"#D13212","Reported On Time":"#1D8102"})
        st.plotly_chart(fig, use_container_width=True)

    # --- Row 3: Day of Week + Time of Day + Record Type ---
    r3c1, r3c2, r3c3 = st.columns(3)
    with r3c1:
        st.subheader("Day of Week")
        dow_counts = a_filtered.dropna(subset=["day_of_week"])["day_of_week"].value_counts().reset_index()
        dow_counts.columns = ["Day", "Count"]
        day_order = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        dow_counts["sort_key"] = dow_counts["Day"].apply(lambda x: day_order.index(x) if x in day_order else 99)
        dow_counts = dow_counts.sort_values("sort_key")
        if a_chart_type == "Bar Charts":
            fig = px.bar(dow_counts, x="Day", y="Count", text="Count", color_discrete_sequence=["#232F3E"])
            fig.update_traces(textposition="outside")
        else:
            fig = px.pie(dow_counts, values="Count", names="Day")
        st.plotly_chart(fig, use_container_width=True)
    with r3c2:
        st.subheader("Time of Day")
        tod_data = a_filtered.dropna(subset=["hour"])
        hour_counts = tod_data.groupby("hour").size().reset_index(name="count")
        hour_counts["hour_label"] = hour_counts["hour"].apply(lambda h: f"{int(h):02d}:00")
        if a_chart_type == "Bar Charts":
            fig = px.bar(hour_counts, x="hour_label", y="count", text="count", labels={"hour_label":"Hour","count":"Incidents"}, color_discrete_sequence=["#146EB4"])
            fig.update_traces(textposition="outside")
        else:
            fig = px.pie(hour_counts, values="count", names="hour_label")
        st.plotly_chart(fig, use_container_width=True)
    with r3c3:
        st.subheader("Record Type")
        rec_counts = a_filtered["record_type"].value_counts().reset_index()
        rec_counts.columns = ["Type", "Count"]
        if a_chart_type == "Bar Charts":
            fig = px.bar(rec_counts, x="Type", y="Count", text="Count", color="Type",
                         color_discrete_map={"Incident":"#D13212","Near Miss":"#FF9900"})
            fig.update_traces(textposition="outside")
            fig.update_layout(showlegend=False)
        else:
            fig = px.pie(rec_counts, values="Count", names="Type", color="Type",
                         color_discrete_map={"Incident":"#D13212","Near Miss":"#FF9900"})
        st.plotly_chart(fig, use_container_width=True)

    # --- Incidents Over Time ---
    st.subheader("Incidents Over Time")
    trend = a_filtered.dropna(subset=["incident_date"]).copy()
    trend["month"] = trend["incident_date"].dt.to_period("M").astype(str)
    monthly = trend.groupby("month").size().reset_index(name="count")
    avg_count = monthly["count"].mean() if not monthly.empty else 0
    fig_trend = px.bar(monthly, x="month", y="count", labels={"month":"Month","count":"Incidents"}, text="count", color_discrete_sequence=["#FF9900"])
    fig_trend.update_layout(xaxis_tickangle=-45)
    fig_trend.update_traces(textposition="outside")
    if avg_count > 0:
        fig_trend.add_hline(y=avg_count, line_dash="dash", line_color="red", line_width=2,
                            annotation_text=f"Avg: {avg_count:.1f}", annotation_position="top right",
                            annotation_font_color="red", annotation_font_size=14)
    st.plotly_chart(fig_trend, use_container_width=True)

    # --- FLAGGED NEAR MISSES SUMMARY ---
    st.markdown("---")
    st.subheader("🚩 Reclassified Near Misses")
    st.caption("These near misses were flagged and reclassified as incidents in this view.")

    # Show flagged cases from the filtered data
    flagged_nm = a_filtered[a_filtered["is_flagged"] == True]

    flag_col1, flag_col2 = st.columns(2)
    with flag_col1:
        st.metric("Reclassified Cases", len(flagged_nm))
    with flag_col2:
        if not flagged_nm.empty:
            st.subheader("Flags by Site")
            flag_site_counts = flagged_nm["site"].value_counts().reset_index()
            flag_site_counts.columns = ["Site", "Count"]
            if a_chart_type == "Bar Charts":
                fig_flag = px.bar(flag_site_counts.head(15), x="Site", y="Count", text="Count", color_discrete_sequence=["#D13212"])
                fig_flag.update_traces(textposition="outside")
            else:
                fig_flag = px.pie(flag_site_counts.head(15), values="Count", names="Site")
            st.plotly_chart(fig_flag, use_container_width=True)
        else:
            st.info("No flagged near misses with current filters.")

    # --- DATA TABLE ---
    st.markdown("---")
    st.subheader("All PIT Incidents Raw Data")
    display_cols = ["record_type", "site", "incident_date", "process_path",
                    "location_clean", "pit_incident_type", "pit_equipment_type", "description"]
    available_cols = [c for c in display_cols if c in a_filtered.columns]
    st.dataframe(
        a_filtered[available_cols].sort_values("incident_date", ascending=False),
        use_container_width=True,
        height=400
    )


# ============================================================
# PIT Near Misses
# ============================================================
elif active_page == "🚜 PIT Near Misses":
    pit_data = df[df["initial_info_nearmiss_type"] == "PIT"]

    # Load verified flags and remove validated incidents from near miss view
    verified = load_verified()
    valid_ids = verified.get("valid", [])
    if valid_ids:
        pit_data = pit_data[~pit_data["incident_id"].isin(valid_ids)]

    # Classify PIT incident types before filtering
    def classify_pit_type_for_filter(description):
        if pd.isna(description):
            return "Other/Unknown"
        desc = description.lower()
        pit_kw = ["pit on pit", "pit-on-pit", "another op", "another pit",
                  "other op", "other pit", "two ops", "two pits",
                  "op collided", "pit collided", "t-boned", "t boned",
                  "rear-ended", "rear ended", "op that was parked",
                  "parked op", "parked pit", "adjacent op", "neighboring op"]
        struct_kw = ["rack", "racking", "guard", "pillar", "column", "wall",
                     "door", "bollard", "barrier", "post", "beam", "structure",
                     "vna", "aisle", "sprinkler", "ceiling", "overhead",
                     "dock", "gate", "fence", "rail", "railing", "upright"]
        prod_kw = ["pallet", "product", "box", "case", "tote", "package",
                   "load", "freight", "cargo", "bin", "carton", "inventory"]
        for kw in pit_kw:
            if kw in desc:
                return "PIT/PIT"
        for kw in struct_kw:
            if kw in desc:
                return "PIT/Structure"
        for kw in prod_kw:
            if kw in desc:
                return "PIT/Product"
        return "Other/Unknown"

    pit_data["pit_incident_type"] = pit_data["initial_info_incident_description"].apply(classify_pit_type_for_filter)

    # Location cleaning
    pit_data["location_clean"] = pit_data["initial_info_location_event"].apply(
        lambda x: "VNA (Very Narrow Aisle)" if pd.notna(x) and ("vna" in x.lower() or "very narrow aisle" in x.lower())
        else ("PIT Highway" if pd.notna(x) and ("straight" in x.lower() or "drive lane" in x.lower() or "driveway" in x.lower())
        else ("Parking Lot" if pd.notna(x) and ("parking" in x.lower())
        else ("Stow Aisles" if pd.notna(x) and ("stow rack" in x.lower() or "stow aisle" in x.lower()) else x)))
    )

    # Derive day of week and reporting timeliness for filtering
    pit_data["day_of_week"] = pit_data["nearmiss_date"].dt.day_name()
    pit_data["nearmiss_time_parsed"] = pd.to_datetime(pit_data["nearmiss_time"], errors="coerce")
    pit_data["hour"] = pit_data["nearmiss_time_parsed"].dt.hour
    pit_data["hour_label"] = pit_data["hour"].apply(lambda h: f"{int(h):02d}:00" if pd.notna(h) else None)
    pit_data["days_to_report"] = (pit_data["created_at"] - pit_data["nearmiss_date"]).dt.total_seconds() / 86400
    pit_data["report_status"] = pit_data["days_to_report"].apply(
        lambda x: "Late Report" if pd.notna(x) and x > 1 else ("Reported On Time" if pd.notna(x) else None)
    )

    # PIT equipment type (extracted from description)
    def classify_pit_equipment_nm(description):
        if pd.isna(description):
            return "Unknown"
        desc = description.lower()
        if "turret" in desc:
            return "TT (Turret Truck)"
        elif "center rider" in desc or "center-rider" in desc or "epj" in desc or "electric pallet jack" in desc:
            return "Center Rider"
        elif "tugger" in desc or "tow motor" in desc:
            return "Tugger"
        elif "stand up" in desc or "standup" in desc or "stand-up" in desc or "forklift" in desc or "counterbalance" in desc:
            return "SU (Stand Up/Forklift)"
        elif "reach truck" in desc or "reach-truck" in desc:
            return "Reach Truck"
        elif "order picker" in desc or " op " in desc or "op " in desc[:3] or "their op" in desc or "the op" in desc or "an op" in desc:
            return "OP (Order Picker)"
        elif "pallet jack" in desc or "pallet truck" in desc:
            return "Pallet Truck"
        else:
            return "Unknown"

    pit_data["pit_equipment_type"] = pit_data["initial_info_incident_description"].apply(classify_pit_equipment_nm)

    # --- FILTERS (2 rows) ---
    fc1, fc2, fc3, fc4, fc5, fc6, fc7 = st.columns(7)
    with fc1:
        sel_cats = st.multiselect("Site Type", sorted(pit_data["site_category"].unique()), default=[], key="pit_cat", placeholder="All")
    with fc2:
        sel_sites = st.multiselect("Site", sorted(pit_data["site"].dropna().unique()), default=[], key="pit_sites", placeholder="All")
    with fc3:
        sel_paths = st.multiselect("Process Path", sorted(pit_data["initial_info_process_path"].dropna().unique()), default=[], key="pit_paths", placeholder="All")
    with fc4:
        sel_pit_types = st.multiselect("Incident Type", sorted(pit_data["pit_incident_type"].unique()), default=[], key="pit_type", placeholder="All")
    with fc5:
        sel_locations = st.multiselect("Location", sorted(pit_data["location_clean"].dropna().unique()), default=[], key="pit_location", placeholder="All")
    with fc6:
        sel_equip = st.multiselect("PIT Type", sorted(pit_data["pit_equipment_type"].unique()), default=[], key="pit_equip", placeholder="All")
    with fc7:
        sel_tenures = st.multiselect("Tenure", sorted(pit_data["tenure_at_amazon"].dropna().unique()), default=[], key="pit_tenure", placeholder="All")

    fc8, fc9, fc10, fc11, fc12, fc13, fc14 = st.columns(7)
    with fc8:
        sel_days = st.multiselect("Day of Week", ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"], default=[], key="pit_dow", placeholder="All")
    with fc9:
        sel_hours = st.multiselect("Time of Day", sorted(pit_data["hour_label"].dropna().unique()), default=[], key="pit_tod", placeholder="All")
    with fc10:
        sel_report = st.multiselect("Report Status", ["Reported On Time","Late Report"], default=[], key="pit_report", placeholder="All")
    with fc11:
        pit_data["year"] = pit_data["nearmiss_date"].dt.year.astype("Int64").astype(str).replace("<NA>", None)
        pit_data["month_name"] = pit_data["nearmiss_date"].dt.month_name()
        sel_years = st.multiselect("Year", sorted(pit_data["year"].dropna().unique()), default=[], key="pit_year", placeholder="All")
    with fc12:
        sel_months = st.multiselect("Month", ["January","February","March","April","May","June","July","August","September","October","November","December"], default=[], key="pit_month", placeholder="All")
    with fc13:
        min_date = pit_data["nearmiss_date"].min()
        max_date = pit_data["nearmiss_date"].max()
        if pd.notna(min_date) and pd.notna(max_date):
            date_range = st.date_input("Date Range", value=(min_date.date(), max_date.date()), min_value=min_date.date(), max_value=max_date.date(), key="pit_date")
        else:
            date_range = None
    with fc14:
        chart_type = st.selectbox("Chart Style", ["Bar Charts", "Pie Charts"], key="pit_chart_type")

    # Apply filters (empty selection = All)
    filtered = pit_data.copy()
    if sel_cats:
        filtered = filtered[filtered["site_category"].isin(sel_cats)]
    if sel_sites:
        filtered = filtered[filtered["site"].isin(sel_sites)]
    if sel_paths:
        filtered = filtered[filtered["initial_info_process_path"].isin(sel_paths)]
    if sel_pit_types:
        filtered = filtered[filtered["pit_incident_type"].isin(sel_pit_types)]
    if sel_locations:
        filtered = filtered[filtered["location_clean"].isin(sel_locations)]
    if sel_equip:
        filtered = filtered[filtered["pit_equipment_type"].isin(sel_equip)]
    if sel_tenures:
        filtered = filtered[filtered["tenure_at_amazon"].isin(sel_tenures)]
    if sel_days:
        filtered = filtered[filtered["day_of_week"].isin(sel_days)]
    if sel_hours:
        filtered = filtered[filtered["hour_label"].isin(sel_hours)]
    if sel_report:
        filtered = filtered[filtered["report_status"].isin(sel_report)]
    if sel_years:
        filtered = filtered[filtered["year"].isin(sel_years)]
    if sel_months:
        filtered = filtered[filtered["month_name"].isin(sel_months)]
    if date_range and len(date_range) == 2:
        filtered = filtered[
            (filtered["nearmiss_date"].dt.date >= date_range[0]) &
            (filtered["nearmiss_date"].dt.date <= date_range[1])
        ]

    # --- KPI Header ---
    kpi1, kpi2 = st.columns([1, 1])
    with kpi1:
        st.metric("Total Incidents", len(filtered))
    with kpi2:
        st.metric("Sites", filtered["site"].nunique())

    # --- Row 1: Site + Process Path + Incident Type ---
    r1c1, r1c2, r1c3 = st.columns(3)
    with r1c1:
        st.subheader("Site")
        site_counts = filtered["site"].value_counts().reset_index()
        site_counts.columns = ["Site", "Count"]
        if chart_type == "Bar Charts":
            fig_site = px.bar(site_counts.head(15), x="Site", y="Count", text="Count", color_discrete_sequence=["#232F3E"])
            fig_site.update_traces(textposition="outside")
        else:
            fig_site = px.pie(site_counts.head(15), values="Count", names="Site")
        st.plotly_chart(fig_site, use_container_width=True)
    with r1c2:
        st.subheader("Process Path")
        path_counts = filtered["initial_info_process_path"].value_counts().reset_index()
        path_counts.columns = ["Process Path", "Count"]
        if chart_type == "Bar Charts":
            fig_path = px.bar(path_counts.head(10), x="Count", y="Process Path", orientation="h", text="Count", color_discrete_sequence=["#146EB4"])
            fig_path.update_layout(yaxis=dict(autorange="reversed"))
            fig_path.update_traces(textposition="outside")
        else:
            fig_path = px.pie(path_counts.head(10), values="Count", names="Process Path")
        st.plotly_chart(fig_path, use_container_width=True)
    with r1c3:
        st.subheader("Incident Type")
        pit_type_counts = filtered["pit_incident_type"].value_counts().reset_index()
        pit_type_counts.columns = ["PIT Incident Type", "Count"]
        if chart_type == "Bar Charts":
            fig_pit_type = px.bar(pit_type_counts, x="PIT Incident Type", y="Count", color="PIT Incident Type", text="Count",
                                  color_discrete_map={"PIT/PIT":"#FF9900","PIT/Structure":"#232F3E","PIT/Product":"#146EB4","Other/Unknown":"#879596"})
            fig_pit_type.update_layout(showlegend=False)
            fig_pit_type.update_traces(textposition="outside")
        else:
            fig_pit_type = px.pie(pit_type_counts, values="Count", names="PIT Incident Type",
                                  color="PIT Incident Type", color_discrete_map={"PIT/PIT":"#FF9900","PIT/Structure":"#232F3E","PIT/Product":"#146EB4","Other/Unknown":"#879596"})
        st.plotly_chart(fig_pit_type, use_container_width=True)

    # --- Row 2: Location + PIT Type + Tenure ---
    r2c1, r2c2, r2c3 = st.columns(3)
    with r2c1:
        st.subheader("Location")
        location_counts = filtered["location_clean"].value_counts().reset_index()
        location_counts.columns = ["Location", "Count"]
        if chart_type == "Bar Charts":
            fig_location = px.bar(location_counts.head(10), x="Count", y="Location", orientation="h", text="Count", color_discrete_sequence=["#146EB4"])
            fig_location.update_layout(yaxis=dict(autorange="reversed"))
            fig_location.update_traces(textposition="outside")
        else:
            fig_location = px.pie(location_counts.head(10), values="Count", names="Location")
        st.plotly_chart(fig_location, use_container_width=True)
    with r2c2:
        st.subheader("PIT Type")
        equip_counts = filtered["pit_equipment_type"].value_counts().reset_index()
        equip_counts.columns = ["PIT Type", "Count"]
        if chart_type == "Bar Charts":
            fig_equip = px.bar(equip_counts, x="PIT Type", y="Count", text="Count", color_discrete_sequence=["#FF9900"])
            fig_equip.update_traces(textposition="outside")
            fig_equip.update_layout(xaxis_tickangle=-45)
        else:
            fig_equip = px.pie(equip_counts, values="Count", names="PIT Type")
        st.plotly_chart(fig_equip, use_container_width=True)
    with r2c3:
        st.subheader("Associate Tenure")
        tenure_order = ["Less than 1 month","1-3 months","3-6 months","6-12 months","1-2 years","2-5 years","5+ years"]
        tenure_counts = filtered["tenure_at_amazon"].value_counts().reset_index()
        tenure_counts.columns = ["Tenure", "Count"]
        tenure_counts["sort_key"] = tenure_counts["Tenure"].apply(lambda x: tenure_order.index(x) if x in tenure_order else 99)
        tenure_counts = tenure_counts.sort_values("sort_key")
        if chart_type == "Bar Charts":
            fig_tenure = px.bar(tenure_counts, x="Tenure", y="Count", text="Count", color_discrete_sequence=["#FF9900"])
            fig_tenure.update_layout(xaxis_tickangle=-45)
            fig_tenure.update_traces(textposition="outside")
        else:
            fig_tenure = px.pie(tenure_counts, values="Count", names="Tenure")
        st.plotly_chart(fig_tenure, use_container_width=True)

    # --- Row 3: Reporting Timeliness + Day of Week + Time of Day ---
    r3c1, r3c2, r3c3 = st.columns(3)
    with r3c1:
        st.subheader("Reporting Timeliness")
        report_data = filtered.dropna(subset=["nearmiss_date", "created_at"]).copy()
        report_data["days_to_report"] = (report_data["created_at"] - report_data["nearmiss_date"]).dt.total_seconds() / 86400
        report_data["report_status_calc"] = report_data["days_to_report"].apply(lambda x: "Late Report" if x > 1 else "Reported On Time")
        report_counts = report_data["report_status_calc"].value_counts().reset_index()
        report_counts.columns = ["Status", "Count"]
        if chart_type == "Bar Charts":
            fig_report = px.bar(report_counts, x="Status", y="Count", text="Count", color="Status",
                                color_discrete_map={"Late Report":"#D13212","Reported On Time":"#1D8102"})
            fig_report.update_traces(textposition="outside")
            fig_report.update_layout(showlegend=False)
        else:
            fig_report = px.pie(report_counts, values="Count", names="Status", color="Status",
                                color_discrete_map={"Late Report":"#D13212","Reported On Time":"#1D8102"})
        st.plotly_chart(fig_report, use_container_width=True)
    with r3c2:
        st.subheader("Day of Week")
        dow_data = filtered.dropna(subset=["nearmiss_date"]).copy()
        dow_data["day_of_week_chart"] = dow_data["nearmiss_date"].dt.day_name()
        day_order = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        dow_counts = dow_data["day_of_week_chart"].value_counts().reset_index()
        dow_counts.columns = ["Day", "Count"]
        dow_counts["sort_key"] = dow_counts["Day"].apply(lambda x: day_order.index(x) if x in day_order else 99)
        dow_counts = dow_counts.sort_values("sort_key")
        if chart_type == "Bar Charts":
            fig_dow = px.bar(dow_counts, x="Day", y="Count", text="Count", color_discrete_sequence=["#232F3E"])
            fig_dow.update_traces(textposition="outside")
        else:
            fig_dow = px.pie(dow_counts, values="Count", names="Day")
        st.plotly_chart(fig_dow, use_container_width=True)
    with r3c3:
        st.subheader("Time of Day")
        tod_data = filtered.copy()
        tod_data["nearmiss_time_parsed"] = pd.to_datetime(tod_data["nearmiss_time"], errors="coerce")
        tod_data = tod_data.dropna(subset=["nearmiss_time_parsed"])
        tod_data["hour_chart"] = tod_data["nearmiss_time_parsed"].dt.hour
        hour_counts = tod_data.groupby("hour_chart").size().reset_index(name="count")
        hour_counts["hour_label"] = hour_counts["hour_chart"].apply(lambda h: f"{h:02d}:00")
        if chart_type == "Bar Charts":
            fig_tod = px.bar(hour_counts, x="hour_label", y="count", text="count", labels={"hour_label":"Hour","count":"Incidents"}, color_discrete_sequence=["#146EB4"])
            fig_tod.update_traces(textposition="outside")
        else:
            fig_tod = px.pie(hour_counts, values="count", names="hour_label")
        st.plotly_chart(fig_tod, use_container_width=True)

    # --- Incidents Over Time ---
    st.subheader("Incidents Over Time")
    trend = filtered.dropna(subset=["nearmiss_date"]).copy()
    trend["month"] = trend["nearmiss_date"].dt.to_period("M").astype(str)
    monthly = trend.groupby("month").size().reset_index(name="count")
    avg_count = monthly["count"].mean()
    fig_trend = px.bar(monthly, x="month", y="count",
                       labels={"month": "Month", "count": "Incidents"},
                       text="count",
                       color_discrete_sequence=["#FF9900"])
    fig_trend.update_layout(xaxis_tickangle=-45)
    fig_trend.update_traces(textposition="outside")
    fig_trend.add_hline(
        y=avg_count,
        line_dash="dash",
        line_color="red",
        line_width=2,
        annotation_text=f"Avg: {avg_count:.1f}",
        annotation_position="top right",
        annotation_font_color="red",
        annotation_font_size=14
    )
    st.plotly_chart(fig_trend, use_container_width=True)

    st.markdown("---")
    st.subheader("Near Miss Raw Data")
    display_cols = [
        "site", "nearmiss_date", "potential_severity", "status",
        "initial_info_process_path", "initial_info_primary_impact",
        "tenure_at_amazon", "initial_info_incident_description"
    ]
    available_cols = [c for c in display_cols if c in filtered.columns]
    st.dataframe(
        filtered[available_cols].sort_values("nearmiss_date", ascending=False),
        use_container_width=True,
        height=400
    )


# ============================================================
# Flagged Near Misses (Verification Tab)
# ============================================================
elif active_page == "🚩 Flagged Near Misses":
    st.header("🚩 Flagged Near Misses - Verification")
    st.markdown("Review each flagged near miss below. Mark as **Valid** (it IS an incident, not a near miss) or **Not Valid** (it should stay as a near miss).")
    st.markdown("- **Valid** = removes it from the PIT Near Misses tab (it's actually an incident)")
    st.markdown("- **Not Valid** = keeps it in the PIT Near Misses tab (it's correctly a near miss)")
    st.markdown("---")

    pit_data = df[df["initial_info_nearmiss_type"] == "PIT"]

    # Run flagging on all PIT data
    pit_data["flag_result"] = pit_data["initial_info_incident_description"].apply(is_flagged)
    pit_data["flag_reason"] = pit_data["flag_result"].apply(lambda x: x[0] if x else None)
    pit_data["flag_keyword"] = pit_data["flag_result"].apply(lambda x: x[1] if x else None)
    flagged = pit_data[pit_data["flag_reason"].notna()].copy()

    # Load current verification state
    verified = load_verified()

    # Show counts
    total_flagged = len(flagged)
    num_valid = len([i for i in flagged["incident_id"] if i in verified["valid"]])
    num_not_valid = len([i for i in flagged["incident_id"] if i in verified["not_valid"]])
    already_verified = num_valid + num_not_valid
    pending = total_flagged - already_verified

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total Flagged", total_flagged)
    with col2:
        st.metric("Verified", already_verified)
    with col3:
        st.metric("Pending Review", pending)
    with col4:
        st.metric("Valid (Incidents)", num_valid)
    with col5:
        st.metric("Not Valid (Near Misses)", num_not_valid)

    st.markdown("---")

    # Filter options for the flagged view
    flag_filter = st.selectbox("Show", ["Pending Review", "All Flagged", "Verified Valid", "Verified Not Valid"])

    if flag_filter == "Pending Review":
        display_flagged = flagged[~flagged["incident_id"].isin(verified["valid"] + verified["not_valid"])]
    elif flag_filter == "Verified Valid":
        display_flagged = flagged[flagged["incident_id"].isin(verified["valid"])]
    elif flag_filter == "Verified Not Valid":
        display_flagged = flagged[flagged["incident_id"].isin(verified["not_valid"])]
    else:
        display_flagged = flagged

    if display_flagged.empty:
        st.info("No flagged near misses in this category.")
    else:
        for idx, row in display_flagged.iterrows():
            incident_id = row["incident_id"]
            with st.expander(f"**{row['site']}** | {row['flag_reason']} | Triggered by: \"{row['flag_keyword']}\""):
                st.markdown(f"**Site:** {row['site']}")
                st.markdown(f"**Primary Impact:** {row['initial_info_primary_impact']}")
                st.markdown(f"**Flag Reason:** {row['flag_reason']}")
                st.markdown(f"**Triggered By:** \"{row['flag_keyword']}\"")
                st.markdown(f"**Date:** {row['nearmiss_date']}")
                st.markdown("**Description:**")
                st.text(str(row["initial_info_incident_description"])[:1000])

                # Current status
                if incident_id in verified["valid"]:
                    st.success("✅ Marked as VALID (removed from near misses)")
                elif incident_id in verified["not_valid"]:
                    st.warning("❌ Marked as NOT VALID (stays in near misses)")

                # Verification buttons
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    if st.button("✅ Valid (is an incident)", key=f"valid_{incident_id}"):
                        verified = load_verified()
                        if incident_id not in verified["valid"]:
                            verified["valid"].append(incident_id)
                        if incident_id in verified["not_valid"]:
                            verified["not_valid"].remove(incident_id)
                        save_verified(verified)
                        st.rerun()
                with col_b:
                    if st.button("❌ Not Valid (stays as near miss)", key=f"notvalid_{incident_id}"):
                        verified = load_verified()
                        if incident_id not in verified["not_valid"]:
                            verified["not_valid"].append(incident_id)
                        if incident_id in verified["valid"]:
                            verified["valid"].remove(incident_id)
                        save_verified(verified)
                        st.rerun()
                with col_c:
                    if incident_id in verified["valid"] or incident_id in verified["not_valid"]:
                        if st.button("🔄 Reset", key=f"reset_{incident_id}"):
                            verified = load_verified()
                            if incident_id in verified["valid"]:
                                verified["valid"].remove(incident_id)
                            if incident_id in verified["not_valid"]:
                                verified["not_valid"].remove(incident_id)
                            save_verified(verified)
                            st.rerun()


# ============================================================
# Fire Near Misses
# ============================================================
elif active_page == "🔥 Thermal Events":
    # Load and combine fire data from both sources
    @st.cache_data
    def load_thermal_events():
        # Fire near misses
        nm = pd.read_csv("Near Miss Data.csv")
        nm["nearmiss_date"] = pd.to_datetime(nm["nearmiss_date"], errors="coerce")
        nm["created_at"] = pd.to_datetime(nm["created_at"], errors="coerce")
        nm_fire = nm[nm["initial_info_nearmiss_type"] == "Fire"].copy()
        nm_fire["incident_date"] = nm_fire["nearmiss_date"]
        nm_fire["location"] = nm_fire["initial_info_location_event"]
        nm_fire["description"] = nm_fire["initial_info_incident_description"]
        nm_fire["record_type"] = "Near Miss"
        nm_fire["fire_type_raw"] = None
        nm_fire["root_cause"] = nm_fire.get("rca_primary_cause", None)

        # Fire events
        fe = pd.read_csv("Fire Events.csv")
        fe["incident_date"] = pd.to_datetime(fe["incident_date"], errors="coerce")
        fe["created_at"] = pd.to_datetime(fe["created_at"], errors="coerce")
        fe["location"] = fe["initial_info_incident_location"]
        fe["description"] = fe["initial_info_incident_description"]
        fe["record_type"] = "Incident"
        fe["fire_type_raw"] = fe["sub_event_type_details"]
        fe["root_cause"] = fe["rca_primary_cause"]

        common_cols = ["site", "incident_date", "created_at", "location", "description", "record_type", "status", "fire_type_raw", "root_cause"]
        nm_sub = nm_fire[[c for c in common_cols if c in nm_fire.columns]].copy()
        fe_sub = fe[[c for c in common_cols if c in fe.columns]].copy()

        combined = pd.concat([nm_sub, fe_sub], ignore_index=True)
        return combined

    tdf = load_thermal_events()
    tdf["site_category"] = tdf["site"].apply(classify_site_type)

    # Classify fire type from description if not already set
    def classify_fire_type(row):
        if pd.notna(row.get("fire_type_raw")):
            # Check description for auger even if we have a raw type
            desc = str(row.get("description", "")).lower()
            if "auger" in desc:
                return "Auger"
            return row["fire_type_raw"]
        desc = str(row.get("description", "")).lower()
        if "auger" in desc:
            return "Auger"
        elif "battery" in desc or "lithium" in desc:
            return "Battery"
        elif "vehicle" in desc or "car" in desc or "truck fire" in desc:
            return "Vehicle"
        elif "electrical" in desc or "wiring" in desc or "outlet" in desc or "short circuit" in desc:
            return "Electrical"
        elif "vegetation" in desc or "bush" in desc or "grass" in desc or "tree" in desc or "mulch" in desc:
            return "Vegetation"
        elif "waste" in desc or "trash" in desc or "compactor" in desc or "cardboard" in desc:
            return "Waste"
        elif "machine" in desc or "conveyor" in desc or "motor" in desc or "friction" in desc:
            return "Machinery"
        elif "propane" in desc or "gas" in desc or "flammable" in desc or "chemical" in desc:
            return "Flammable Liquid"
        elif "structure" in desc or "building" in desc or "roof" in desc:
            return "Structure"
        else:
            return "Unknown"

    tdf["fire_type"] = tdf.apply(classify_fire_type, axis=1)

    # --- FILTERS (2 rows) ---
    tfc1, tfc2, tfc3, tfc4, tfc5, tfc6 = st.columns(6)
    with tfc1:
        t_sel_type = st.multiselect("Record Type", ["Near Miss", "Incident"], default=[], key="therm_type", placeholder="All")
    with tfc2:
        t_sel_cats = st.multiselect("Site Type", sorted(tdf["site_category"].unique()), default=[], key="therm_cat", placeholder="All")
    with tfc3:
        t_sel_sites = st.multiselect("Site", sorted(tdf["site"].dropna().unique()), default=[], key="therm_sites", placeholder="All")
    with tfc4:
        t_sel_fire_type = st.multiselect("Event Type", sorted(tdf["fire_type"].unique()), default=[], key="therm_firetype", placeholder="All")
    with tfc5:
        tdf["year"] = tdf["incident_date"].dt.year.astype("Int64").astype(str).replace("<NA>", None)
        tdf["month_name"] = tdf["incident_date"].dt.month_name()
        t_sel_years = st.multiselect("Year", sorted(tdf["year"].dropna().unique()), default=[], key="therm_year", placeholder="All")
    with tfc6:
        t_sel_months = st.multiselect("Month", ["January","February","March","April","May","June","July","August","September","October","November","December"], default=[], key="therm_month", placeholder="All")

    tfc7, tfc8 = st.columns([1, 5])
    with tfc7:
        t_min_date = tdf["incident_date"].min()
        t_max_date = tdf["incident_date"].max()
        if pd.notna(t_min_date) and pd.notna(t_max_date):
            t_date_range = st.date_input("Date Range", value=(t_min_date.date(), t_max_date.date()), min_value=t_min_date.date(), max_value=t_max_date.date(), key="therm_date")
        else:
            t_date_range = None

    t_chart_type = st.selectbox("Chart Style", ["Bar Charts", "Pie Charts"], key="therm_chart_type")

    # Apply filters
    t_filtered = tdf.copy()
    if t_sel_type:
        t_filtered = t_filtered[t_filtered["record_type"].isin(t_sel_type)]
    if t_sel_cats:
        t_filtered = t_filtered[t_filtered["site_category"].isin(t_sel_cats)]
    if t_sel_sites:
        t_filtered = t_filtered[t_filtered["site"].isin(t_sel_sites)]
    if t_sel_fire_type:
        t_filtered = t_filtered[t_filtered["fire_type"].isin(t_sel_fire_type)]
    if t_sel_years:
        t_filtered = t_filtered[t_filtered["year"].isin(t_sel_years)]
    if t_sel_months:
        t_filtered = t_filtered[t_filtered["month_name"].isin(t_sel_months)]
    if t_date_range and len(t_date_range) == 2:
        t_filtered = t_filtered[
            (t_filtered["incident_date"].dt.date >= t_date_range[0]) &
            (t_filtered["incident_date"].dt.date <= t_date_range[1])
        ]

    # --- KPI ---
    kpi1, kpi2, kpi3 = st.columns(3)
    with kpi1:
        st.metric("Total", len(t_filtered))
    with kpi2:
        st.metric("Incidents", len(t_filtered[t_filtered["record_type"] == "Incident"]))
    with kpi3:
        st.metric("Near Misses", len(t_filtered[t_filtered["record_type"] == "Near Miss"]))

    # --- Row 1: Site + Location + Fire Type ---
    r1c1, r1c2, r1c3 = st.columns(3)
    with r1c1:
        st.subheader("Site")
        site_counts = t_filtered["site"].value_counts().reset_index()
        site_counts.columns = ["Site", "Count"]
        if t_chart_type == "Bar Charts":
            fig = px.bar(site_counts.head(15), x="Site", y="Count", text="Count", color_discrete_sequence=["#D13212"])
            fig.update_traces(textposition="outside")
        else:
            fig = px.pie(site_counts.head(15), values="Count", names="Site")
        st.plotly_chart(fig, use_container_width=True)
    with r1c2:
        st.subheader("Location")
        loc_counts = t_filtered["location"].value_counts().reset_index()
        loc_counts.columns = ["Location", "Count"]
        if t_chart_type == "Bar Charts":
            fig = px.bar(loc_counts.head(10), x="Count", y="Location", orientation="h", text="Count", color_discrete_sequence=["#FF9900"])
            fig.update_layout(yaxis=dict(autorange="reversed"))
            fig.update_traces(textposition="outside")
        else:
            fig = px.pie(loc_counts.head(10), values="Count", names="Location")
        st.plotly_chart(fig, use_container_width=True)
    with r1c3:
        st.subheader("Event Type")
        fire_type_counts = t_filtered["fire_type"].value_counts().reset_index()
        fire_type_counts.columns = ["Event Type", "Count"]
        if t_chart_type == "Bar Charts":
            fig = px.bar(fire_type_counts, x="Event Type", y="Count", text="Count", color_discrete_sequence=["#D13212"])
            fig.update_traces(textposition="outside")
            fig.update_layout(xaxis_tickangle=-45)
        else:
            fig = px.pie(fire_type_counts, values="Count", names="Event Type")
        st.plotly_chart(fig, use_container_width=True)

    # --- Row 2: Record Type + Root Cause ---
    r2c1, r2c2 = st.columns(2)
    with r2c1:
        st.subheader("Record Type")
        rec_counts = t_filtered["record_type"].value_counts().reset_index()
        rec_counts.columns = ["Type", "Count"]
        if t_chart_type == "Bar Charts":
            fig = px.bar(rec_counts, x="Type", y="Count", text="Count", color="Type",
                         color_discrete_map={"Incident":"#D13212","Near Miss":"#FF9900"})
            fig.update_traces(textposition="outside")
            fig.update_layout(showlegend=False)
        else:
            fig = px.pie(rec_counts, values="Count", names="Type", color="Type",
                         color_discrete_map={"Incident":"#D13212","Near Miss":"#FF9900"})
        st.plotly_chart(fig, use_container_width=True)
    with r2c2:
        st.subheader("Root Cause")
        rc_data = t_filtered.dropna(subset=["root_cause"])
        if not rc_data.empty:
            rc_counts = rc_data["root_cause"].value_counts().reset_index()
            rc_counts.columns = ["Root Cause", "Count"]
            if t_chart_type == "Bar Charts":
                fig = px.bar(rc_counts.head(10), x="Count", y="Root Cause", orientation="h", text="Count", color_discrete_sequence=["#FF9900"])
                fig.update_layout(yaxis=dict(autorange="reversed"))
                fig.update_traces(textposition="outside")
            else:
                fig = px.pie(rc_counts.head(10), values="Count", names="Root Cause")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No root cause data available for current filters.")

    # --- Incidents Over Time ---
    st.subheader("Incidents Over Time")
    trend = t_filtered.dropna(subset=["incident_date"]).copy()
    trend["month"] = trend["incident_date"].dt.to_period("M").astype(str)
    monthly = trend.groupby("month").size().reset_index(name="count")
    avg_count = monthly["count"].mean() if not monthly.empty else 0
    fig = px.bar(monthly, x="month", y="count", labels={"month":"Month","count":"Events"}, text="count", color_discrete_sequence=["#D13212"])
    fig.update_layout(xaxis_tickangle=-45)
    fig.update_traces(textposition="outside")
    if avg_count > 0:
        fig.add_hline(y=avg_count, line_dash="dash", line_color="red", line_width=2,
                      annotation_text=f"Avg: {avg_count:.1f}", annotation_position="top right",
                      annotation_font_color="red", annotation_font_size=14)
    st.plotly_chart(fig, use_container_width=True)

    # --- DATA TABLE ---
    st.markdown("---")
    st.subheader("Thermal Events Raw Data")
    display_cols = ["record_type", "site", "incident_date", "location", "description"]
    available_cols = [c for c in display_cols if c in t_filtered.columns]
    st.dataframe(
        t_filtered[available_cols].sort_values("incident_date", ascending=False),
        use_container_width=True,
        height=400
    )

# ============================================================
# PIT Incidents
# ============================================================
elif active_page == "⚠️ PIT Incidents":
    # Load PIT Incident Data
    @st.cache_data
    def load_pit_incidents():
        idf = pd.read_csv("PIT Incident Data.csv")
        idf["incident_date"] = pd.to_datetime(idf["incident_date"], errors="coerce")
        idf["created_at"] = pd.to_datetime(idf["created_at"], errors="coerce")
        idf["date_reported"] = pd.to_datetime(idf["date_reported"], errors="coerce")
        return idf

    idf = load_pit_incidents()
    idf["site_category"] = idf["site"].apply(classify_site_type)

    def classify_pit_incident_type(description):
        if pd.isna(description):
            return "Other/Unknown"
        desc = description.lower()
        ped_kw = ["pedestrian", "struck an associate", "hit an associate",
                  "struck the associate", "hit the associate", "struck aa",
                  "contact with an associate", "contact with a pedestrian",
                  "made contact with an associate", "made contact with a pedestrian",
                  "associate was walking", "walking associate", "person on foot",
                  "struck a aa", "contact with aa", "struck the aa", "hit the aa"]
        pit_kw = ["pit on pit", "pit-on-pit", "another op", "another pit",
                  "other op", "other pit", "two ops", "two pits",
                  "op collided", "pit collided", "t-boned", "t boned",
                  "rear-ended", "rear ended", "op that was parked",
                  "parked op", "parked pit", "adjacent op", "neighboring op"]
        struct_kw = ["rack", "racking", "guard", "pillar", "column", "wall",
                     "door", "bollard", "barrier", "post", "beam", "structure",
                     "vna", "aisle", "sprinkler", "ceiling", "overhead",
                     "dock", "gate", "fence", "rail", "railing", "upright"]
        prod_kw = ["pallet", "product", "box", "case", "tote", "package",
                   "load", "freight", "cargo", "bin", "carton", "inventory"]
        for kw in ped_kw:
            if kw in desc:
                return "PIT/Pedestrian"
        for kw in pit_kw:
            if kw in desc:
                return "PIT/PIT"
        for kw in struct_kw:
            if kw in desc:
                return "PIT/Structure"
        for kw in prod_kw:
            if kw in desc:
                return "PIT/Product"
        return "Other/Unknown"

    idf["pit_incident_type"] = idf["initial_info_incident_description"].apply(classify_pit_incident_type)
    idf["location_clean"] = idf["initial_info_incident_location"].apply(
        lambda x: "VNA (Very Narrow Aisle)" if pd.notna(x) and ("vna" in x.lower() or "very narrow aisle" in x.lower())
        else ("PIT Highway" if pd.notna(x) and ("straight" in x.lower() or "drive lane" in x.lower() or "driveway" in x.lower())
        else ("Parking Lot" if pd.notna(x) and ("parking" in x.lower())
        else ("Stow Aisles" if pd.notna(x) and ("stow rack" in x.lower() or "stow aisle" in x.lower()) else x)))
    )
    idf["day_of_week"] = idf["incident_date"].dt.day_name()
    idf["incident_time_parsed"] = pd.to_datetime(idf["incident_time"], errors="coerce")
    idf["hour"] = idf["incident_time_parsed"].dt.hour
    idf["hour_label"] = idf["hour"].apply(lambda h: f"{int(h):02d}:00" if pd.notna(h) else None)
    idf["days_to_report"] = (idf["created_at"] - idf["incident_date"]).dt.total_seconds() / 86400
    idf["report_status"] = idf["days_to_report"].apply(
        lambda x: "Late Report" if pd.notna(x) and x > 1 else ("Reported On Time" if pd.notna(x) else None)
    )

    # PIT equipment type classification
    def classify_pit_equipment(pit_type):
        if pd.isna(pit_type):
            return "Unknown"
        pt = pit_type.lower()
        if "order picker" in pt or "vop" in pt or "llop" in pt or "stock-picker" in pt or "stock picker" in pt or "high-level" in pt:
            return "OP (Order Picker)"
        elif "turret" in pt or "turrent" in pt or "vnatr" in pt:
            return "TT (Turret Truck)"
        elif "center" in pt or "crpt" in pt or "center-controlled" in pt:
            return "Center Rider"
        elif "tugger" in pt or "tow tractor" in pt or "tract" in pt:
            return "Tugger"
        elif "standup" in pt or "stand-up" in pt or "counterbalance" in pt or "cbtr" in pt or "forklift" in pt:
            return "SU (Stand Up/Forklift)"
        elif "reach" in pt or "retr" in pt:
            return "Reach Truck"
        elif "pallet" in pt or "rppt" in pt or "rpps" in pt or "pedestrian" in pt:
            return "Pallet Truck"
        elif "boom" in pt or "cherry" in pt or "lift" in pt:
            return "Boom Lift"
        elif "scrubber" in pt or "flscr" in pt:
            return "Floor Scrubber"
        else:
            return "Other"

    def classify_pit_equipment_with_desc(row):
        result = classify_pit_equipment(row["initial_info_pit_type"])
        if result == "Unknown":
            desc = str(row.get("initial_info_incident_description", "")).lower()
            if "turret" in desc:
                return "TT (Turret Truck)"
            elif "order picker" in desc or " op " in desc or "their op" in desc or "the op" in desc or "an op" in desc:
                return "OP (Order Picker)"
            elif "center rider" in desc or "epj" in desc:
                return "Center Rider"
            elif "tugger" in desc or "tow motor" in desc:
                return "Tugger"
            elif "stand up" in desc or "standup" in desc or "forklift" in desc or "counterbalance" in desc:
                return "SU (Stand Up/Forklift)"
            elif "reach truck" in desc:
                return "Reach Truck"
            elif "pallet jack" in desc or "pallet truck" in desc:
                return "Pallet Truck"
        return result

    idf["pit_equipment_type"] = idf.apply(classify_pit_equipment_with_desc, axis=1)

    # Remove non-PIT incidents (Unknown = no PIT type identified)
    idf = idf[idf["pit_equipment_type"] != "Unknown"]

    # --- FILTERS (2 rows) ---
    ifc1, ifc2, ifc3, ifc4, ifc5, ifc6 = st.columns(6)
    with ifc1:
        i_sel_cats = st.multiselect("Site Type", sorted(idf["site_category"].unique()), default=[], key="inc_cat", placeholder="All")
    with ifc2:
        i_sel_sites = st.multiselect("Site", sorted(idf["site"].dropna().unique()), default=[], key="inc_sites", placeholder="All")
    with ifc3:
        i_sel_paths = st.multiselect("Process Path", sorted(idf["initial_info_pit_process"].dropna().unique()), default=[], key="inc_paths", placeholder="All")
    with ifc4:
        i_sel_pit_types = st.multiselect("Incident Type", sorted(idf["pit_incident_type"].unique()), default=[], key="inc_type", placeholder="All")
    with ifc5:
        i_sel_locations = st.multiselect("Location", sorted(idf["location_clean"].dropna().unique()), default=[], key="inc_location", placeholder="All")
    with ifc6:
        i_sel_equip = st.multiselect("PIT Type", sorted(idf["pit_equipment_type"].unique()), default=[], key="inc_equip", placeholder="All")

    ifc7, ifc8, ifc9, ifc10, ifc11, ifc12 = st.columns(6)
    with ifc7:
        i_sel_days = st.multiselect("Day of Week", ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"], default=[], key="inc_dow", placeholder="All")
    with ifc8:
        i_sel_hours = st.multiselect("Time of Day", sorted(idf["hour_label"].dropna().unique()), default=[], key="inc_tod", placeholder="All")
    with ifc9:
        i_sel_report = st.multiselect("Report Status", ["Reported On Time","Late Report"], default=[], key="inc_report", placeholder="All")
    with ifc10:
        idf["year"] = idf["incident_date"].dt.year.astype("Int64").astype(str).replace("<NA>", None)
        idf["month_name"] = idf["incident_date"].dt.month_name()
        i_sel_years = st.multiselect("Year", sorted(idf["year"].dropna().unique()), default=[], key="inc_year", placeholder="All")
    with ifc11:
        i_sel_months = st.multiselect("Month", ["January","February","March","April","May","June","July","August","September","October","November","December"], default=[], key="inc_month", placeholder="All")
    with ifc12:
        i_min_date = idf["incident_date"].min()
        i_max_date = idf["incident_date"].max()
        if pd.notna(i_min_date) and pd.notna(i_max_date):
            i_date_range = st.date_input("Date Range", value=(i_min_date.date(), i_max_date.date()), min_value=i_min_date.date(), max_value=i_max_date.date(), key="inc_date")
        else:
            i_date_range = None

    i_chart_type = st.selectbox("Chart Style", ["Bar Charts", "Pie Charts"], key="inc_chart_type")

    # Apply filters
    i_filtered = idf.copy()
    if i_sel_cats:
        i_filtered = i_filtered[i_filtered["site_category"].isin(i_sel_cats)]
    if i_sel_sites:
        i_filtered = i_filtered[i_filtered["site"].isin(i_sel_sites)]
    if i_sel_paths:
        i_filtered = i_filtered[i_filtered["initial_info_pit_process"].isin(i_sel_paths)]
    if i_sel_pit_types:
        i_filtered = i_filtered[i_filtered["pit_incident_type"].isin(i_sel_pit_types)]
    if i_sel_locations:
        i_filtered = i_filtered[i_filtered["location_clean"].isin(i_sel_locations)]
    if i_sel_equip:
        i_filtered = i_filtered[i_filtered["pit_equipment_type"].isin(i_sel_equip)]
    if i_sel_days:
        i_filtered = i_filtered[i_filtered["day_of_week"].isin(i_sel_days)]
    if i_sel_hours:
        i_filtered = i_filtered[i_filtered["hour_label"].isin(i_sel_hours)]
    if i_sel_report:
        i_filtered = i_filtered[i_filtered["report_status"].isin(i_sel_report)]
    if i_sel_years:
        i_filtered = i_filtered[i_filtered["year"].isin(i_sel_years)]
    if i_sel_months:
        i_filtered = i_filtered[i_filtered["month_name"].isin(i_sel_months)]
    if i_date_range and len(i_date_range) == 2:
        i_filtered = i_filtered[
            (i_filtered["incident_date"].dt.date >= i_date_range[0]) &
            (i_filtered["incident_date"].dt.date <= i_date_range[1])
        ]

    # --- KPI Header ---
    kpi1, kpi2 = st.columns([1, 1])
    with kpi1:
        st.metric("Total Incidents", len(i_filtered))
    with kpi2:
        st.metric("Sites", i_filtered["site"].nunique())

    # --- Row 1: Site + Process Path + Incident Type ---
    r1c1, r1c2, r1c3 = st.columns(3)
    with r1c1:
        st.subheader("Site")
        site_counts = i_filtered["site"].value_counts().reset_index()
        site_counts.columns = ["Site", "Count"]
        if i_chart_type == "Bar Charts":
            fig_site = px.bar(site_counts.head(15), x="Site", y="Count", text="Count", color_discrete_sequence=["#232F3E"])
            fig_site.update_traces(textposition="outside")
        else:
            fig_site = px.pie(site_counts.head(15), values="Count", names="Site")
        st.plotly_chart(fig_site, use_container_width=True)
    with r1c2:
        st.subheader("Process Path")
        path_counts = i_filtered["initial_info_pit_process"].value_counts().reset_index()
        path_counts.columns = ["PIT Process", "Count"]
        if i_chart_type == "Bar Charts":
            fig_path = px.bar(path_counts.head(10), x="Count", y="PIT Process", orientation="h", text="Count", color_discrete_sequence=["#146EB4"])
            fig_path.update_layout(yaxis=dict(autorange="reversed"))
            fig_path.update_traces(textposition="outside")
        else:
            fig_path = px.pie(path_counts.head(10), values="Count", names="PIT Process")
        st.plotly_chart(fig_path, use_container_width=True)
    with r1c3:
        st.subheader("Incident Type")
        pit_type_counts = i_filtered["pit_incident_type"].value_counts().reset_index()
        pit_type_counts.columns = ["PIT Incident Type", "Count"]
        if i_chart_type == "Bar Charts":
            fig_pit_type = px.bar(pit_type_counts, x="PIT Incident Type", y="Count", color="PIT Incident Type", text="Count",
                                  color_discrete_map={"PIT/Pedestrian":"#D13212","PIT/PIT":"#FF9900","PIT/Structure":"#232F3E","PIT/Product":"#146EB4","Other/Unknown":"#879596"})
            fig_pit_type.update_layout(showlegend=False)
            fig_pit_type.update_traces(textposition="outside")
        else:
            fig_pit_type = px.pie(pit_type_counts, values="Count", names="PIT Incident Type",
                                  color="PIT Incident Type", color_discrete_map={"PIT/Pedestrian":"#D13212","PIT/PIT":"#FF9900","PIT/Structure":"#232F3E","PIT/Product":"#146EB4","Other/Unknown":"#879596"})
        st.plotly_chart(fig_pit_type, use_container_width=True)

    # --- Row 2: Location + PIT Type + Reporting Timeliness ---
    r2c1, r2c2, r2c3 = st.columns(3)
    with r2c1:
        st.subheader("Location")
        location_counts = i_filtered["location_clean"].value_counts().reset_index()
        location_counts.columns = ["Location", "Count"]
        if i_chart_type == "Bar Charts":
            fig_location = px.bar(location_counts.head(10), x="Count", y="Location", orientation="h", text="Count", color_discrete_sequence=["#146EB4"])
            fig_location.update_layout(yaxis=dict(autorange="reversed"))
            fig_location.update_traces(textposition="outside")
        else:
            fig_location = px.pie(location_counts.head(10), values="Count", names="Location")
        st.plotly_chart(fig_location, use_container_width=True)
    with r2c2:
        st.subheader("PIT Type")
        equip_counts = i_filtered["pit_equipment_type"].value_counts().reset_index()
        equip_counts.columns = ["PIT Type", "Count"]
        if i_chart_type == "Bar Charts":
            fig_equip = px.bar(equip_counts, x="PIT Type", y="Count", text="Count", color_discrete_sequence=["#FF9900"])
            fig_equip.update_traces(textposition="outside")
            fig_equip.update_layout(xaxis_tickangle=-45)
        else:
            fig_equip = px.pie(equip_counts, values="Count", names="PIT Type")
        st.plotly_chart(fig_equip, use_container_width=True)
    with r2c3:
        st.subheader("Reporting Timeliness")
        report_data = i_filtered.dropna(subset=["report_status"])
        report_counts = report_data["report_status"].value_counts().reset_index()
        report_counts.columns = ["Status", "Count"]
        if i_chart_type == "Bar Charts":
            fig_report = px.bar(report_counts, x="Status", y="Count", text="Count", color="Status",
                                color_discrete_map={"Late Report":"#D13212","Reported On Time":"#1D8102"})
            fig_report.update_traces(textposition="outside")
            fig_report.update_layout(showlegend=False)
        else:
            fig_report = px.pie(report_counts, values="Count", names="Status", color="Status",
                                color_discrete_map={"Late Report":"#D13212","Reported On Time":"#1D8102"})
        st.plotly_chart(fig_report, use_container_width=True)

    # --- Row 3: Day of Week + Time of Day + Resulted in Injury ---
    r3c1, r3c2, r3c3 = st.columns(3)
    with r3c1:
        st.subheader("Day of Week")
        dow_data = i_filtered.dropna(subset=["day_of_week"])
        day_order = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        dow_counts = dow_data["day_of_week"].value_counts().reset_index()
        dow_counts.columns = ["Day", "Count"]
        dow_counts["sort_key"] = dow_counts["Day"].apply(lambda x: day_order.index(x) if x in day_order else 99)
        dow_counts = dow_counts.sort_values("sort_key")
        if i_chart_type == "Bar Charts":
            fig_dow = px.bar(dow_counts, x="Day", y="Count", text="Count", color_discrete_sequence=["#232F3E"])
            fig_dow.update_traces(textposition="outside")
        else:
            fig_dow = px.pie(dow_counts, values="Count", names="Day")
        st.plotly_chart(fig_dow, use_container_width=True)
    with r3c2:
        st.subheader("Time of Day")
        tod_data = i_filtered.dropna(subset=["hour"])
        hour_counts = tod_data.groupby("hour").size().reset_index(name="count")
        hour_counts["hour_label"] = hour_counts["hour"].apply(lambda h: f"{int(h):02d}:00")
        if i_chart_type == "Bar Charts":
            fig_tod = px.bar(hour_counts, x="hour_label", y="count", text="count", labels={"hour_label":"Hour","count":"Incidents"}, color_discrete_sequence=["#146EB4"])
            fig_tod.update_traces(textposition="outside")
        else:
            fig_tod = px.pie(hour_counts, values="count", names="hour_label")
        st.plotly_chart(fig_tod, use_container_width=True)
    with r3c3:
        st.subheader("Resulted in Injury")
        def check_injury(description):
            if pd.isna(description):
                return "No"
            desc = description.lower()
            no_injury_phrases = ["no injur","no injuries","not injured","was not injured","were not injured","no pain","denied any injur","denied injur","no medical","did not report any injur","did not sustain","no one was injured","no one injured","no associate injur","no aa injur","without injury","no reported injur"]
            injury_phrases = ["reported pain","complained of pain","felt pain","injury reported","injuries reported","was injured","were injured","sustained an injury","sustained injur","sent to clinic","sent to amcare","went to amcare","first aid","medical attention","medical treatment","taken to hospital","went to hospital","soreness","bruise","laceration","sprain","strain","fracture","swelling","discomfort","hurting"]
            for phrase in no_injury_phrases:
                if phrase in desc:
                    return "No"
            for phrase in injury_phrases:
                if phrase in desc:
                    return "Yes"
            if "injur" in desc:
                return "No"
            return "No"
        i_filtered["resulted_in_injury"] = i_filtered["initial_info_incident_description"].apply(check_injury)
        injury_counts = i_filtered["resulted_in_injury"].value_counts().reset_index()
        injury_counts.columns = ["Injury", "Count"]
        if i_chart_type == "Bar Charts":
            fig_injury = px.bar(injury_counts, x="Injury", y="Count", text="Count", color="Injury",
                                color_discrete_map={"Yes":"#D13212","No":"#1D8102"})
            fig_injury.update_traces(textposition="outside")
            fig_injury.update_layout(showlegend=False)
        else:
            fig_injury = px.pie(injury_counts, values="Count", names="Injury", color="Injury",
                                color_discrete_map={"Yes":"#D13212","No":"#1D8102"})
        st.plotly_chart(fig_injury, use_container_width=True)

    # --- Incidents Over Time ---
    st.subheader("Incidents Over Time")
    trend = i_filtered.dropna(subset=["incident_date"]).copy()
    trend["month"] = trend["incident_date"].dt.to_period("M").astype(str)
    monthly = trend.groupby("month").size().reset_index(name="count")
    avg_count = monthly["count"].mean() if not monthly.empty else 0
    fig_trend = px.bar(monthly, x="month", y="count", labels={"month":"Month","count":"Incidents"}, text="count", color_discrete_sequence=["#FF9900"])
    fig_trend.update_layout(xaxis_tickangle=-45)
    fig_trend.update_traces(textposition="outside")
    if avg_count > 0:
        fig_trend.add_hline(y=avg_count, line_dash="dash", line_color="red", line_width=2,
                            annotation_text=f"Avg: {avg_count:.1f}", annotation_position="top right",
                            annotation_font_color="red", annotation_font_size=14)
    st.plotly_chart(fig_trend, use_container_width=True)

    # --- DATA TABLE ---
    st.markdown("---")
    st.subheader("PIT Incident Raw Data")
    display_cols = ["site", "incident_date", "potential_severity", "status",
                    "initial_info_pit_process", "initial_info_incident_location",
                    "pit_incident_type", "initial_info_incident_description"]
    available_cols = [c for c in display_cols if c in i_filtered.columns]
    st.dataframe(
        i_filtered[available_cols].sort_values("incident_date", ascending=False),
        use_container_width=True,
        height=400
    )

# Footer
st.markdown("---")
st.caption("R2L PIT Tiger Team Dashboard | Data source: Near Miss Details Export & PIT Incident Data")
