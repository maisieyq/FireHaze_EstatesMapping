
from dataclasses import dataclass
import math

FIRE_TILE_DEG = 4.0
FIRE_RADIUS_KM = 10.0

# Maximum additional map-background samples
MAX_BACKGROUND_POINTS = 700

# Approximate sampling step for visual haze overlay
HAZE_GRID_STEP = 0.6


@dataclass
class CoveragePlan:
    haze_coordinates: list
    fire_tiles: list
    footprint_bounds: tuple


def tile_bbox(tile):
    x, y = tile

    return (
        x * FIRE_TILE_DEG,
        y * FIRE_TILE_DEG,
        (x + 1) * FIRE_TILE_DEG,
        (y + 1) * FIRE_TILE_DEG
    )


def tile_id(tile):
    return f"{tile[0]}_{tile[1]}"


def fire_tiles_for_bounds(bounds):
    west, south, east, north = bounds

    epsilon = 1e-9

    x0 = math.floor(west / FIRE_TILE_DEG)
    x1 = math.floor((east - epsilon) / FIRE_TILE_DEG)

    y0 = math.floor(south / FIRE_TILE_DEG)
    y1 = math.floor((north - epsilon) / FIRE_TILE_DEG)

    return {
        (x, y)
        for x in range(x0, x1 + 1)
        for y in range(y0, y1 + 1)
    }


def plan_coverage(points):
    locations = set()

    for row in points.itertuples(index=False):
        lat = float(row.latitude)
        lon = float(row.longitude)

        locations.add((
            round(lat, 5),
            round(lon, 5)
        ))

    if not locations:
        raise ValueError("No valid estate coordinates")

    footprint_bounds = (
            min(lon for lat, lon in locations),
            min(lat for lat, lon in locations),
            max(lon for lat, lon in locations),
            max(lat for lat, lon in locations)
        )

    
    # Fire tiles covering each estate's 10 km radius.
    fire_tiles = set()

    for lat, lon in locations:
        lat_pad = FIRE_RADIUS_KM / 111.0

        lon_pad = FIRE_RADIUS_KM / (
            111.0 * max(
                0.1,
                math.cos(math.radians(lat))
            )
        )

        bounds = (
            lon - lon_pad,
            lat - lat_pad,
            lon + lon_pad,
            lat + lat_pad
        )

        fire_tiles.update(
            fire_tiles_for_bounds(bounds)
        )

    # Background haze grid for map visualization.
    # Use a regular grid across the whole plantation footprint
    # so the middle area is also sampled.

    background = set()

    west, south, east, north = footprint_bounds

    # Expand coverage a bit around plantation area
    pad_deg = 1.5
    west -= pad_deg
    south -= pad_deg
    east += pad_deg
    north += pad_deg

    lat_start = math.floor(south / HAZE_GRID_STEP) * HAZE_GRID_STEP
    lat_end = math.ceil(north / HAZE_GRID_STEP) * HAZE_GRID_STEP

    lon_start = math.floor(west / HAZE_GRID_STEP) * HAZE_GRID_STEP
    lon_end = math.ceil(east / HAZE_GRID_STEP) * HAZE_GRID_STEP

    lat = lat_start
    while lat <= lat_end + 1e-9:
        lon = lon_start
        while lon <= lon_end + 1e-9:
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                background.add((
                    round(lat, 5),
                    round(lon, 5)
                ))
            lon += HAZE_GRID_STEP
        lat += HAZE_GRID_STEP

    background = sorted(background - locations)


    


    haze_coordinates = sorted(
        locations | set(background)
    )

    
    print("Estate coordinate locations:", len(locations))
    print("Extra haze map samples:", len(background))
    print("Total haze requests:", len(haze_coordinates))
    print("NASA fire tiles:", len(fire_tiles))

    return CoveragePlan(
        haze_coordinates=haze_coordinates,
        fire_tiles=sorted(fire_tiles),
        footprint_bounds=footprint_bounds
    )
