from pathlib import Path
import json

import numpy as np
import pandas as pd
from PIL import Image,ImageFilter
from scipy.spatial import cKDTree

from exposure_analysis import xyz, EARTH_KM

# Visual settings
MAX_DISTANCE_KM = 65
IMAGE_WIDTH = 1400
MAX_IMAGE_HEIGHT = 1600


COLORS = [
    (0,   45, 160, 230),    # Bright blue
    (15,  30, 195, 215),    # Cyan
    (25,  65, 205, 95),     # Vivid green
    (35,  255, 210, 45),    # Bright yellow
    (55,  255, 115, 35),    # Orange
    (100, 225, 35, 65),     # Strong red
]



def create_haze_overlay(haze, output_dir):
    """
    Generate a smoothed transparent PM2.5 overlay.

    Files:
      haze_overlay.png
      haze_overlay.json

    Pixels beyond MAX_DISTANCE_KM from observed/modelled
    sample positions remain fully transparent.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    data = haze.copy()

    for field in ["latitude", "longitude", "pm2_5"]:
        data[field] = pd.to_numeric(
            data[field], errors="coerce"
        )

    data = data.dropna(
        subset=["latitude", "longitude", "pm2_5"]
    )

    data = data[
        data.latitude.between(-90, 90) &
        data.longitude.between(-180, 180) &
        (data.pm2_5 >= 0)
    ].copy()

    if "time" in data.columns and not data.empty:
        data = data[
            data["time"] == data["time"].max()
        ].copy()

    data = data.drop_duplicates(
        ["latitude", "longitude"],
        keep="last"
    )

    if data.empty:
        raise ValueError("No valid haze samples")

    # Include a small margin around model samples.
    margin = 0.85
    south = max(-90, data.latitude.min() - margin)
    north = min(90, data.latitude.max() + margin)
    west = max(-180, data.longitude.min() - margin)
    east = min(180, data.longitude.max() + margin)

    width = IMAGE_WIDTH
    height = int(
        width * (north - south) / (east - west)
    )
    height = max(100, min(height, MAX_IMAGE_HEIGHT))

    # Pixel positions are geographic coordinates.
    lons = np.linspace(west, east, width)
    lats = np.linspace(north, south, height)
    lon_grid, lat_grid = np.meshgrid(lons, lats)

    sample_xyz = xyz(
        data.latitude.to_numpy(),
        data.longitude.to_numpy()
    )

    tree = cKDTree(sample_xyz)

    output = np.zeros(
        (height * width, 4),
        dtype=np.uint8
    )

    values = data.pm2_5.to_numpy(dtype=float)

    # Process in chunks to limit memory usage.
    chunk_size = 30000

    for start in range(0, len(output), chunk_size):
        end = min(start + chunk_size, len(output))

        query_xyz = xyz(
            lat_grid.ravel()[start:end],
            lon_grid.ravel()[start:end]
        )

        k = min(8, len(values))

        chord_distances, indices = tree.query(
            query_xyz, k=k
        )

        distances = np.atleast_2d(chord_distances)
        indices = np.atleast_2d(indices)

        if k == 1:
            distances = chord_distances[:, None]
            indices = indices[:, None]

        distances_km = (
            2 * EARTH_KM *
            np.arcsin(
                np.clip(distances / 2, 0, 1)
            )
        )

        nearest = distances_km[:, 0]
        valid = nearest <= MAX_DISTANCE_KM

        # IDW interpolation using 4 nearest samples.
        weights = 1 / np.maximum(
            distances_km, 0.1
        ) ** 2

        interpolated = (
            np.sum(weights * values[indices], axis=1) /
            np.sum(weights, axis=1)
        )

        concentrations = np.array(
            [c[0] for c in COLORS],
            dtype=float
        )

        rgb = np.column_stack([
            np.interp(
                interpolated,
                concentrations,
                [c[channel] for c in COLORS]
            )
            for channel in range(1, 4)
        ])

        # Smooth fade at the data coverage edge.
        distance_fade = np.clip(
            (MAX_DISTANCE_KM - nearest) / 36,
            0, 1
        )

        value_alpha = np.interp(
            interpolated,
            concentrations,
            [70, 85, 100, 118, 138, 155]
        )

        alpha = distance_fade * value_alpha
        
        pixels = output[start:end]
        pixels[:, :3] = rgb.astype(np.uint8)
        pixels[:, 3] = np.where(
            valid, alpha, 0
        ).astype(np.uint8)

    image = Image.fromarray(
        output.reshape(height, width, 4),
        mode="RGBA"
    )

    # Smooth the overlay so it looks like haze,
    # not separate circles / cells.
    image = image.filter(ImageFilter.GaussianBlur(radius=15))

    image.save(out / "haze_overlay.png")

    metadata = {
        "bounds": [
            [float(south), float(west)],
            [float(north), float(east)]
        ],
        "sample_count": len(data),
        "method": "IDW visualization",
        "max_distance_km": MAX_DISTANCE_KM,
        "model_time": (
            str(data["time"].max())
            if "time" in data else None
        )
    }

    (out / "haze_overlay.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8"
    )

    print("Haze overlay generated")

    return metadata
