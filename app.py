"""Application Streamlit pour le simulateur Capacite-Commande."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from src.data_loader import load_data
from src.model import solve_model


DATA_PATH = Path("Donnees_MaghrebSteel.xlsx")


st.set_page_config(page_title="Maghreb Steel - Simulateur Capacite-Commande", layout="wide")
st.title("Simulateur Capacite-Commande")

with st.sidebar:
    st.header("Scenario")
    hrc_multiplier = st.slider("Prix HRC", 0.8, 1.3, 1.0, 0.05)
    extra_lgb_stop = st.number_input("Arret LGB supplementaire S2 (jours)", 0.0, 5.0, 0.0, 0.5)
    campaigns = st.checkbox("Activer les campagnes binaires", value=False)
    relax = st.checkbox("Relaxation LP", value=False)
    time_limit = st.slider("Temps limite solveur (s)", 30, 300, 120, 30)

data = load_data(DATA_PATH)
st.subheader("Carnet de commandes")
edited_orders = st.data_editor(
    data.orders,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "Tonnage": st.column_config.NumberColumn(min_value=0.0),
        "Prix": st.column_config.NumberColumn(min_value=0.0),
        "DueWeek": st.column_config.NumberColumn(min_value=1, max_value=4),
    },
)

run = st.button("Relancer le calcul", type="primary")
if run:
    scenario_data = data.__class__(
        orders=edited_orders,
        cadences=data.cadences,
        yields=data.yields,
        scrap_rates=data.scrap_rates,
        downgraded_rates=data.downgraded_rates,
        nonconforming_rates=data.nonconforming_rates,
        costs=data.costs,
        hrc_prices=data.hrc_prices,
        hrc_availability=data.hrc_availability,
        finished_stocks=data.finished_stocks,
        interprocess_stocks=data.interprocess_stocks,
        pk_stocks=data.pk_stocks,
        stops=data.stops,
        params=data.params,
    )
    with st.spinner("Resolution PuLP/CBC en cours..."):
        result = solve_model(
            scenario_data,
            campaigns=campaigns,
            relax=relax,
            hrc_multiplier=hrc_multiplier,
            extra_lgb_stop_week2=extra_lgb_stop,
            time_limit=time_limit,
        )

    total_t = result.orders["tonnage"].sum()
    served_t = result.orders.loc[result.orders["accepted"], "tonnage"].sum()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Statut", result.status)
    c2.metric("Marge", f"{result.objective/1_000_000:.2f} MMAD")
    c3.metric("Taux de service", f"{served_t/total_t:.1%}")
    c4.metric("Commandes refusees", int((~result.orders["accepted"]).sum()))

    tab1, tab2, tab3, tab4 = st.tabs(["Plan", "Goulots", "Commandes", "HRC"])
    with tab1:
        plan = result.capacity[result.capacity["used_t"] > 1e-6].copy()
        st.dataframe(plan, use_container_width=True)
        fig = px.bar(plan, x="week", y="used_t", color="family", facet_row="line", barmode="stack")
        st.plotly_chart(fig, use_container_width=True)
    with tab2:
        bottlenecks = result.capacity.sort_values("utilization", ascending=False).head(20)
        st.dataframe(bottlenecks, use_container_width=True)
        st.plotly_chart(
            px.bar(bottlenecks, x="utilization", y="line", color="family", orientation="h"),
            use_container_width=True,
        )
    with tab3:
        st.dataframe(result.orders, use_container_width=True)
        st.download_button(
            "Telecharger les commandes",
            result.orders.to_csv(index=False).encode("utf-8-sig"),
            "commandes_resultat.csv",
            "text/csv",
        )
    with tab4:
        st.dataframe(result.hrc, use_container_width=True)
        st.plotly_chart(px.bar(result.hrc, x="grade", y=["used_t", "available_t"], barmode="group"), use_container_width=True)
else:
    st.info("Modifiez le carnet ou le scenario, puis lancez le calcul.")
