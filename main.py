from estate_data import load_estates
from fire_data import get_all_fires
from haze_data import get_haze_grid
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

    # Step 2: Fetch Fire Data
    print("Fetching NASA fire hotspots...")
    fires = get_all_fires()

    # Step 3: Fetch Haze Data
    print("Fetching haze data...")
    haze = get_haze_grid()

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