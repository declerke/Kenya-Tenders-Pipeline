"""
Kenya Tenders Intelligence — Streamlit Dashboard
4 pages: Overview | By Entity | By Sector | Active Tenders
"""

import os

import pandas as pd
import plotly.express as px
import psycopg2
import streamlit as st

st.set_page_config(
    page_title="Kenya Tenders Intelligence",
    page_icon="🏛",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_conn():
    return psycopg2.connect(
        host=os.getenv("APP_DB_HOST", "postgres"),
        port=int(os.getenv("APP_DB_PORT", 5432)),
        dbname=os.getenv("APP_DB_NAME", "tenders_db"),
        user=os.getenv("APP_DB_USER", "postgres"),
        password=os.getenv("APP_DB_PASSWORD", "postgres"),
    )


@st.cache_data(ttl=3600)
def load_kpis() -> dict:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM raw.tenders")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM raw.tenders WHERE status = 'Open'")
            open_count = cur.fetchone()[0]
            cur.execute("""
                SELECT COUNT(*) FROM raw.tenders
                WHERE status = 'Open'
                AND deadline_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days'
            """)
            closing_soon = cur.fetchone()[0]
            cur.execute("SELECT COUNT(DISTINCT procuring_entity) FROM raw.tenders WHERE procuring_entity != 'Not Disclosed'")
            unique_entities = cur.fetchone()[0]
        return {
            "total": total,
            "open": open_count,
            "closing_soon": closing_soon,
            "entities": unique_entities,
        }
    finally:
        conn.close()


@st.cache_data(ttl=3600)
def load_status_breakdown() -> pd.DataFrame:
    conn = get_conn()
    try:
        return pd.read_sql(
            "SELECT status, COUNT(*) AS count FROM raw.tenders GROUP BY status ORDER BY count DESC",
            conn,
        )
    finally:
        conn.close()


@st.cache_data(ttl=3600)
def load_sector_breakdown() -> pd.DataFrame:
    conn = get_conn()
    try:
        return pd.read_sql(
            """
            SELECT COALESCE(sector_tag, 'Other') AS sector_tag, COUNT(*) AS count
            FROM raw.tenders
            GROUP BY sector_tag
            ORDER BY count DESC
            """,
            conn,
        )
    finally:
        conn.close()


@st.cache_data(ttl=3600)
def load_mart_by_entity() -> pd.DataFrame:
    conn = get_conn()
    try:
        return pd.read_sql(
            "SELECT * FROM marts.mart_by_entity ORDER BY tender_count DESC",
            conn,
        )
    finally:
        conn.close()


@st.cache_data(ttl=3600)
def load_mart_by_sector() -> pd.DataFrame:
    conn = get_conn()
    try:
        return pd.read_sql(
            "SELECT * FROM marts.mart_by_sector ORDER BY tender_count DESC",
            conn,
        )
    finally:
        conn.close()


