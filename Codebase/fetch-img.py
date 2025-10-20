from dotenv import load_dotenv
import os

load_dotenv()
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")



from sentinelhub import SHConfig
config = SHConfig()
config.instance_id = ""
config.sh_client_id = CLIENT_ID
config.sh_client_secret = CLIENT_SECRET
config.save()
print(f"SentienalHub config -> {config}")


from sentinelhub import SentinelHubRequest, MimeType, CRS, BBox, DataCollection

cities = [
    {"name": "New York", "bbox": BBox([-74.010, 40.710, -73.950, 40.765], crs=CRS.WGS84), "hemisphere": "north"},
    {"name": "SA", "bbox": BBox([35.1100, 28.0500, 35.1700, 28.1000], crs=CRS.WGS84), "hemisphere": "north"},
    # {"name": "Dubai", "bbox": BBox([55.20, 25.05, 55.40, 25.30], crs=CRS.WGS84), "hemisphere": "north"},
    # {"name": "Abu Dhabi", "bbox": BBox([54.30, 24.30, 54.80, 24.60], crs=CRS.WGS84), "hemisphere": "north"},

    # {"name": "Gaza City", "bbox": BBox([34.42, 31.48, 34.52, 31.56], crs=CRS.WGS84), "hemisphere": "north"},
    # {"name": "Cairo", "bbox": BBox([31.18, 29.95, 31.36, 30.15], crs=CRS.WGS84), "hemisphere": "north"},
    # {"name": "Bangkok", "bbox": BBox([100.35, 13.50, 100.90, 13.95], crs=CRS.WGS84), "hemisphere": "north"},
    # {"name": "Bangalore", "bbox": BBox([77.45, 12.80, 77.75, 13.15], crs=CRS.WGS84), "hemisphere": "north"},

    # {"name": "Riyadh", "bbox": BBox([46.50, 24.40, 47.00, 25.00], crs=CRS.WGS84), "hemisphere": "north"},
    # {"name": "Gurgaon","bbox": BBox([76.9600, 28.3500, 77.1500, 28.5200], crs=CRS.WGS84),"hemisphere": "north"},
    # {"name": "Nairobi", "bbox": BBox([36.70, -1.45, 37.10, -1.10], crs=CRS.WGS84), "hemisphere": "south"},
    # {"name": "Kaunas","bbox": BBox([23.8100, 54.8500, 23.9900, 54.9600], crs=CRS.WGS84),"hemisphere": "north"},
    
    # {"name": "Hanoi","bbox": BBox([105.75, 20.95, 105.95, 21.10], crs=CRS.WGS84),"hemisphere": "north"},
    # {"name": "Addis Ababa","bbox": BBox([38.65, 8.85, 39.00, 9.15], crs=CRS.WGS84),"hemisphere": "north"},
    # {"name": "Doha","bbox": BBox([51.45, 25.15, 51.65, 25.45], crs=CRS.WGS84),"hemisphere": "north"},
    # {"name": "Belgrade","bbox": BBox([20.30, 44.65, 20.60, 44.90], crs=CRS.WGS84),"hemisphere": "north"},
]

evalscript_true_color = """
    //VERSION=3

    function setup() {
        return {
            input: [{
                bands: ["B02", "B03", "B04"]
            }],
            output: {
                bands: 3
            }
        };
    }

    function evaluatePixel(sample) {
        return [sample.B04, sample.B03, sample.B02];
    }
"""


def get_season_dates(year, hemisphere):
    
    if (hemisphere == "north"):
        return (f"{year}-02-01", f"{year}-04-30")  
    else:
        return (f"{year}-03-01", f"{year+1}-04-28")

def create_request(city, year):
    summer_start, summer_end = get_season_dates(year, city["hemisphere"])

    return SentinelHubRequest(
        evalscript=evalscript_true_color,
        input_data=[
            SentinelHubRequest.input_data(
                data_collection=DataCollection.SENTINEL2_L2A,
                time_interval=(summer_start, summer_end),
                maxcc=0.01,
                mosaicking_order="leastCC"
            )
        ],
        responses=[
            SentinelHubRequest.output_response("default", MimeType.PNG)
        ],
        bbox=city["bbox"],
        #size=(512, 512),
        resolution=(10,10),
        config=config
    )

# Fetch and store all images
images_2018, images_2024 = [], []

for city in cities:
    request_14 = create_request(city, 2018)
    request_24 = create_request(city, 2024)

    image_14 = request_14.get_data()[0]
    image_24 = request_24.get_data()[0]

    images_2018.append(image_14)
    images_2024.append(image_24)



import os
import cv2
import numpy as np
from skimage import exposure

output_folder = "city_images"
os.makedirs(output_folder, exist_ok=True)

for i in range(len(cities)):
    img2018 = images_2018[i]
    img2024 = images_2024[i]

    # Brighten images
    bright2018 = exposure.adjust_gamma(img2018, gamma=0.8)
    bright2024 = exposure.adjust_gamma(img2024, gamma=0.8)


    # Save using cv2 (note: BGR format)
    city_name = cities[i]['name'].replace(" ", "_")
    path2018 = os.path.join(output_folder, f"{city_name}_2018.png")
    path2024 = os.path.join(output_folder, f"{city_name}_2024.png")

    cv2.imwrite(path2018, cv2.cvtColor(bright2018, cv2.COLOR_RGB2BGR))
    cv2.imwrite(path2024, cv2.cvtColor(bright2024, cv2.COLOR_RGB2BGR))