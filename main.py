from estate_data import load_estates
from coverage import plan_coverage
from coverage import plan_coverage
from fire_data import get_all_fires
from haze_data import get_haze_grid
from haze_data import get_estate_haze_locations
from exposure_analysis import (
    calculate_fire_exposure,
    calculate_haze_exposure
)
from map_visualization import create_map
from dashboard.build_dashboard import build_dashboard


def main():

    # Step 1: Load Estate Data
    print("Loading estate data...")
    estates, gps_points = load_estates()

    plan = plan_coverage(estates, gps_points)
    print(f"Dynamic coverage: {len(plan.fire_tiles)} FIRMS region tiles; "
          f"{len(plan.haze_coordinates)} CAMS sample positions")

    plan = plan_coverage(estates, gps_points)
    print(f"Dynamic coverage: {len(plan.fire_tiles)} FIRMS region tiles; "
          f"{len(plan.haze_coordinates)} CAMS sample positions")

    # Step 2: Fetch Fire Data
    print("Fetching NASA fire hotspots...")
    fires = get_all_fires(plan)

    # Step 3: Fetch Haze Data
    print("Fetching haze data...")
    haze_locations = get_estate_haze_locations(
        estates,
        gps_points
    )

    haze = get_haze_grid(haze_locations)

    # Step 4: Calculate Rankings
    print("Calculating fire exposure...")
    fire_ranking = calculate_fire_exposure(fires)

    print("Calculating haze exposure...")
    haze_ranking = calculate_haze_exposure(haze)

    # Step 5: Generate Map
    print("Creating interactive map...")
    create_map(
        estates=estates,
        gps_points=gps_points,
        fires=fires,
        haze=haze
    )

    # Step 6: Generate Dashboard
    print("Creating dashboard...")
    build_dashboard(
        fire_ranking=fire_ranking,
        haze_ranking=haze_ranking
    )

    print("Dashboard completed!")



if __name__ == "__main__":
    main()