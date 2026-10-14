"""Drop-in Folium map visualization for the Fire/Haze/Estates project.

The haze layer is modelled CAMS/Open-Meteo PM2.5 (not a visible smoke plume
and not Malaysia's official API). The purple PM2.5 bands are designed to be
visually distinct from orange NASA FIRMS thermal anomalies and cool-coloured
palm oil plantation boundaries.
"""

import base64
import html
from io import BytesIO

import branca.colormap as cm
import folium
import numpy as np
import pandas as pd
from contourpy import contour_generator
from folium.plugins import HeatMap
from PIL import Image
from scipy.interpolate import griddata
from scipy.spatial import cKDTree

from config import MAP_CENTER, MAP_ZOOM, OUTPUT

# Modelled PM2.5 visual bins, in ug/m3. These are NOT official Malaysian API bands.
PM25_LEVELS = [0, 12, 25, 35, 55, 75, 100]
PM25_COLOR_BINS = [
    "#62B2FF",  # 0-12:  light blue
    "#3389FF",  # 12-25: blue
    "#5963F8",  # 25-35: indigo
    "#8454F4",  # 35-55: purple
    "#AD68F3",  # 55-75: violet
    "#C39BF9",  # 75-100: lavender
    "#EEE0FF",  # 100+: pale purple
]
PM25_ALPHA_BINS = [40, 125, 155, 180, 202, 218, 235]
PM25_DISPLAY_CAP = 100.0

# Cool/bright boundaries remain distinct from both haze and fires.
COMPANY_DISPLAY_COLORS = {
    "United Plantations Berhad": "#2EF0C9",
    "Bumitama Agri": "#A5FFF3",
    "IOI Corporation": "#75E2FF",
    "SD Guthrie": "#AEFF9A",
    "Sarawak Plantation Berhad": "#C8FFE4",
    "Hap Seng Plantations": "#F4FBFF",
}


def _to_image_url(rgba):
    image = Image.fromarray(np.flipud(rgba), "RGBA")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")



def add_high_contrast_haze(m, haze):

    import base64
    from io import BytesIO
    from PIL import Image
    from scipy.ndimage import gaussian_filter

    data = haze.copy()

    required = ["latitude", "longitude", "pm2_5"]

    for col in required:
        data[col] = pd.to_numeric(
            data[col], errors="coerce"
        )

    data = data.dropna(subset=required)

    data = data[
        (data["pm2_5"] >= 0)
        & data["latitude"].between(-90, 90)
        & data["longitude"].between(-180, 180)
    ]

    if "time" in data.columns:
        data = data.sort_values("time")

    data = data.drop_duplicates(
        ["latitude", "longitude"],
        keep="last"
    )

    if data.empty:
        print("No valid Haze data")
        return

    # Approximate native CAMS model grid spacing
    step = 0.4
    half = step / 2

    lon_min = float(data.longitude.min()) - half
    lon_max = float(data.longitude.max()) + half
    lat_min = float(data.latitude.min()) - half
    lat_max = float(data.latitude.max()) + half

    # Image display resolution only
    width = min(
        2400,
        max(500, int((lon_max - lon_min) * 25))
    )
    height = min(
        1200,
        max(300, int((lat_max - lat_min) * 25))
    )

    rgba = np.zeros(
        (height, width, 4),
        dtype=np.uint8
    )

    levels = [12, 25, 35, 55, 75, 100]

    colors = [
        "#62B2FF",
        "#3389FF",
        "#5963F8",
        "#8454F4",
        "#AD68F3",
        "#B76CE9",
        "#9440C8"
    ]

    alphas = [90, 110, 125, 145, 165, 180, 195]

    for _, row in data.iterrows():

        lat = float(row["latitude"])
        lon = float(row["longitude"])
        pm25 = float(row["pm2_5"])

        color_index = int(
            np.searchsorted(
                levels, pm25, side="right"
            )
        )

        color = colors[color_index]

        rgb = [
            int(color[i:i + 2], 16)
            for i in (1, 3, 5)
        ]

        # Draw the model cell centred on API coordinate
        x0 = int(
            (lon - half - lon_min)
            / (lon_max - lon_min) * width
        )
        x1 = int(
            (lon + half - lon_min)
            / (lon_max - lon_min) * width
        )

        y0 = int(
            (lat - half - lat_min)
            / (lat_max - lat_min) * height
        )
        y1 = int(
            (lat + half - lat_min)
            / (lat_max - lat_min) * height
        )

        x0, x1 = max(0, x0), min(width, x1)
        y0, y1 = max(0, y0), min(height, y1)

        rgba[y0:y1, x0:x1, :3] = rgb
        rgba[y0:y1, x0:x1, 3] = alphas[color_index]

    # Soft visual edges only.
    # Does not interpolate PM2.5 concentrations.
    sigma = 2.5

    alpha = rgba[:, :, 3].astype(float) / 255.0
    premultiplied = (
        rgba[:, :, :3].astype(float)
        * alpha[:, :, None]
    )

    soft_alpha = gaussian_filter(alpha, sigma=sigma)

    soft_rgb = gaussian_filter(
        premultiplied,
        sigma=(sigma, sigma, 0)
    )

    soft_rgb = soft_rgb / np.maximum(
        soft_alpha[:, :, None], 1e-8
    )

    rgba[:, :, :3] = np.clip(
        soft_rgb, 0, 255
    ).astype(np.uint8)

    rgba[:, :, 3] = np.clip(
        soft_alpha * 255, 0, 255
    ).astype(np.uint8)

    # North at top
    rgba = np.flipud(rgba)

    image = Image.fromarray(rgba, "RGBA")

    buffer = BytesIO()
    image.save(buffer, format="PNG")

    image_url = (
        "data:image/png;base64,"
        + base64.b64encode(
            buffer.getvalue()
        ).decode()
    )

    haze_layer = folium.FeatureGroup(
        name="Haze: CAMS PM2.5",
        show=True
    )

    folium.raster_layers.ImageOverlay(
        image=image_url,
        bounds=[
            [lat_min, lon_min],
            [lat_max, lon_max]
        ],
        pane="haze_pane",
        opacity=1,
        interactive=False
    ).add_to(haze_layer)

    haze_layer.add_to(m)

    print(
        f"Displayed {len(data)} PM2.5 model cells"
    )




