"""Automatic estate-led geographic coverage. No hard-coded country/ASEAN bounds.

Points and polygon footprints both contribute. The coarse CAMS grid is sampled
near the native 0.4-degree resolution rather than creating fictitious detail.
"""
from dataclasses import dataclass
import math

# Native CAMS Global resolution (approximately)
HAZE_STEP = 0.4

# Dynamic regional coverage
HAZE_REGION_DEG = 4.0
HAZE_REGION_BUFFER_DEG = 0.4
HAZE_GRID_MARGIN = 0.4

FIRE_TILE_DEG = 4.0
FIRE_BUFFER_DEG = 0.12  # >= 10 km around estate for latitudes in supplied data


@dataclass
class CoveragePlan:
    haze_coordinates: list  # [(lat, lon), ...] requested model samples
    fire_tiles: list  # [(tile_x, tile_y), ...]
    footprint_bounds: tuple


def _footprints(estates, gps_points):
    for dataset in (estates, gps_points):
        if dataset is None or dataset.empty:
            continue
        if dataset.crs is None:
            raise ValueError("Estate / GPS geometries require a known CRS")
        geo = dataset.to_crs('EPSG:4326')
        for geom in geo.geometry:
            if geom is None or geom.is_empty:
                continue
            bounds = geom.bounds
            if any(not math.isfinite(v) for v in bounds):
                continue
            yield bounds


def _cells(bounds, cell_size, pad):
    west, south, east, north = bounds
    # Explicitly cap globe coordinates before conversion to cell ids.
    west = max(-180., west-pad)
    east = min(180., east+pad)
    south = max(-90., south-pad)
    north = min(90., north+pad)
    for x in range(math.floor(west/cell_size), math.floor(east/cell_size)+1):
        for y in range(math.floor(south/cell_size), math.floor(north/cell_size)+1):
            yield (x, y)


def plan_coverage(estates, gps_points):

    footprints = list(_footprints(estates, gps_points))

    if not footprints:
        raise ValueError(
            "No valid plantation polygons or GPS points"
        )

    haze_regions = set()
    fire_cells = set()

    # Identify regions containing plantations
    for bounds in footprints:
        haze_regions.update(
            _cells(
                bounds,
                HAZE_REGION_DEG,
                HAZE_REGION_BUFFER_DEG
            )
        )

        # Keep existing fire coverage logic
        fire_cells.update(
            _cells(
                bounds,
                FIRE_TILE_DEG,
                FIRE_BUFFER_DEG
            )
        )

    # Build complete regional PM2.5 grids
    cells_per_region = round(
        HAZE_REGION_DEG / HAZE_STEP
    )

    margin = round(
        HAZE_GRID_MARGIN / HAZE_STEP
    )

    haze_cells = set()

    for region_x, region_y in haze_regions:

        min_x = region_x * cells_per_region - margin
        max_x = (region_x + 1) * cells_per_region + margin

        min_y = region_y * cells_per_region - margin
        max_y = (region_y + 1) * cells_per_region + margin

        for y in range(min_y, max_y + 1):

            for x in range(min_x, max_x + 1):

                lat = y * HAZE_STEP
                lon = x * HAZE_STEP

                if -90 <= lat <= 90 and -180 <= lon <= 180:

                    haze_cells.add((x, y))

    # Convert grid indices into coordinates
    haze_coords = [
        (
            round(y * HAZE_STEP, 5),
            round(x * HAZE_STEP, 5)
        )
        for x, y in sorted(
            haze_cells,
            key=lambda cell: (cell[1], cell[0])
        )
    ]

    all_bounds = (
        min(b[0] for b in footprints),
        min(b[1] for b in footprints),
        max(b[2] for b in footprints),
        max(b[3] for b in footprints)
    )

    print(f"Haze regions: {len(haze_regions)}")

    print(f"PM2.5 sample locations: {len(haze_coords)}")

    return CoveragePlan(
        haze_coordinates=haze_coords,
        fire_tiles=sorted(fire_cells),
        footprint_bounds=all_bounds
    )



def tile_bbox(tile):
    x, y = tile
    return (x*FIRE_TILE_DEG, y*FIRE_TILE_DEG,
            (x+1)*FIRE_TILE_DEG, (y+1)*FIRE_TILE_DEG)


def tile_id(tile):
    return f'{tile[0]}_{tile[1]}'


def fire_tiles_for_bounds(bounds):
    return set(_cells(bounds, FIRE_TILE_DEG, FIRE_BUFFER_DEG))
