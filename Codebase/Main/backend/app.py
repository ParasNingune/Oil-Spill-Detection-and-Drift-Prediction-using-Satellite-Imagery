from flask import Flask, request, jsonify
from flask_cors import CORS
import numpy as np
import tensorflow as tf
import rasterio
from skimage.filters import threshold_otsu
import io
import base64
from PIL import Image
import cv2

app = Flask(__name__)
CORS(app)

# ============================================================================
MODEL_PATH = "BestModel.keras"  # Model file in the same directory as app.py

try:
    model = tf.keras.models.load_model(MODEL_PATH)
    print(f"Model loaded successfully from {MODEL_PATH}")
except Exception as e:
    print(f"Warning: Could not load model from {MODEL_PATH}")
    print(f"Error: {e}")
    print(f"Make sure BestModel.keras is in the backend folder")
    model = None

# Model parameters
IMG_SIZE = (512, 512)
CLASSIFICATION_THRESHOLD = 0.4    # Adjust based on your model's performance

# ============================================================================


def detect_image_format(file_bytes):
    """
    Detect image format (TIF, PNG, JPEG, etc.)
    Returns: format string ('tiff', 'png', 'jpeg')
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

    raise ValueError("Unsupported image format. Please use TIFF, PNG, or JPEG.")


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


def preprocess_standard_image(file_bytes):
    """
    Preprocess PNG/JPEG images
    Uses OpenCV logic:
    1) Decode image
    2) Resize to 256x256
    3) Convert to grayscale
    4) Create fake VV/VH channels
    5) Resize to model input size
    6) Add batch dimension

    Returns batched_image, None transform (no georeference), None CRS
    """
    try:
        # Decode bytes to OpenCV image (BGR)
        np_buffer = np.frombuffer(file_bytes, np.uint8)
        img = cv2.imdecode(np_buffer, cv2.IMREAD_COLOR)

        if img is None:
            raise ValueError("Could not decode PNG/JPEG image")

        # Resize (as requested)
        img = cv2.resize(img, (256, 256), interpolation=cv2.INTER_AREA)

        # Convert RGB/BGR -> grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Fake 2 channels (VV/VH-like)
        fake_vv = gray.astype(np.float32) / 255.0
        fake_vh = gray.astype(np.float32) / 255.0

        sar_like = np.stack([fake_vv, fake_vh], axis=-1)

        # Match model training input size (prevents dense shape mismatch)
        sar_like = tf.image.resize(sar_like, IMG_SIZE, method="bilinear").numpy()
        sar_like = np.expand_dims(sar_like, axis=0)

        return sar_like, None, None
    
    except Exception as e:
        raise ValueError(f"Error preprocessing PNG/JPEG image: {str(e)}")


def create_visualization_image(file_bytes, image_format='tiff'):
    """
    Create a visualization of the image
    For TIFF: combines bands (30:70 ratio)
    For PNG/JPEG: displays as-is with normalization
    """
    try:
        if image_format == 'tiff':
            with rasterio.open(io.BytesIO(file_bytes)) as src:
                band1 = src.read(1).astype(np.float32)  # Band 1
                band2 = src.read(2).astype(np.float32)  # Band 2
            
            # Normalize both bands using min-max normalization
            band1_norm = (band1 - np.nanmin(band1)) / (np.nanmax(band1) - np.nanmin(band1))
            band2_norm = (band2 - np.nanmin(band2)) / (np.nanmax(band2) - np.nanmin(band2))
            
            # Combine 30% Band1 + 70% Band2
            combined = 0.3 * band1_norm + 0.7 * band2_norm
        else:
            # For PNG/JPEG
            img_pil = Image.open(io.BytesIO(file_bytes)).convert('L')
            combined = np.array(img_pil, dtype=np.float32) / 255.0
        
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


def generate_oil_mask_from_file(file_bytes, image_format='tiff'):
    """
    Generate oil spill mask using Otsu thresholding
    Works with both TIFF (2-band) and standard images (PNG/JPEG)
    """
    try:
        if image_format == 'tiff':
            # Read original TIFF bands
            with rasterio.open(io.BytesIO(file_bytes)) as src:
                band1 = src.read(1).astype(float)
                band2 = src.read(2).astype(float)
            
            # Normalize both bands using min-max normalization
            band1_norm = (band1 - np.nanmin(band1)) / (np.nanmax(band1) - np.nanmin(band1))
            band2_norm = (band2 - np.nanmin(band2)) / (np.nanmax(band2) - np.nanmin(band2))
            
            # Combine 30% Band1 + 70% Band2
            combined = 0.3 * band1_norm + 0.7 * band2_norm
        else:
            # For PNG/JPEG, read as grayscale
            img_pil = Image.open(io.BytesIO(file_bytes)).convert('L')
            combined = np.array(img_pil, dtype=float) / 255.0
        
        # Compute Otsu threshold on valid data only
        valid_data = combined[~np.isnan(combined)]
        threshold = threshold_otsu(valid_data)
        
        # Create oil mask (oil = darker region)
        oil_mask = (combined < threshold).astype(np.uint8)
        
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


def predict_oil_drift(mask):
    """
    Predict oil drift direction and speed
    This is a simplified implementation - you can enhance this based on your specific requirements
    
    Returns:
        dict: Dictionary containing drift direction (degrees) and speed (km/h)
    """
    # Find contours of oil spill
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return None
    
    # Get the largest contour
    largest_contour = max(contours, key=cv2.contourArea)
    
    # Fit an ellipse to estimate the main axis of the oil spill
    if len(largest_contour) >= 5:
        ellipse = cv2.fitEllipse(largest_contour)
        angle = ellipse[2]  # Angle of rotation
        
        # Convert angle to compass direction (0-360 degrees)
        drift_direction = (90 - angle) % 360
        
        # Simplified speed estimation (you can enhance this with temporal data)
        # For now, using a placeholder based on typical oil drift speeds
        drift_speed = np.random.uniform(0.5, 2.0)  # km/h
        
        return {
            "direction": round(drift_direction, 1),
            "speed": round(drift_speed, 2)
        }
    
    return None


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


def create_overlay_visualization(file_bytes, mask, image_format='tiff'):
    """
    Create a visualization with the image and oil mask overlay with boundaries
    Works with both TIFF and standard images
    """
    try:
        if image_format == 'tiff':
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
        else:
            # For PNG/JPEG
            img_pil = Image.open(io.BytesIO(file_bytes)).convert('L')
            combined_8bit = np.array(img_pil, dtype=np.uint8)
        
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
        return None


@app.route('/api/predict', methods=['POST'])
def predict():
    """
    Main prediction endpoint
    Expects: multipart/form-data with 'image' field containing TIFF, PNG, or JPEG
    Returns: JSON with classification result, area, and drift information
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
            print(f"❌ No 'image' field in request. Available fields: {list(request.files.keys())}")
            return jsonify({'error': 'No image file provided'}), 400
        
        file = request.files['image']
        
        if file.filename == '':
            print("❌ Empty filename")
            return jsonify({'error': 'No file selected'}), 400
        
        print(f"✅ Received file: {file.filename}")
        
        # Read file bytes
        file_bytes = file.read()
        
        # Detect image format
        try:
            image_format = detect_image_format(file_bytes)
            print(f"✅ Detected image format: {image_format}")
        except Exception as e:
            print(f"❌ Image format detection failed: {e}")
            return jsonify({'error': str(e)}), 400

        # Extract bounding box coordinates (only for TIFF)
        bbox = None
        if image_format == 'tiff':
            try:
                bbox = extract_image_bbox_coords(file_bytes)
            except Exception as e:
                print(f"⚠️  Bounding box extraction failed: {e}")
                # Don't return error for standard images without bbox

        # Create visualization image
        viz_image = create_visualization_image(file_bytes, image_format)
        
        # Preprocess the image based on format
        if image_format == 'tiff':
            img, transform, crs = preprocess_sar_image(file_bytes)
            pixel_area_km2 = calculate_pixel_area_km2(transform) if transform else None
        else:
            img, transform, crs = preprocess_standard_image(file_bytes)
            pixel_area_km2 = None  # Standard images don't have pixel area info
        
        # Prepare for model prediction
        if img.ndim == 3:
            img_batch = np.expand_dims(img, axis=0)
        elif img.ndim == 4:
            img_batch = img
        else:
            raise ValueError(f"Unexpected preprocessed image shape: {img.shape}")
        
        # ============================================================================
        # MODEL PREDICTION - This is where your model runs
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
                'direction': 0,
                'distance_km': 0.0
            },
            'preview_image': viz_image,  # Add visualization
            'mask_image': None,
            'overlay_image': None
        }
        
        # If oil is detected, calculate area and drift
        if has_oil:
            # Generate oil mask from original file (not preprocessed)
            mask = generate_oil_mask_from_file(file_bytes, image_format)
            
            if mask is None:
                return jsonify({'error': 'Failed to generate oil mask'}), 500
            
            # Calculate oil spill area (only if we have pixel area info)
            if pixel_area_km2:
                oil_area = calculate_oil_area(mask, pixel_area_km2)
                num_oil_pixels = int(np.sum(mask > 0))
                response['area_km2'] = round(float(oil_area), 2)
                response['area_pixels'] = num_oil_pixels
            else:
                # For standard images, only count pixels
                num_oil_pixels = int(np.sum(mask > 0))
                response['area_pixels'] = num_oil_pixels
                response['area_km2'] = 0.0  # Not available for standard images
            
            # Predict drift
            drift_info = predict_oil_drift(mask)
            if drift_info:
                response['drift_prediction'] = {
                    'direction': drift_info['direction'],
                    'distance_km': round(drift_info['speed'] * 24, 2)  # Speed * 24h = distance
                }
            
            # Convert mask to base64 for visualization (mask only with boundaries)
            mask_image = mask_to_base64(mask)
            response['mask_image'] = mask_image
            
            # Create overlay visualization
            overlay_image = create_overlay_visualization(file_bytes, mask, image_format)
            if overlay_image:
                response['overlay_image'] = overlay_image
        
        # Calculate processing time
        processing_time_ms = (time.time() - start_time) * 1000
        response['processing_time_ms'] = round(processing_time_ms, 2)
        
        return jsonify(response), 200
    
    except Exception as e:
        print(f"Error during prediction: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/preview', methods=['POST'])
def preview():
    """
    Preview endpoint - generates visualization of the image
    Expects: multipart/form-data with 'image' field containing TIFF, PNG, or JPEG
    Returns: JSON with base64 encoded preview image
    """
    try:
        # Check if file is present
        if 'image' not in request.files:
            print(f"❌ No 'image' field in request. Available fields: {list(request.files.keys())}")
            return jsonify({'error': 'No image file provided'}), 400
        
        file = request.files['image']
        
        if file.filename == '':
            print("❌ Empty filename")
            return jsonify({'error': 'No file selected'}), 400
        
        print(f"✅ Generating preview for: {file.filename}")
        
        # Read file bytes
        file_bytes = file.read()
        
        # Detect image format
        try:
            image_format = detect_image_format(file_bytes)
        except Exception as e:
            return jsonify({'error': str(e)}), 400
        
        # Create visualization image
        viz_image = create_visualization_image(file_bytes, image_format)
        
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
    Health check endpoint
    """
    return jsonify({
        'status': 'healthy',
        'model_loaded': model is not None
    }), 200


if __name__ == '__main__':
    print("="*60)
    print("Starting SAR Oil Spill Detection API Server")
    print("="*60)
    print(f"Model Status: {'Loaded' if model else 'Not Loaded'}")
    print(f"Model Path: {MODEL_PATH}")
    print("="*60)
    print("\nServer running at http://localhost:5001")
    print("Frontend should connect at http://localhost:3000")
    print("\n")
    
    app.run(debug=True, host='0.0.0.0', port=5001)