def add_estate_boundaries(m, estates):
    required = ["Company", "SupplyBase", "SBType", "geometry"]
    for company, group in estates.groupby("Company"):
        color = COMPANY_DISPLAY_COLORS.get(company, "#B8E9DA")
        layer = folium.FeatureGroup(name=f"Estate Boundaries: {company}", show=True)
        folium.GeoJson(
            group[required].to_json(),
            pane="estate_pane",
            style_function=lambda feat, c=color: {
                "color": c, "weight": 0.95, "opacity": 0.98,
                "fillColor": c, "fillOpacity": 0.035,
            },
            highlight_function=lambda feat, c=color: {
                "color": "#FFFFFF", "weight": 2.5,
                "fillColor": c, "fillOpacity": 0.24,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["Company", "SupplyBase", "SBType"],
                aliases=["Company", "Supply Base", "Type"],
            ),
        ).add_to(layer)
        layer.add_to(m)


def add_gps_reference_points(m, gps_points, estates):
    
    companies_with_polygons = set(estates.Company.unique())
    for company, group in gps_points.groupby('Company'):
        is_gps_only = company not in companies_with_polygons
        prefix = 'GPS ONLY - boundary unavailable' if is_gps_only else 'Additional GPS references'
        color = COMPANY_DISPLAY_COLORS.get(company, '#FFFFFF')
        layer = folium.FeatureGroup(name=f'{prefix}: {company}', show=is_gps_only)
        for _, record in group.iterrows():
            name = html.escape(str(record.get('Estate_Name', 'Unknown')))
            availability = 'No polygon boundary supplied' if is_gps_only else 'Reference coordinate, NOT polygon footprint'
            folium.CircleMarker(
                location=[float(record.geometry.y), float(record.geometry.x)],
                radius=4, color='#FFFFFF', weight=1.4,
                fill=True, fill_color=color, fill_opacity=1,
                pane='gps_pane', tooltip=f'GPS reference: {company} / {name}',
                popup=folium.Popup(
                    f'<b>{html.escape(company)}</b><br>{name}<br>{availability}',
                    max_width=300
                )
            ).add_to(layer)
        layer.add_to(m)


