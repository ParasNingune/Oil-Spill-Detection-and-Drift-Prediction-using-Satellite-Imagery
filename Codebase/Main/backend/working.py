from flask import Flask, request, jsonify, send_file, make_response
from flask_cors import CORS
import numpy as np
import tensorflow as tf
import rasterio
import io
import base64
from PIL import Image
import cv2
import os
import sys
import traceback
from datetime import datetime, timedelta
from rasterio.transform import xy
from scipy.spatial import ConvexHull, QhullError
import threading
import time

# Import the drift prediction module
try:
    from drift_prediction import (
        run_drift_simulation, 
        extract_spill_coordinates,
        setup_drift_environment,
        safe_hull,
        create_drift_map_html,
        create_trajectory_plot_image,
        generate_drift_animation,
        cleanup_drift_files,
        get_drift_module_status,
        generate_synthetic_data_for_bbox,
        DRIFT_SIMULATION_DURATION_HOURS,
        NUM_DRIFT_PARTICLES
    )
    DRIFT_MODULE_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Drift prediction module not available: {e}")
    DRIFT_MODULE_AVAILABLE = False
    generate_synthetic_data_for_bbox = None

# Configure Matplotlib backend IMMEDIATELY (before any plotting)
# This MUST be done before importing matplotlib.pyplot
# Required to prevent GUI threading issues on macOS
try:
    import matplotlib
    matplotlib.use('Agg')  # Use Anti-Grain Geometry backend (non-interactive, thread-safe)
except ImportError:
    pass

# Load environment variables from .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Copernicus Marine API no longer needed - system uses synthetic data generation

try:
    from opendrift.models.oceandrift import OceanDrift
    from opendrift.readers.reader_netCDF_CF_generic import Reader
    OPENDRIFT_AVAILABLE = True
except ImportError:
    OPENDRIFT_AVAILABLE = False
    print("Warning: opendrift not installed. Drift simulation will not work.")
    print("Install with: pip install opendrift")

try:
    import folium
    FOLIUM_AVAILABLE = True
except ImportError:
    FOLIUM_AVAILABLE = False
    print("Warning: folium not installed. Interactive maps will not work.")
    print("Install with: pip install folium")

app = Flask(__name__)
CORS(app)

# Create animations directory at startup
if not os.path.exists('animations'):
    os.makedirs('animations')
    print("Created animations directory")

# ============================================================================
MODEL_PATH = "BestModel.keras"  # Model file in the same directory as app.py
UNET_MODEL_PATH = "unet.h5"  # U-Net mask model in same folder

try:
    model = tf.keras.models.load_model(MODEL_PATH)
    print(f"Model loaded successfully from {MODEL_PATH}")
except Exception as e:
    print(f"Warning: Could not load model from {MODEL_PATH}")
    print(f"Error: {e}")
    print(f"Make sure BestModel.keras is in the backend folder")
    model = None

try:
    unet_model = tf.keras.models.load_model(UNET_MODEL_PATH, compile=False)
    print(f"U-Net loaded successfully from {UNET_MODEL_PATH}")
except Exception as e:
    print(f"Warning: Could not load U-Net model from {UNET_MODEL_PATH}")
    print(f"Error: {e}")
    print("Mask generation will fail until unet_epoch_009.h5 is available")
    unet_model = None

# Model parameters
IMG_SIZE = (512, 512)
CLASSIFICATION_THRESHOLD = 0.4    # Adjust based on your model's performance

# ============================================================================
# DRIFT SIMULATION CONFIGURATION
# ============================================================================
# Note: Drift simulation uses synthetic data generation exclusively.
# If local data files (currents.nc, wind.nc) are not found, the system
# automatically generates synthetic oceanographic data for the specific region.
ENABLE_DRIFT_SIMULATION = OPENDRIFT_AVAILABLE and DRIFT_MODULE_AVAILABLE# Optional (no longer required)
DRIFT_SIMULATION_DURATION_HOURS = 48  # How long to simulate drift
NUM_DRIFT_PARTICLES = 1000  # Number of particles to seed
DRIFT_TIME_STEP = 900  # Time step in seconds (15 minutes)

# Global dictionary to store drift results keyed by animation filename
drift_results_cache = {}

# ============================================================================


def detect_image_format(file_bytes):
    """
    Detect image format and validate TIFF-only input.
    Returns: format string ('tiff')
    """
    header = file_bytes[:16]

    # Quick signature checks (most reliable and fast)
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if header[:3] == b'\xff\xd8\xff':
        return 'jpeg'
    if header.startswith(b'II*\x00') or header.startswith(b'MM\x00*'):
        return 'tiff'

    # PIL format detection
    try:
        img = Image.open(io.BytesIO(file_bytes))
        fmt = (img.format or '').lower()
        if fmt in ['png', 'jpeg', 'jpg', 'tif', 'tiff']:
            if fmt in ['jpg', 'jpeg']:
                return 'jpeg'
            if fmt in ['tif', 'tiff']:
                return 'tiff'
            return 'png'
    except Exception:
        pass

    # Rasterio fallback (check driver, not just open success)
    try:
        with rasterio.open(io.BytesIO(file_bytes)) as src:
            driver = (src.driver or '').lower()
            if 'tiff' in driver or driver == 'gtiff' or driver == 'cog':
                return 'tiff'
            if driver == 'png':
                return 'png'
            if 'jpeg' in driver or driver == 'jpg':
                return 'jpeg'
    except Exception:
        pass

    raise ValueError("Unsupported image format. Please use TIFF.")


