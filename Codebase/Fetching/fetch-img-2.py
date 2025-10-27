import geemap
import ee
from dotenv import load_dotenv
import os
from PIL import Image

load_dotenv()
PROJECT_ID = os.getenv("PROJECT_ID")
print(PROJECT_ID)


ee.Authenticate()
ee.Initialize(project=PROJECT_ID)

# Area of interest
cities = [
    {"name": "New York", "bbox": ee.Geometry.Rectangle([-74.02, 40.70, -73.93, 40.79])},
    {"name": "Mumbai", "bbox": ee.Geometry.Rectangle([72.77, 18.89, 72.99, 19.30])},
    # Add 14 more...
]

years = {
    "2019": ['2019-06-01', '2019-09-30'],
    "2024": ['2024-06-01', '2024-09-30']
}

output_dir = "images"
os.makedirs(output_dir, exist_ok=True)

# Cloud-masked Sentinel-2 composite
def get_composite(bbox, start_date, end_date):
    img = (ee.ImageCollection("COPERNICUS/S2_SR")
           .filterBounds(bbox)
           .filterDate(start_date, end_date)
           .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 10))
           .median()
           .clip(bbox))
    return img

for city in cities:
    for year, (start, end) in years.items():
        img = get_composite(city["bbox"], start, end)
        vis_img = img.visualize(min=0, max=9000, bands=["B4", "B3", "B2"])

        tif_path = os.path.join(output_dir, f"{city['name']}_{year}.tif")
        png_path = tif_path.replace(".tif", ".png")

        geemap.ee_export_image(
            ee_object=vis_img,
            filename=tif_path,
            scale=10,
            region=city["bbox"],
            file_per_band=False
        )

        # Convert TIFF to PNG
        im = Image.open(tif_path)
        im.save(png_path)
        os.remove(tif_path)