@st.cache_data(ttl=3600)
def load_active_tenders() -> pd.DataFrame:
    conn = get_conn()
    try:
        return pd.read_sql(
            "SELECT * FROM marts.mart_active_tenders",
            conn,
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------

st.sidebar.title("Kenya Tenders Intelligence")
st.sidebar.markdown("Live Kenya government & NGO procurement intelligence")
st.sidebar.divider()

page = st.sidebar.radio(
    "Navigate",
    ["Overview", "By Procuring Entity", "By Sector", "Active Tenders"],
    index=0,
)

st.sidebar.divider()
st.sidebar.caption("Data: TendersKenya.co.ke (live)")
st.sidebar.caption("NLP: spaCy en_core_web_sm")

# ---------------------------------------------------------------------------
# Page 1: Overview
# ---------------------------------------------------------------------------

if page == "Overview":
    st.title("Kenya Government Procurement — Overview")
    st.markdown("Real procurement intelligence sourced from the Kenya Government Tenders dataset.")

    try:
        kpis = load_kpis()
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Tenders", f"{kpis['total']:,}")
        with col2:
            st.metric("Open Tenders", f"{kpis['open']:,}")
        with col3:
            st.metric("Closing This Week", f"{kpis['closing_soon']:,}")
        with col4:
            st.metric("Known Entities", f"{kpis['entities']:,}")

        st.divider()
        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("Tenders by Status")
            status_df = load_status_breakdown()
            if not status_df.empty:
                fig = px.bar(
                    status_df,
                    x="count",
                    y="status",
                    orientation="h",
                    color="status",
                    color_discrete_map={
                        "Open": "#2ecc71",
                        "Closed": "#e74c3c",
                        "Awarded": "#3498db",
                        "Cancelled": "#e67e22",
                        "Other": "#95a5a6",
                    },
                    labels={"count": "Number of Tenders", "status": "Status"},
                )
                fig.update_layout(showlegend=False, height=350)
                st.plotly_chart(fig, use_container_width=True)

        with col_right:
            st.subheader("Tenders by Sector")
            sector_df = load_sector_breakdown()
            if not sector_df.empty:
                fig = px.pie(
                    sector_df,
                    values="count",
                    names="sector_tag",
                    hole=0.35,
                    color_discrete_sequence=px.colors.qualitative.Set2,
                )
                fig.update_layout(height=350)
                st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Could not load data: {e}")
        st.info("Ensure the pipeline has run and the database is accessible.")

# ---------------------------------------------------------------------------
# Page 2: By Procuring Entity
# ---------------------------------------------------------------------------

elif page == "By Procuring Entity":
    st.title("Procurement by Entity")
    st.markdown("Entities with 2 or more tenders in the dataset.")

    try:
        df = load_mart_by_entity()

        if df.empty:
            st.warning("No entity data available yet. Run the pipeline first.")
        else:
            # Exclude "Not Disclosed" aggregation — not meaningful for a chart
            chart_df = df[df["procuring_entity"] != "Not Disclosed"].head(15)
            if chart_df.empty:
                st.info("Entity names are not public on this data source. Showing aggregate table below.")
            else:
                fig = px.bar(
                    chart_df,
                    x="tender_count",
                    y="procuring_entity",
                    orientation="h",
                    color="tender_count",
                    color_continuous_scale="Blues",
                    labels={"tender_count": "Tender Count", "procuring_entity": "Entity"},
                    title="Top Entities by Tender Count (named entities only)",
                )
                fig.update_layout(height=400, showlegend=False, yaxis={"categoryorder": "total ascending"})
                st.plotly_chart(fig, use_container_width=True)

            st.subheader("Full Entity Table")
            display_df = df.copy()
            display_df["total_value_kes"] = display_df["total_value_kes"].apply(
                lambda v: f"KES {v/1_000_000:.2f}M" if pd.notna(v) and v > 0 else "N/A"
            )
            display_df["avg_value_kes"] = display_df["avg_value_kes"].apply(
                lambda v: f"KES {v/1_000_000:.2f}M" if pd.notna(v) and v > 0 else "N/A"
            )
            if "last_seen" in display_df.columns:
                display_df = display_df.drop(columns=["last_seen"])
            st.dataframe(display_df, use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"Could not load entity data: {e}")

# ---------------------------------------------------------------------------
# Page 3: By Sector
# ---------------------------------------------------------------------------

elif page == "By Sector":
    st.title("Procurement by Sector")
    st.markdown("NLP-classified sectors using spaCy rule-based keyword matching.")

    try:
        df = load_mart_by_sector()

        if df.empty:
            st.warning("No sector data available yet. Run the pipeline first.")
        else:
            fig = px.bar(
                df,
                x="sector_tag",
                y="tender_count",
                color="sector_tag",
                color_discrete_sequence=px.colors.qualitative.Pastel,
                labels={"tender_count": "Tender Count", "sector_tag": "Sector"},
                title="Tenders per Sector",
            )
            fig.update_layout(showlegend=False, height=400)
            st.plotly_chart(fig, use_container_width=True)

            st.subheader("Sector Summary Table")
            display_df = df.copy()
            display_df["total_value_kes"] = display_df["total_value_kes"].apply(
                lambda v: f"KES {v/1_000_000:.1f}M" if pd.notna(v) and v > 0 else "N/A"
            )
            display_df["avg_value_kes"] = display_df["avg_value_kes"].apply(
                lambda v: f"KES {v/1_000_000:.1f}M" if pd.notna(v) and v > 0 else "N/A"
            )
            st.dataframe(display_df, use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"Could not load sector data: {e}")

# ---------------------------------------------------------------------------
# Page 4: Active Tenders
# ---------------------------------------------------------------------------

elif page == "Active Tenders":
    st.title("Active Tenders")
    st.markdown("Open tenders with non-expired deadlines, ordered by urgency.")

    try:
        df = load_active_tenders()

        if df.empty:
            st.info("No active tenders found. All tenders may be closed or pipeline needs to run.")
        else:
            # Sidebar filters
            st.sidebar.subheader("Filters")

            # Sector filter
            sectors = ["All"] + sorted(df["sector_tag"].dropna().unique().tolist())
            selected_sector = st.sidebar.selectbox("Sector", sectors)

            # Entity search
            entity_query = st.sidebar.text_input("Entity Search", placeholder="e.g. Nairobi")

            # Apply filters
            filtered = df.copy()
            if selected_sector != "All":
                filtered = filtered[filtered["sector_tag"] == selected_sector]
            if entity_query:
                filtered = filtered[
                    filtered["procuring_entity"].str.contains(entity_query, case=False, na=False)
                ]

            st.markdown(f"Showing **{len(filtered)}** active tenders")

            # Highlight urgent rows (deadline < 7 days)
            def highlight_urgent(row):
                if pd.notna(row.get("days_to_deadline")) and row["days_to_deadline"] < 7:
                    return ["background-color: #fff3cd"] * len(row)
                return [""] * len(row)

            display_df = filtered[[
                "tender_number", "procuring_entity", "description",
                "estimated_value_kes", "deadline_date", "days_to_deadline", "sector_tag"
            ]].copy()

            display_df["estimated_value_kes"] = display_df["estimated_value_kes"].apply(
                lambda v: f"KES {v:,.0f}" if pd.notna(v) and v > 0 else "N/A"
            )
            display_df.columns = [
                "Ref", "Entity", "Description",
                "Est. Value", "Deadline", "Days Left", "Sector"
            ]

            st.dataframe(
                display_df.style.apply(highlight_urgent, axis=1),
                use_container_width=True,
                hide_index=True,
            )
            st.caption("Yellow rows: deadline within 7 days")

    except Exception as e:
        st.error(f"Could not load active tenders: {e}")
