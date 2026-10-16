
from pathlib import Path
import os
from dotenv import load_dotenv

# Project root (one level above src/)
BASE = Path(__file__).resolve().parent.parent

load_dotenv(BASE / ".env")

MAP_KEY = os.getenv("NASA_MAP_KEY", "").strip()

GPKG = BASE / "source_data" / "all_company_geometries.gpkg"
OUTPUT = BASE / "output" / "estate_fire_map.html"

FIRE_DAYS = 3
FIRE_CACHE_HOURS = 1
HAZE_CACHE_HOURS = 1

HAZE_BATCH_SIZE = 30
MAX_HAZE_LOCATIONS = 1200

MAP_CENTER = [1.6, 109.8]
MAP_ZOOM = 5

COLORS = {
    "United Plantations Berhad": "#2EF0C9",
    "Bumitama Agri": "#A5FFF3",
    "IOI Corporation": "#75E2FF",
    "SD Guthrie": "#AEFF9A",
    "Sarawak Plantation Berhad": "#C8FFE4",
    "Hap Seng Plantations": "#F4FBFF",
}