def preprocess_sar_image(file_bytes):
    """
    Preprocess the uploaded SAR TIFF image
    Expects 2-channel image (VV and VH)
    """
    try:
        # Read the TIFF file
        with rasterio.open(io.BytesIO(file_bytes)) as src:
            vv = src.read(1).astype(np.float32)
            vh = src.read(2).astype(np.float32)
            
            # Store metadata for area calculation
            transform = src.transform
            crs = src.crs
        
        # Normalize using the same approach as training
        vv = np.clip(vv, -35, 5)
        vh = np.clip(vh, -40, 0)
        
        vv = (vv + 35) / 40
        vh = (vh + 40) / 40
        
        # Stack channels
        img = np.stack([vv, vh], axis=-1)
        
        # Resize to model input size
        img = tf.image.resize(img, IMG_SIZE, method="bilinear").numpy()
        
        return img, transform, crs
    
    except Exception as e:
        raise ValueError(f"Error preprocessing TIFF image: {str(e)}")


def create_visualization_image(file_bytes):
    """
    Create a visualization of the TIFF image by combining bands (30:70 ratio)
    """
    try:
        with rasterio.open(io.BytesIO(file_bytes)) as src:
            band1 = src.read(1).astype(np.float32)  # Band 1
            band2 = src.read(2).astype(np.float32)  # Band 2

        # Normalize both bands using min-max normalization
        band1_norm = (band1 - np.nanmin(band1)) / (np.nanmax(band1) - np.nanmin(band1))
        band2_norm = (band2 - np.nanmin(band2)) / (np.nanmax(band2) - np.nanmin(band2))

        # Combine 30% Band1 + 70% Band2
        combined = 0.3 * band1_norm + 0.7 * band2_norm
        
        # Convert to 8-bit for display
        combined_8bit = (combined * 255).astype(np.uint8)
        
        # Create RGB image (grayscale)
        rgb_image = np.stack([combined_8bit] * 3, axis=-1)
        
        # Convert to PIL Image
        img = Image.fromarray(rgb_image)
        
        # Resize for faster transmission (optional)
        max_size = 512
        if img.width > max_size or img.height > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        
        # Save to bytes
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        # Encode to base64
        img_base64 = base64.b64encode(buffer.read()).decode('utf-8')
        
        return img_base64
    
    except Exception as e:
        print(f"Error creating visualization: {str(e)}")
        return None


def calculate_pixel_area_km2(transform):
    """
    Calculate the area of a single pixel in km²
    """
    res_x, res_y = abs(transform[0]), abs(transform[4])
    meters_per_degree = 111_320
    
    # Convert to km²
    area_km2 = (res_x * meters_per_degree * res_y * meters_per_degree) / 1e6
    return area_km2


def extract_image_bbox_coords(file_bytes):
    """
    Extract image bounding box coordinates in WGS84 (lat/lon) from a TIFF file's georeference.
    Returns a dict with left, bottom, right, top in EPSG:4326.
    Raises ValueError if CRS or bounds are missing or transform fails.
    """
    try:
        with rasterio.open(io.BytesIO(file_bytes)) as src:
            bounds = src.bounds
            crs = src.crs

            if bounds is None:
                raise ValueError("Image has no bounds")
            if crs is None:
                raise ValueError("Image has no CRS (coordinate reference system)")

            # Transform bounds to WGS84 (EPSG:4326)
            try:
                from rasterio.warp import transform_bounds
                wgs_bounds = transform_bounds(crs, 'EPSG:4326', bounds.left, bounds.bottom, bounds.right, bounds.top, densify_pts=21)
            except Exception as e:
                raise ValueError(f"Failed to transform bounds to EPSG:4326: {e}")

            return {
                'left': float(wgs_bounds[0]),
                'bottom': float(wgs_bounds[1]),
                'right': float(wgs_bounds[2]),
                'top': float(wgs_bounds[3]),
                'crs': str(crs)
            }

    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Error extracting bbox coords: {e}")


def generate_oil_mask_from_file(file_bytes):
    """
    Generate oil spill mask using U-Net inference on TIFF data.
    """
    try:
        if unet_model is None:
            print("Error generating oil mask: U-Net model is not loaded")
            return None

        # Read original TIFF bands
        with rasterio.open(io.BytesIO(file_bytes)) as src:
            vv = src.read(1).astype(np.float32)
            vh = src.read(2).astype(np.float32)

        original_h, original_w = vv.shape

        # Normalize exactly like training preprocessing
        vv = np.clip(vv, -35, 5)
        vh = np.clip(vh, -40, 0)
        vv = (vv + 35) / 40
        vh = (vh + 40) / 40

        # Stack and resize to U-Net input size
        img = np.stack([vv, vh], axis=-1)
        img = tf.image.resize(img, IMG_SIZE, method="bilinear").numpy()
        img_batch = np.expand_dims(img, axis=0)

        # Predict mask with U-Net
        pred = unet_model.predict(img_batch, verbose=0)[0]
        pred_mask = pred[..., 0] if pred.ndim == 3 else pred
        oil_mask = (pred_mask > 0.5).astype(np.uint8)

        # Resize predicted mask back to original TIFF size for area/overlay consistency
        if oil_mask.shape != (original_h, original_w):
            oil_mask = cv2.resize(oil_mask, (original_w, original_h), interpolation=cv2.INTER_NEAREST)

        # Apply morphological operations to clean up the mask
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        oil_mask = cv2.morphologyEx(oil_mask, cv2.MORPH_OPEN, kernel)
        oil_mask = cv2.morphologyEx(oil_mask, cv2.MORPH_CLOSE, kernel)
        
        return oil_mask
    
    except Exception as e:
        print(f"Error generating oil mask: {str(e)}")
        return None


