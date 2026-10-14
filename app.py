
import streamlit as st
import streamlit.components.v1 as components

from config import OUTPUT

from estate_data import load_estates
from fire_data import get_all_fires
from haze_data import get_haze_grid

from exposure_analysis import (
    calculate_fire_exposure,
    calculate_haze_exposure
)

from map_visualization import create_map
from dashboard.build_dashboard import build_dashboard
from dashboard.embed import get_embedded_dashboard


st.set_page_config(
    page_title="Palm Oil Fire & Haze Monitor",
    layout="wide",
    initial_sidebar_state="collapsed"
)


@st.cache_data(ttl=3600, show_spinner=False)
def prepare_dashboard():

    estates, gps_points = load_estates()

    fires = get_all_fires()
    haze = get_haze_grid()

    fire_ranking = calculate_fire_exposure(fires)
    haze_ranking = calculate_haze_exposure(haze)

    create_map(
        estates=estates,
        gps_points=gps_points,
        fires=fires,
        haze=haze
    )

    index_path = build_dashboard(
        fire_ranking=fire_ranking,
        haze_ranking=haze_ranking
    )

    dashboard_html = get_embedded_dashboard(
        index_path=index_path,
        map_path=OUTPUT
    )

    return dashboard_html


with st.spinner("Preparing Fire & Haze Dashboard..."):
    dashboard_html = prepare_dashboard()


# Display complete HTML dashboard
components.html(
    dashboard_html,
    height=850,
    scrolling=False
)
