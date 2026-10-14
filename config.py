from pathlib import Path
import os
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent

load_dotenv(BASE / ".env")

MAP_KEY = os.getenv("NASA_MAP_KEY")

if not MAP_KEY:
    raise ValueError("NASA_MAP_KEY is missing")

GPKG = BASE / "data" / "all_company_geometries.gpkg"
OUTPUT = BASE / "output" / "estate_fire_map.html"

AREA = "94,-12,125,8"
FIRE_DAYS = 3

MAP_CENTER = [1.6, 109.8]
MAP_ZOOM = 5

COLORS = {
    "United Plantations Berhad": "#009E73",
    "Bumitama Agri": "#E69F00",
    "IOI Corporation": "#0072B2",
    "SD Guthrie": "#7B61A8",
    "Sarawak Plantation Berhad": "#E15759",
    "Hap Seng Plantations": "#56B4E9",
}