import geopandas as gpd
from config import GPKG

def load_estates():

    polygons = gpd.read_file(
        GPKG,
        layer="estate_boundaries"
    )

    points = gpd.read_file(
        GPKG,
        layer="estate_reference_points"
    )

    owned = polygons[
        polygons["Eligible_Own_Estate"].eq(True)
    ].copy()

    owned["geometry"] = owned.geometry.simplify(
        150,
        preserve_topology=True
    )

    owned = owned.to_crs("EPSG:4326")
    points = points.to_crs("EPSG:4326")

    print("Estate polygons:", len(owned))
    print("GPS points:", len(points))

    return owned, points