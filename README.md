# Oil Spill Detection & Drift Prediction using Satellite Imagery

An end-to-end deep learning and meteorological simulation system designed to identify marine oil spills from Synthetic Aperture Radar (SAR) satellite imagery, calculate slick area, and predict drift trajectories using ocean current and wind models.

---

## Key Features

*   **Dual-Polarization SAR Processing**: Standardizes dual-polarization Sentinel-1 SAR bands (VV and VH) to handle high-dynamic-range backscatter measurements.
*   **Deep Learning Pipeline**:
    *   **CNN Classifier**: A 6-layer custom Convolutional Neural Network that classifies SAR image patches into `Oil Spill`, `No Oil`, or `Lookalike` (natural slicks, wind shelters, etc.).
    *   **U-Net Segmenter**: An encoder-decoder network trained with a hybrid loss function (Binary Focal Loss + Intersection-over-Union) to generate precise pixel-level oil spill masks.
*   **Lagrangian Drift Simulation**: Simulates the transport and diffusion of spilled oil over a 48-hour horizon using OpenDrift's Lagrangian particle tracking engine, driven by real-time wind and ocean current data from Copernicus Marine Service.
*   **Interactive Web Dashboard**: React/Vite-based frontend that allows users to upload GeoTIFF SAR images, preview polarization bands, visualize oil masks, calculate spill area, and track simulated drift trajectories on an interactive map.

---

##  System Architecture

![System Architecture](/Codebase/Main/images/System_Architecture.png)

---

##  Sequence Diagram

![System Architecture](/Codebase/Main/images/Sequence_Diagram.png)

---

## 📂 Project Directory Structure

```filepath
Codebase/
├── README.md                 # Project documentation
├── requirements.txt          # Python package dependencies
├── env/                      # Python virtual environment
└── Main/
    ├── Sample_Images/        # Sample dual-pol SAR TIFF files for testing
    │   ├── Oil/              # Verified oil spills
    │   ├── No_Oil/           # Clear sea surfaces
    │   ├── Lookalike/        # Lookalike phenomena (e.g. low-wind areas)
    │   └── Image Conversion.ipynb  # Notebook to convert GeoTIFF to PNG formats (Not recommended)
    ├── backend/              # Flask backend & Machine Learning models
    │   ├── app.py            # Flask API server
    │   ├── BestModel.keras   # Trained CNN classification model
    │   ├── unet.h5           # Trained U-Net segmentation model
    │   ├── CNN_Training.ipynb     # Notebook for CNN training and validation
    │   ├── UNet_Segmentation.ipynb # Notebook for U-Net training and validation
    │   └── animations/       # Generated drift simulation output folder
    └── frontend/             # Frontend application
        └── dist/             # Compiled production build served by web hosts
```

---

## Model Configuration & Hyperparameters

### 1. SAR Preprocessing & Normalization
SAR backscatter values are in decibels ($dB$) and require clipping and scaling to stabilize neural network training:
*   **VV Band**: Clipped between $-35\text{ dB}$ and $5\text{ dB}$, normalized via:
    $$VV_{norm} = \frac{VV + 35}{40}$$
*   **VH Band**: Clipped between $-40\text{ dB}$ and $0\text{ dB}$, normalized via:
    $$VH_{norm} = \frac{VH + 40}{40}$$
*   Both channels are stacked to produce an input shape of `(512, 512, 2)`.

### 2. CNN Classifier
*   **Architecture**: 6-layer CNN with max pooling, dropout for regularization, and a dense output layer with sigmoid activation.
*   **Input**: `(512, 512, 2)` dual-channel SAR patch.
*   **Trained Weight File**: `BestModel.keras`

### 3. U-Net Segmenter
*   **Architecture**: Deep U-Net with skip connections to preserve high-resolution spatial details.
*   **Loss Function**: Weighted Focal Loss + IoU Loss to address severe class imbalance (spill pixels occupy a small fraction of the image).
*   **Trained Weight File**: `unet.h5`

---

## Setup and Installation

### 1. Prerequisites
*   Python 3.10 to 3.12
*   Node.js (optional, only for rebuilding the frontend source code)

### 2. Environment Setup
Clone the repository and set up a virtual environment:
```bash
# Navigate to the codebase
cd Codebase

# Create and activate virtual environment
python3 -m venv env
source env/bin/activate  # On Windows use: env\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Setup Copernicus Marine Credentials
To enable live Lagrangian drift predictions, configure your Copernicus Marine credentials in a `.env` file under `Main/backend/`:
```bash
# Create Main/backend/.env file
echo "COPERNICUS_USERNAME=your_username" > Main/backend/.env
echo "COPERNICUS_PASSWORD=your_password" >> Main/backend/.env
```
*Note: If credentials or dependencies (`opendrift`, `copernicusmarine`) are missing, the backend will run in classification/segmentation-only mode, and drift features will be disabled gracefully.*

---

## Running the Application

### 1. Launch the Backend Server
Navigate to the backend directory and run the Flask application:
```bash
cd Main/backend
python app.py
```
The backend API starts running on `http://localhost:5001`.

### 2. Run the Frontend Dashboard
Since the frontend is pre-built inside the `Main/frontend/dist` directory, you can serve it using a lightweight static file server:
```bash
# Serve static files on port 8000
npx serve -s ../frontend/dist -l 8000
```
Open `http://localhost:8000` in your web browser to access the dashboard.

---

## API Documentation

### 1. Run Oil Spill Inference
Runs classification and segmentation on a SAR GeoTIFF image.

*   **Endpoint**: `/api/predict`
*   **Method**: `POST`
*   **Content-Type**: `multipart/form-data`
*   **Parameters**:
    *   `image`: A `.tif` file containing dual-pol bands.
*   **Response (JSON)**:
    ```json
    {
      "has_oil": true,
      "confidence": 0.942,
      "oil_probability": 0.942,
      "area_km2": 4.12,
      "area_pixels": 16480,
      "bbox": [ [10.23, 56.45], [10.28, 56.49] ],
      "preview_image": "data:image/png;base64,...",
      "mask_image": "data:image/png;base64,...",
      "overlay_image": "data:image/png;base64,...",
      "drift_animation_url": "/api/animations/drift_animation_168694000.mp4",
      "drift_simulation_status": "generating"
    }
    ```

### 2. View SAR Image Channels
Generates band previews (VV/VH) without running inference.

*   **Endpoint**: `/api/preview`
*   **Method**: `POST`
*   **Content-Type**: `multipart/form-data`
*   **Parameters**:
    *   `image`: A `.tif` file.

### 3. Get Simulation Results
*   **Endpoint**: `/api/animations/<filename>/results`
*   **Method**: `GET`
*   **Response (JSON)**:
    ```json
    {
      "status": "completed",
      "drift_distance_km": 12.4,
      "drift_direction_degrees": 114.5,
      "drift_trajectory_coords": [ [10.23, 56.45], ... ],
      "drift_map_html": "<!DOCTYPE html><html>..."
    }
    ```

---

## Authors

*   **Paras Ningune**
*   **Soham Mane**
*   **Sakshi Patil**
*   **Siddhant Pote**
