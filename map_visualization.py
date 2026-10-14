import folium
import branca.colormap as cm
import numpy as np
import pandas as pd
import base64
import html

from io import BytesIO
from scipy.interpolate import griddata
from scipy.ndimage import gaussian_filter
from PIL import Image
from matplotlib import colormaps

from config import (
    MAP_CENTER,
    MAP_ZOOM,
    COLORS,
    OUTPUT
)



def add_smooth_haze(m, haze):

    haze = haze.dropna(
        subset=["latitude", "longitude", "pm2_5"]
    ).copy()

    if len(haze) < 3:
        print("Not enough haze data")
        return

    points = haze[
        ["longitude", "latitude"]
    ].to_numpy(dtype=float)

    values = haze["pm2_5"].to_numpy(dtype=float)

    lon_min = float(haze["longitude"].min())
    lon_max = float(haze["longitude"].max())
    lat_min = float(haze["latitude"].min())
    lat_max = float(haze["latitude"].max())

    width = 500
    height = 350

    grid_lon, grid_lat = np.meshgrid(
        np.linspace(lon_min, lon_max, width),
        np.linspace(lat_min, lat_max, height)
    )

    grid_pm25 = griddata(
        points,
        values,
        (grid_lon, grid_lat),
        method="linear"
    )

    # Smooth valid values without spreading NaNs
    valid = np.isfinite(grid_pm25)

    weights = gaussian_filter(
        valid.astype(float),
        sigma=3
    )

    smoothed_values = gaussian_filter(
        np.nan_to_num(grid_pm25),
        sigma=3
    )

    grid_pm25 = np.where(
        weights > 0.01,
        smoothed_values / np.maximum(weights, 1e-8),
        np.nan
    )

    # Normalize PM2.5 values
    normalized = np.clip(
        grid_pm25 / 100.0,
        0,
        1
    )

    cmap = colormaps["YlOrRd"]

    rgba = (
        cmap(np.nan_to_num(normalized)) * 255
    ).astype(np.uint8)

    # Edge fading to remove rectangular boundaries
    y = np.linspace(0, 1, height)
    x = np.linspace(0, 1, width)

    fade_width = 0.08

    fade_x = np.minimum(
        np.minimum(x, 1 - x) / fade_width,
        1
    )

    fade_y = np.minimum(
        np.minimum(y, 1 - y) / fade_width,
        1
    )

    edge_fade = (
        fade_y[:, None] * fade_x[None, :]
    )

    # Transparency
    alpha = np.where(
        np.isfinite(grid_pm25),
        70 * edge_fade,
        0
    )

    rgba[:, :, 3] = alpha.astype(np.uint8)

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

    folium.raster_layers.ImageOverlay(
        image=image_url,
        bounds=[
            [lat_min, lon_min],
            [lat_max, lon_max]
        ],
        name="Smooth Haze - PM2.5 (Modelled)",
        opacity=1,
        overlay=True,
        control=True,
        show=False,
        interactive=False
    ).add_to(m)

    print("Smooth haze overlay added")


def create_map(estates, gps_points, fires, haze):

    #create the folium map
    m = folium.Map(
        location=MAP_CENTER,
        zoom_start=MAP_ZOOM,
        tiles=None,
        prefer_canvas=True
    )

    # Basemap
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/"
            "rest/services/World_Street_Map/"
            "MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Tiles © Esri",
        name="Esri World Street Map",
        overlay=False
    ).add_to(m)

    # Legend for PM2.5 -- haze
    legend = cm.LinearColormap(
            colors=[
                "#ffffcc",
                "#ffeda0",
                "#feb24c",
                "#f03b20",
                "#bd0026"
            ],
            vmin=0,
            vmax=100,
            caption="Modelled PM2.5 (µg/m³)"
        )
    
    legend.add_to(m)

    # Estate polygons
    for company, group in estates.groupby("Company"):

        color = COLORS.get(company, "#888888")

        layer = folium.FeatureGroup(
            name=f"{company} - Polygons"
        )

        folium.GeoJson(
            group[
                ["Company", "SupplyBase", "SBType", "geometry"]
            ].to_json(),
            style_function=lambda feature, c=color: {
                "color": c,
                "fillColor": c,
                "weight": 0.25,
                "fillOpacity": 0.35
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["Company", "SupplyBase", "SBType"]
            )
        ).add_to(layer)

        layer.add_to(m)

    # GPS reference points (selected companies)
    gps_companies = [
        "Bumitama Agri",
        "Sarawak Plantation Berhad"
    ]

    selected_points = gps_points[
        gps_points["Company"].isin(gps_companies)
    ]

    for company, group in selected_points.groupby("Company"):

        gps_layer = folium.FeatureGroup(
            name=f"{company} - GPS Points",
            show=True
        )

        for _, point in group.iterrows():

            color = COLORS.get(company, "#555555")

            folium.CircleMarker(
                location=[
                    float(point.geometry.y),
                    float(point.geometry.x)
                ],
                radius=2,
                color=color,
                weight=1,
                fill=True,
                fill_color=color,
                fill_opacity=0.9,
                tooltip=(
                    f"Company: {company}"
                    f" | Estate: {point['Estate_Name']}"
                    f" | GPS Reference Point"
                )
            ).add_to(gps_layer)

        gps_layer.add_to(m)

    # NASA fire hotspots
    fire_layer = folium.FeatureGroup(
        name="NASA Fire Hotspots",
        show=True
    )

    for _, fire in fires.iterrows():

        folium.CircleMarker(
            location=[
                float(fire["latitude"]),
                float(fire["longitude"])
            ],
            radius=2,
            color="#e63946",
            weight=0,
            fill=True,
            fill_color="#e63946",
            fill_opacity=0.8,
            tooltip=(
                f"Date: {fire['acq_date']} | "
                f"FRP: {fire['frp']} MW"
            )
        ).add_to(fire_layer)

    fire_layer.add_to(m)

    # Add smooth haze
    add_smooth_haze(m, haze)

    folium.LayerControl(
        collapsed=False
    ).add_to(m)

    OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )
  

    m.save(str(OUTPUT))

    print("Map saved:", OUTPUT)