def add_fire_hotspots(m, fires):
    if fires is None or fires.empty:
        print("No NASA fire detections; fire layer skipped")
        return
    frame = fires.copy()
    for field in ["latitude", "longitude"]:
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    frame = frame.dropna(subset=["latitude", "longitude"])
    frame = frame[frame.latitude.between(-90, 90) & frame.longitude.between(-180, 180)]
    if "frp" not in frame.columns:
        frame["frp"] = np.nan
    frame["frp"] = pd.to_numeric(frame["frp"], errors="coerce")
    if frame.empty:
        return

    layer = folium.FeatureGroup(name="NASA FIRMS hotspots: fire glow", show=True)
    heat = [
        [float(row.latitude), float(row.longitude),
         float(np.clip(0.22 + np.log1p(max(0.0, row.frp if pd.notna(row.frp) else 0)) / 7.5, 0.22, 1.0))]
        for row in frame.itertuples()
    ]
    HeatMap(
        data=heat,
        radius=9, blur=7, min_opacity=0.025, max_zoom=9,
        pane="fire_glow_pane",
        gradient={.20: "#712a13", .45: "#dd5019", .70: "#ff9625", 1.: "#fff2ad"},
    ).add_to(layer)
    for _, row in frame.iterrows():
        frp = float(row.frp) if pd.notna(row.frp) else 0.0
        radius = float(np.clip(1.3 + 0.43 * np.log1p(max(frp, 0)), 1.5, 3.8))
        dt = html.escape(str(row.get("acq_date", "unknown")))
        folium.CircleMarker(
            location=[float(row.latitude), float(row.longitude)],
            radius=radius, pane="fire_core_pane",
            color="#ff831d", weight=0.55,
            fill=True, fill_color="#fff5b7" if frp >= 20 else "#ffbb55",
            fill_opacity=0.96,
            tooltip=f"NASA thermal anomaly | {dt} | FRP: {frp:.1f} MW",
        ).add_to(layer)
    layer.add_to(m)


def create_map(estates, gps_points, fires, haze):
    m = folium.Map(
        location=MAP_CENTER, zoom_start=MAP_ZOOM,
        tiles=None, prefer_canvas=True,
    )
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri", name="Esri Satellite Imagery", overlay=False,
        show=True,
    ).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri", name="Esri Street Map (optional)", overlay=False,
        show=False,
    ).add_to(m)

    # Explicit pane z-orders make toggling layers predictable.
    for name, z, pointer in [
        ("haze_pane", 340, False),
        ("haze_contour_pane", 385, False),
        ("haze_samples_pane", 400, True),
        ("fire_glow_pane", 410, False),
        ("estate_pane", 450, True),
        ("gps_pane", 475, True),
        ("fire_core_pane", 490, True),
    ]:
        folium.map.CustomPane(name, z_index=z, pointer_events=pointer).add_to(m)

    add_estate_boundaries(m, estates)
    add_gps_reference_points(m, gps_points, estates)
    add_fire_hotspots(m, fires)
    add_high_contrast_haze(m, haze)

    # Legend bins aligned with the displayed bin colours, not the official API.
    cm.StepColormap(
        colors=PM25_COLOR_BINS,
        index=PM25_LEVELS + [200],
        vmin=0, vmax=200,
        caption="Modelled PM2.5 (ug/m3): purple haze bands; 100+ is capped for DISPLAY only",
    ).add_to(m)
    # The map has NO country or fixed bounding box restriction. Fit to all
    # known estate footprints and GPS positions on initial display.
    bounds=[]
    for dataset in (estates,gps_points):
        if dataset is not None and not dataset.empty:
            west,south,east,north=dataset.to_crs('EPSG:4326').total_bounds
            bounds.append((west,south,east,north))
    if bounds:
        m.fit_bounds([[min(v[1] for v in bounds),min(v[0] for v in bounds)],
                      [max(v[3] for v in bounds),max(v[2] for v in bounds)]])
    # Visible source credit. A modelled layer is not an observation or a smoke plume.
    from branca.element import Element
    m.get_root().html.add_child(Element("""<div style="position:fixed;bottom:20px;left:15px;z-index:9999;
        background:rgba(15,23,42,.82);color:white;padding:6px 9px;
        border-radius:6px;font:11px sans-serif;max-width:370px">
        PM2.5: Open-Meteo / CAMS Global model (~45 km), interpolated visual display.<br>
        Fire: NASA FIRMS satellite thermal detections (not confirmed causes).<br>
        Credits: <a style="color:#b8ddff" href="https://open-meteo.com/" target="_blank">Open-Meteo</a>
        · <a style="color:#b8ddff" href="https://ads.atmosphere.copernicus.eu/" target="_blank">CAMS</a>
        · <a style="color:#b8ddff" href="https://firms.modaps.eosdis.nasa.gov/" target="_blank">NASA FIRMS</a>
        </div>"""))
    folium.LayerControl(collapsed=False).add_to(m)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(OUTPUT))
    print("Saved map:", OUTPUT)
    return m