def calculate_oil_area(mask, pixel_area_km2):
    """
    Calculate the total area of oil spill in km²
    """
    num_oil_pixels = np.sum(mask > 0)
    total_area_km2 = num_oil_pixels * pixel_area_km2
    return total_area_km2



def mask_to_base64(mask):
    """
    Convert binary mask to base64 encoded PNG image with colored boundaries
    """
    # Convert mask to RGB for visualization
    mask_rgb = np.stack([mask * 255] * 3, axis=-1).astype(np.uint8)
    
    # Add color overlay (red for oil)
    mask_rgb[mask > 0] = [220, 38, 38]  # Red color for oil regions
    
    # Find contours to draw boundaries
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Draw thick colored boundaries around oil spills
    cv2.drawContours(mask_rgb, contours, -1, (255, 255, 0), 3)  # Yellow boundary
    
    # Convert to PIL Image
    img = Image.fromarray(mask_rgb)
    
    # Save to bytes
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    
    # Encode to base64
    img_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    
    return img_base64


def create_overlay_visualization(file_bytes, mask):
    """
    Create a visualization with the TIFF image and oil mask overlay with boundaries.
    """
    try:
        with rasterio.open(io.BytesIO(file_bytes)) as src:
            vv = src.read(1).astype(np.float32)
            vh = src.read(2).astype(np.float32)

        # Apply the same normalization
        vv_clipped = np.clip(vv, -35, 5)
        vv_norm = (vv_clipped + 35) / 40

        vh_clipped = np.clip(vh, -40, 0)
        vh_norm = (vh_clipped + 40) / 40

        # Combine 30% VV + 70% VH
        combined = 0.3 * vv_norm + 0.7 * vh_norm
        combined_8bit = (combined * 255).astype(np.uint8)
        
        # Create RGB image
        rgb_image = np.stack([combined_8bit] * 3, axis=-1)
        
        # Resize mask to match original image size if needed
        if mask.shape != combined_8bit.shape:
            mask_resized = cv2.resize(mask.astype(np.uint8), (combined_8bit.shape[1], combined_8bit.shape[0]), 
                                     interpolation=cv2.INTER_NEAREST)
        else:
            mask_resized = mask.astype(np.uint8)
        
        # Apply red overlay with transparency
        oil_overlay = rgb_image.copy()
        oil_overlay[mask_resized > 0] = [220, 38, 38]  # Red color
        
        # Blend with original image
        alpha = 0.4  # Transparency
        blended = cv2.addWeighted(rgb_image, 1 - alpha, oil_overlay, alpha, 0)
        
        # Find and draw contours
        contours, _ = cv2.findContours(mask_resized, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(blended, contours, -1, (255, 255, 0), 4)  # Yellow boundary
        
        # Convert to PIL Image
        img = Image.fromarray(blended)
        
        # Resize for faster transmission
        max_size = 800
        if img.width > max_size or img.height > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        
        # Save to bytes
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        # Encode to base64
        img_base64 = base64.b64encode(buffer.read()).decode('utf-8')
        
        return img_base64
    
    except Exception as e:
        print(f"Error creating overlay visualization: {str(e)}")

    
def run_drift_simulation_background(file_bytes, mask, animation_filename):
    """
    Run complete drift simulation in background thread (non-blocking API response)
    
    Args:
        file_bytes: TIFF file as bytes
        mask: Binary oil mask
        animation_filename: Filename for the animation output
    """
    try:
        print(f"\n[DRIFT BACKGROUND THREAD] Starting drift simulation workflow...")
        print(f"[DRIFT BACKGROUND THREAD] Animation filename: {animation_filename}")
        
        # Get current date for simulation
        today = datetime.now()
        start_date = today.strftime('%Y-%m-%d')
        end_date = (today + timedelta(days=1)).strftime('%Y-%m-%d')
        
        print(f"[DRIFT BACKGROUND THREAD] Simulation period: {start_date} to {end_date}")
        
        # Step 1: Extract oil coordinates
        print(f"[DRIFT BACKGROUND THREAD] Step 1: Extracting spill coordinates...")
        spill_pixels = extract_spill_coordinates(file_bytes, mask)
        if spill_pixels is None or len(spill_pixels) == 0:
            print("[DRIFT BACKGROUND THREAD] ✗ No oil pixels found")
            drift_results_cache[animation_filename] = {'error': 'No oil pixels found', 'status': 'failed'}
            return
        
        print(f"[DRIFT BACKGROUND THREAD] Found {len(spill_pixels)} spill pixels")
        
        # Step 2: Set up environment
        print(f"[DRIFT BACKGROUND THREAD] Step 2: Setting up drift environment...")
        o = setup_drift_environment(spill_pixels, start_date, end_date)
        if o is None:
            print("[DRIFT BACKGROUND THREAD] Failed to set up environment")
            drift_results_cache[animation_filename] = {'error': 'Failed to set up environment', 'status': 'failed'}
            return
        
        print(f"[DRIFT BACKGROUND THREAD] Environment set up successfully")
        
        # Step 3: Run simulation
        print("[DRIFT BACKGROUND THREAD] Step 3: Running drift simulation (this may take several minutes)...")
        if len(spill_pixels) > NUM_DRIFT_PARTICLES:
            indices = np.random.choice(len(spill_pixels), NUM_DRIFT_PARTICLES, replace=False)
            sampled = spill_pixels[indices]
        else:
            sampled = spill_pixels
        
        lons = sampled[:, 0]
        lats = sampled[:, 1]
        
        print(f"[DRIFT BACKGROUND THREAD] Seeding {len(lons)} particles...")
        
        start_time_dt = datetime.strptime(start_date, '%Y-%m-%d')
        o.seed_elements(lon=lons, lat=lats, time=start_time_dt)
        o.run(duration=timedelta(hours=DRIFT_SIMULATION_DURATION_HOURS), time_step=DRIFT_TIME_STEP)
        
        print("[DRIFT BACKGROUND THREAD] ✓ Drift simulation completed")
        
        # Step 4: Extract results
        print(f"[DRIFT BACKGROUND THREAD] Step 4: Extracting drift results...")
        lon = o.result.lon.values
        lat = o.result.lat.values
        
        lon_start = lon[0]
        lat_start = lat[0]
        lon_end = lon[-1]
        lat_end = lat[-1]
        
        points_start = np.column_stack((lon_start, lat_start))
        hull_points_start = safe_hull(points_start)
        
        points_end = np.column_stack((lon_end, lat_end))
        hull_points_end = safe_hull(points_end)
        
        cx_start = np.mean(lon_start)
        cy_start = np.mean(lat_start)
        cx_end = np.mean(lon_end)
        cy_end = np.mean(lat_end)
        
        drift_distance = np.sqrt((cx_end - cx_start)**2 + (cy_end - cy_start)**2) * 111.32
        drift_direction = np.degrees(np.arctan2(cy_end - cy_start, cx_end - cx_start))
        drift_direction = (drift_direction + 360) % 360
        
        print(f"[DRIFT BACKGROUND THREAD] Drift distance: {drift_distance:.2f} km")
        print(f"[DRIFT BACKGROUND THREAD] Drift direction: {drift_direction:.1f}°")
        
        # Step 5: Create interactive map
        print(f"[DRIFT BACKGROUND THREAD] Step 5: Creating drift map...")
        drift_results = {
            'initial_center': {'lon': float(cx_start), 'lat': float(cy_start)},
            'final_center': {'lon': float(cx_end), 'lat': float(cy_end)},
            'drift_distance_km': float(np.round(drift_distance, 2)),
            'drift_direction_degrees': float(np.round(drift_direction, 1)),
            'initial_hull': hull_points_start.tolist() if hull_points_start is not None else None,
            'final_hull': hull_points_end.tolist() if hull_points_end is not None else None,
            'opendrift_object': o
        }
        
        print(f"[DRIFT BACKGROUND THREAD] Calling create_drift_map_html...") 
        map_html = create_drift_map_html(drift_results)
        if map_html:
            print(f"[DRIFT BACKGROUND THREAD] ✓ Drift map created ({len(map_html)} bytes)")
        else:
            print("[DRIFT BACKGROUND THREADMap HTML is None")
        
        # Store drift results in cache for frontend retrieval
        cache_key = animation_filename
        drift_results_cache[cache_key] = {
            'drift_distance_km': round(drift_results['drift_distance_km'], 3),
            'drift_direction_degrees': round(drift_results['drift_direction_degrees'], 3),
            'drift_map_html': map_html,
            'initial_center': drift_results['initial_center'],
            'final_center': drift_results['final_center'],
            'status': 'complete'
        }
        print(f"[DRIFT BACKGROUND THREAD] Stored results in cache: {cache_key}")
        print(f"[DRIFT BACKGROUND THREAD]   - Direction: {drift_results_cache[cache_key]['drift_direction_degrees']}°")
        print(f"[DRIFT BACKGROUND THREAD]   - Distance: {drift_results_cache[cache_key]['drift_distance_km']} km")
        print(f"[DRIFT BACKGROUND THREAD]   - Map: {bool(map_html)}")
        
        # Step 6: Generate animation in separate background thread
        print(f"[DRIFT BACKGROUND THREAD] Step 6: Starting animation generation: {animation_filename}")
        drift_obj = drift_results.get('opendrift_object')
        if drift_obj:
            animation_thread = threading.Thread(
                target=generate_animation_background,
                args=(drift_obj, animation_filename),
                daemon=True
            )
            animation_thread.start()
        
        # Cleanup temporary files
        print(f"[DRIFT BACKGROUND THREAD] Cleaning up temporary files...")
        cleanup_drift_files()
        print("[DRIFT BACKGROUND THREAD] Drift simulation workflow completed!")
        
    except Exception as e:
        print(f"[DRIFT BACKGROUND THREAD] Error: {str(e)}")
        traceback.print_exc()
        try:
            drift_results_cache[animation_filename] = {'error': str(e), 'status': 'failed'}
        except:
            pass
        try:
            cleanup_drift_files()
        except:
            pass


# ============================================================================

def generate_animation_background(drift_obj, animation_filename):
    """
    Generate drift animation MP4 in background thread
    
    Args:
        drift_obj: OpenDrift object with simulation results
        animation_filename: Output filename for the animation (just filename, not full path)
    """
    try:
        print(f"\n[Animation Generation] Starting for {animation_filename}")
        print(f"[Animation Generation] Thread is daemon: {threading.current_thread().daemon}")
        
        if drift_obj is None:
            print(f"[Animation Generation] ✗ drift_obj is None - cannot generate animation")
            return
        
        # Generate animation using the drift_prediction module
        # NOTE: generate_drift_animation handles the 'animations/' path internally
        print(f"[Animation Generation] Calling generate_drift_animation(drift_obj, {animation_filename})")
        output_path = generate_drift_animation(drift_obj, animation_filename)
        
        if output_path and os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            print(f"[Animation Generation] Animation complete: {animation_filename}")
            print(f"[Animation Generation] File size: {file_size} bytes ({file_size/(1024*1024):.2f} MB)")
            print(f"[Animation Generation] Location: {output_path}")
            sys.stdout.flush()
        else:
            expected_path = os.path.join(os.path.abspath('animations'), animation_filename)
            print(f"[Animation Generation] Animation generation failed")
            print(f"[Animation Generation] File not found at: {expected_path}")
            sys.stdout.flush()
    
    except Exception as e:
        print(f"[Animation Generation] Error: {str(e)}")
        print(f"[Animation Generation] Error type: {type(e).__name__}")
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()


# ============================================================================

@app.route('/api/predict', methods=['POST'])
def predict():
    """
    Main prediction endpoint with drift simulation integration
    Expects: multipart/form-data with 'image' field containing TIFF
    Returns: JSON with classification result, area, drift information, and maps
    """
    import time
    start_time = time.time()
    
    try:
        # Check if model is loaded
        if model is None:
            return jsonify({
                'error': 'Model not loaded. Please check the MODEL_PATH in app.py'
            }), 500
        
        # Check if file is present
        if 'image' not in request.files:
            print(f"No 'image' field in request. Available fields: {list(request.files.keys())}")
            return jsonify({'error': 'No image file provided'}), 400
        
        file = request.files['image']
        
        if file.filename == '':
            print("Empty filename")
            return jsonify({'error': 'No file selected'}), 400
        
        print(f"Received file: {file.filename}")
        
        # Read file bytes
        file_bytes = file.read()
        
        # Detect image format
        try:
            image_format = detect_image_format(file_bytes)
            print(f"Detected image format: {image_format}")
        except Exception as e:
            print(f"Image format detection failed: {e}")
            return jsonify({'error': str(e)}), 400

        if image_format != 'tiff':
            return jsonify({'error': 'Only TIFF images are supported.'}), 400

        # Extract bounding box coordinates
        bbox = None
        try:
            bbox = extract_image_bbox_coords(file_bytes)
        except Exception as e:
            print(f"Bounding box extraction failed: {e}")
            return jsonify({'error': str(e)}), 400

        # Create visualization image
        viz_image = create_visualization_image(file_bytes)
        
        # Preprocess TIFF image
        img, transform, crs = preprocess_sar_image(file_bytes)
        pixel_area_km2 = calculate_pixel_area_km2(transform) if transform else None
        
        # Prepare for model prediction
        img_batch = np.expand_dims(img, axis=0)
        
        # ============================================================================
        # MODEL PREDICTION - Classification
        # ============================================================================
        prediction = model.predict(img_batch, verbose=0)
        oil_probability = float(prediction[0][0])
        has_oil = oil_probability > CLASSIFICATION_THRESHOLD
        confidence = oil_probability if has_oil else (1.0 - oil_probability)
        # ============================================================================
        
        response = {
            'has_oil': bool(has_oil),
            'confidence': float(confidence),
            'prediction_value': float(oil_probability),
            'oil_probability': float(oil_probability),
            'bbox': bbox,
            'area_km2': 0.0,
            'area_pixels': 0,
            'drift_prediction': {
                'direction': 0.0,
                'distance_km': 0.0
            },
            'preview_image': viz_image,
            'mask_image': None,
            'overlay_image': None,
            'drift_map_html': None,
            'drift_animation_url': None,
            'drift_animation_path': None,
            'drift_simulation_status': 'disabled'
        }
        
        # If oil is detected, calculate area and run drift simulation
        if has_oil:
            print("\n" + "="*60)
            print("OIL DETECTED - Processing...")
            print("="*60)
            
            # Generate oil mask from original file
            mask = generate_oil_mask_from_file(file_bytes)
            
            if mask is None:
                return jsonify({'error': 'Failed to generate oil mask'}), 500
            
            # Calculate oil spill area
            oil_area = calculate_oil_area(mask, pixel_area_km2)
            num_oil_pixels = int(np.sum(mask > 0))
            response['area_km2'] = round(float(oil_area), 2)
            response['area_pixels'] = num_oil_pixels
            
            # Convert mask to base64 for visualization
            mask_image = mask_to_base64(mask)
            response['mask_image'] = mask_image
            
            # Create overlay visualization
            overlay_image = create_overlay_visualization(file_bytes, mask)
            if overlay_image:
                response['overlay_image'] = overlay_image
            
            # Set drift animation status to generating if drift is enabled
            if ENABLE_DRIFT_SIMULATION:
                # Create a placeholder animation URL so the section renders
                timestamp = int(time.time() * 1000)
                animation_filename = f'drift_animation_{timestamp}.mp4'
                response['drift_animation_url'] = f'/api/animations/{animation_filename}'
                response['drift_animation_status'] = 'generating'
                response['drift_animation_filename'] = animation_filename
        
        # Calculate processing time for main prediction
        processing_time_ms = (time.time() - start_time) * 1000
        response['processing_time_ms'] = round(processing_time_ms, 2)
        
        # ================================================================
        # RETURN RESPONSE IMMEDIATELY (don't wait for drift simulation)
        # ================================================================
        print(f"\nReturning prediction response in {processing_time_ms:.0f}ms")
        
        # If oil detected, start drift simulation in background thread
        if has_oil and ENABLE_DRIFT_SIMULATION:
            print(f"\n[BACKGROUND] Starting drift simulation in background thread...")
            print(f"[BACKGROUND] Animation will be saved as: {response.get('drift_animation_filename', 'unknown')}")
            # Extract animation filename from the URL we created
            animation_filename = response['drift_animation_url'].split('/')[-1]
            drift_thread = threading.Thread(
                target=run_drift_simulation_background,
                args=(file_bytes, mask, animation_filename),
                daemon=True
            )
            drift_thread.start()
            print(f"[BACKGROUND] Drift thread started (daemon mode - runs independently)")
        
        return jsonify(response), 200
    
    except Exception as e:
        print(f"Error during prediction: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/preview', methods=['POST'])
def preview():
    """
    Preview endpoint - generates visualization of the image
    Expects: multipart/form-data with 'image' field containing TIFF
    Returns: JSON with base64 encoded preview image
    """
    try:
        # Check if file is present
        if 'image' not in request.files:
            print(f"No 'image' field in request. Available fields: {list(request.files.keys())}")
            return jsonify({'error': 'No image file provided'}), 400
        
        file = request.files['image']
        
        if file.filename == '':
            print("Empty filename")
            return jsonify({'error': 'No file selected'}), 400
        
        print(f"Generating preview for: {file.filename}")
        
        # Read file bytes
        file_bytes = file.read()
        
        # Detect image format
        try:
            image_format = detect_image_format(file_bytes)
        except Exception as e:
            return jsonify({'error': str(e)}), 400

        if image_format != 'tiff':
            return jsonify({'error': 'Only TIFF images are supported.'}), 400
        
        # Create visualization image
        viz_image = create_visualization_image(file_bytes)
        
        if viz_image is None:
            return jsonify({'error': 'Failed to generate preview'}), 500
        
        return jsonify({
            'preview_image': viz_image,
            'filename': file.filename
        }), 200
    
    except Exception as e:
        print(f"Error generating preview: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """
    Health check endpoint with drift simulation status
    Reports if synthetic data generation is available (no API required)
    """
    status = {
        'status': 'healthy',
        'model_loaded': model is not None,
        'unet_model_loaded': unet_model is not None,
        'drift_simulation_enabled': ENABLE_DRIFT_SIMULATION,
        'drift_module_available': DRIFT_MODULE_AVAILABLE,
        'opendrift_available': OPENDRIFT_AVAILABLE,
        'folium_available': FOLIUM_AVAILABLE,
        'synthetic_data_generation': 'enabled' if generate_synthetic_data_for_bbox else 'disabled'
    }
    
    if DRIFT_MODULE_AVAILABLE:
        try:
            drift_status = get_drift_module_status()
            status['drift_module_status'] = drift_status
        except:
            status['drift_module_status'] = 'available but could not retrieve details'
    
    return jsonify(status), 200


@app.route('/api/animations/<filename>', methods=['GET', 'HEAD', 'OPTIONS'])
def serve_animation(filename):
    """
    Serve drift animation video files with streaming support
    Expects: GET /api/animations/<filename>
    Returns: MP4 video file with proper CORS and streaming headers
    """
    try:
        print(f"\n[Serve Animation] Request for: {filename}")
        
        # Handle OPTIONS preflight requests
        if request.method == 'OPTIONS':
            print(f"[Serve Animation] Handling CORS preflight for {filename}")
            response = make_response('', 204)
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Range'
            return response
        
        # Validate filename to prevent directory traversal
        if '..' in filename or '/' in filename or '\\' in filename:
            print(f"[Serve Animation] ✗ Invalid filename: {filename}")
            return jsonify({'error': 'Invalid filename'}), 400
        
        animations_dir = os.path.abspath('animations')
        file_path = os.path.join(animations_dir, filename)
        
        # Ensure the file is within the animations directory
        if not os.path.abspath(file_path).startswith(animations_dir):
            print(f"[Serve Animation] ✗ File outside animations dir: {file_path}")
            return jsonify({'error': 'Invalid file path'}), 400
        
        if not os.path.exists(file_path):
            print(f"[Serve Animation] ✗ Animation file not found: {file_path}")
            return jsonify({'error': f'Animation not found: {filename}'}), 404
        
        # Check file size and validity
        file_size = os.path.getsize(file_path)
        print(f"[Serve Animation] ✓ File found: {file_size} bytes")
        
        # Check if file is readable
        if not os.access(file_path, os.R_OK):
            print(f"[Serve Animation] ✗ File not readable: {file_path}")
            return jsonify({'error': 'File not readable'}), 403
        
        print(f"[Serve Animation] ✓ Serving {filename} ({file_size} bytes)")
        
        # Serve the video file with streaming support
        response = send_file(
            file_path,
            mimetype='video/mp4',
            as_attachment=False  # Display in browser
        )
        
        # Add comprehensive headers for proper streaming
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Range'
        response.headers['Accept-Ranges'] = 'bytes'
        response.headers['Content-Length'] = file_size
        response.headers['Content-Type'] = 'video/mp4'
        response.headers['Cache-Control'] = 'public, max-age=3600'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Animation-File'] = filename
        
        print(f"[Serve Animation] ✓ Response complete with headers")
        return response
    
    except Exception as e:
        print(f"[Serve Animation] ✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/animations/watch/<filename>', methods=['GET', 'OPTIONS'])
def watch_animation(filename):
    """
    Serve an HTML page with a video player for the animation
    Uses the video_player.html template and passes the filename as a query parameter
    
    Expects: GET /api/animations/watch/<filename>
    Returns: HTML page with embedded video player
    """
    try:
        print(f"\n[Watch Animation] Request for: {filename}")
        
        # Validate filename to prevent directory traversal
        if '..' in filename or '/' in filename or '\\' in filename:
            print(f"[Watch Animation] ✗ Invalid filename: {filename}")
            return jsonify({'error': 'Invalid filename'}), 400
        
        # Check if video file exists
        animations_dir = os.path.abspath('animations')
        file_path = os.path.join(animations_dir, filename)
        
        if not os.path.abspath(file_path).startswith(animations_dir):
            print(f"[Watch Animation] ✗ File outside animations dir: {file_path}")
            return jsonify({'error': 'Invalid file path'}), 400
        
        if not os.path.exists(file_path):
            print(f"[Watch Animation] ✗ Animation file not found: {file_path}")
            return jsonify({'error': f'Animation not found: {filename}'}), 404
        
        # Read the video player HTML template
        video_player_path = 'video_player.html'
        if not os.path.exists(video_player_path):
            print(f"[Watch Animation] ✗ Video player template not found: {video_player_path}")
            return '''
            <html>
                <head><title>Error</title></head>
                <body><h1>Video Player Not Found</h1><p>The video player template is missing.</p></body>
            </html>
            ''', 500
        
        with open(video_player_path, 'r') as f:
            html_content = f.read()
        
        print(f"[Watch Animation] ✓ Serving video player for: {filename}")
        
        # Return HTML with proper headers
        response = make_response(html_content)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Cache-Control'] = 'public, max-age=3600'
        
        print(f"[Watch Animation] ✓ Response complete")
        return response
    
    except Exception as e:
        print(f"[Watch Animation] ✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/animations/<filename>/status', methods=['GET', 'OPTIONS'])
def check_animation_status(filename):
    """
    Check if an animation file is ready for playback
    Expects: GET /api/animations/<filename>/status
    Returns: JSON with status, file size, and playback URL
    """
    try:
        # Handle OPTIONS preflight requests
        if request.method == 'OPTIONS':
            response = make_response('', 204)
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
            return response
        
        # Validate filename to prevent directory traversal
        if '..' in filename or '/' in filename or '\\' in filename:
            print(f"[Animation Status] ✗ Invalid filename: {filename}")
            return jsonify({'ready': False, 'error': 'Invalid filename'}), 400
        
        animations_dir = os.path.abspath('animations')
        file_path = os.path.join(animations_dir, filename)
        
        # Ensure the file is within the animations directory
        if not os.path.abspath(file_path).startswith(animations_dir):
            print(f"[Animation Status] ✗ File outside animations dir: {file_path}")
            return jsonify({'ready': False, 'error': 'Invalid file path'}), 400
        
        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            
            # Check if file is complete (size > 1MB suggests animation finished encoding)
            is_ready = file_size > 1000000  # > 1MB means likely complete
            
            status_icon = '✓' if is_ready else '⏳'
            print(f"[⏱Animation Status] {status_icon} File found: {filename} ({file_size} bytes) - Ready: {is_ready}")
            
            return jsonify({
                'ready': is_ready,
                'filename': filename,
                'size': file_size,
                'url': f'/api/animations/{filename}',
                'ready_for_playback': is_ready
            }), 200
        else:
            print(f"[Animation Status] Still generating: {filename}")
            return jsonify({
                'ready': False,
                'filename': filename,
                'status': 'generating'
            }), 200
    
    except Exception as e:
        print(f"[Animation Status] ✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'ready': False, 'error': str(e)}), 500


@app.route('/api/animations/<filename>/results', methods=['GET', 'OPTIONS'])
def get_animation_results(filename):
    """
    Retrieve drift simulation results (distance, direction, map)
    Expects: GET /api/animations/<filename>/results
    Returns: JSON with drift metrics and map HTML
    """
    try:
        # Handle OPTIONS preflight requests
        if request.method == 'OPTIONS':
            response = make_response('', 204)
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
            return response
        
        # Validate filename to prevent directory traversal
        if '..' in filename or '/' in filename or '\\' in filename:
            print(f"[Drift Results] ✗ Invalid filename: {filename}")
            return jsonify({'error': 'Invalid filename'}), 400
        
        # Check if results are in cache
        if filename in drift_results_cache:
            cached = drift_results_cache[filename]
            print(f"[Drift Results] ✓ Found cached results for {filename}")
            print(f"[Drift Results] Cache contents: direction={cached.get('drift_direction_degrees')}, distance={cached.get('drift_distance_km')}, map={bool(cached.get('drift_map_html'))}, trajectory_plot={bool(cached.get('trajectory_plot_image'))}")
            return jsonify(cached), 200
        else:
            print(f"[Drift Results] ⏳ No results yet for {filename}")
            print(f"[Drift Results] Cache keys: {list(drift_results_cache.keys())}")
            return jsonify({
                'status': 'pending',
                'message': 'Drift simulation still in progress'
            }), 200
    
    except Exception as e:
        print(f"[Drift Results] ✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/debug/animations', methods=['GET', 'OPTIONS'])
def debug_animations():
    """
    Debug endpoint to check animation files and status
    """
    try:
        if request.method == 'OPTIONS':
            response = make_response('', 204)
            response.headers['Access-Control-Allow-Origin'] = '*'
            return response
        
        animations_dir = os.path.abspath('animations')
        animation_files = []
        
        if os.path.exists(animations_dir):
            for file in os.listdir(animations_dir):
                if file.endswith('.mp4'):
                    file_path = os.path.join(animations_dir, file)
                    file_size = os.path.getsize(file_path)
                    animation_files.append({
                        'filename': file,
                        'size_bytes': file_size,
                        'size_mb': round(file_size / (1024*1024), 2),
                        'ready': file_size > 1000000
                    })
        
        return jsonify({
            'animations_dir': animations_dir,
            'animations_exist': os.path.exists(animations_dir),
            'animation_files': animation_files,
            'total_files': len(animation_files),
            'cache_entries': len(drift_results_cache),
            'cache_keys': list(drift_results_cache.keys())
        }), 200
    
    except Exception as e:
        print(f"[DEBUG] ✗ Error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/debug/cache', methods=['GET', 'OPTIONS'])
def debug_cache():
    """
    Debug endpoint to check drift results cache status
    """
    try:
        if request.method == 'OPTIONS':
            response = make_response('', 204)
            response.headers['Access-Control-Allow-Origin'] = '*'
            return response
        
        cache_info = {}
        for key, value in drift_results_cache.items():
            cache_info[key] = {
                'direction': value.get('drift_direction_degrees'),
                'distance': value.get('drift_distance_km'),
                'has_map': bool(value.get('drift_map_html')),
                'has_trajectory_plot': bool(value.get('trajectory_plot_image')),
                'status': value.get('status')
            }
        
        return jsonify({
            'cache_size': len(drift_results_cache),
            'entries': cache_info,
            'timestamp': datetime.now().isoformat()
        }), 200
    
    except Exception as e:
        print(f"[DEBUG] ✗ Error: {str(e)}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("="*80)
    print("SAR OIL SPILL DETECTION API WITH DRIFT SIMULATION")
    print("="*80)
    print("\nDETECTION MODELS:")
    print(f"  ✓ Classification: {'✓ Loaded' if model else '✗ Not Loaded'} ({MODEL_PATH})")
    print(f"  ✓ U-Net Segmentation: {'✓ Loaded' if unet_model else '✗ Not Loaded'} ({UNET_MODEL_PATH})")
    
    print("\n🌊 DRIFT SIMULATION:")
    if ENABLE_DRIFT_SIMULATION:
        print(f"  ✓ Status: ENABLED")
        print(f"  ✓ OpenDrift: Available")
        print(f"  ✓ Folium Maps: {'Available' if FOLIUM_AVAILABLE else 'Not available'}")
        print(f"\n  DATA STRATEGY (NEW):")
        print(f"  ✓ Synthetic Data Generation: ENABLED (automatic bounding box generation)")
        print(f"  • Priority 1: Use local data files (currents.nc, wind.nc if available)")
        print(f"  • Priority 2: Generate synthetic data for specific bbox (FAST, ~1-3 seconds)")
        print(f"\n  SIMULATION CONFIG:")
        print(f"  • Duration: {DRIFT_SIMULATION_DURATION_HOURS} hours")
        print(f"  • Particles: {NUM_DRIFT_PARTICLES}")
        print(f"  • Time Step: {DRIFT_TIME_STEP}s")
    else:
        print(f"  ✗ Status: DISABLED")
        print("\n  Required dependencies:")
        print(f"  {'' if OPENDRIFT_AVAILABLE else '  - pip install opendrift'}")
        print(f"  {'' if FOLIUM_AVAILABLE else '  - pip install folium'}")
        print(f"  {'' if generate_synthetic_data_for_bbox else '  - Ensure drift_prediction.py has generate_synthetic_data_for_bbox()'}")
    
    print("\n" + "="*80)
    print("API ENDPOINTS:")
    print("  • POST /api/predict      - Detect oil spill and simulate drift")
    print("  • POST /api/preview      - Generate preview image")
    print("  • GET  /api/health       - Health check with system status")
    print("  • GET  /api/animations/<file>/status   - Check animation generation status")
    print("  • GET  /api/animations/<file>          - Download animation MP4")
    print("  • GET  /api/animations/<file>/results  - Get drift metrics and maps")
    print("  • GET  /api/debug/animations  - Debug: List all animation files")
    print("  • GET  /api/debug/cache       - Debug: Check drift results cache")
    
    print("\n🚀 SERVER STATUS:")
    print(f"  • Backend:  http://localhost:5001")
    print(f"  • Frontend: http://localhost:3000")
    print(f"  • Drift Results Cache: Ready")
    print(f"  • Animation Directory: {os.path.abspath('animations')}")
    print("\n" + "="*80 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5001)
