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
CLASSIFICATION_THRESHOLD = 0.5  # Adjust based on your model's performance

# ============================================================================


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
        raise ValueError(f"Error preprocessing image: {str(e)}")


def calculate_pixel_area_km2(transform):
    """
    Calculate the area of a single pixel in km²
    """
    res_x, res_y = abs(transform[0]), abs(transform[4])
    meters_per_degree = 111_320
    
    # Convert to km²
    area_km2 = (res_x * meters_per_degree * res_y * meters_per_degree) / 1e6
    return area_km2


def generate_oil_mask(img):
    """
    Generate oil spill mask using Otsu thresholding on VH channel
    This is the best performing method based on your analysis
    """
    vh = img[..., 1]  # VH channel
    
    # Apply Otsu thresholding
    thresh = threshold_otsu(vh)
    mask = (vh < thresh).astype(np.uint8)
    
    # Apply morphological operations to clean up the mask
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    
    return mask


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
    Convert binary mask to base64 encoded PNG image
    """
    # Convert mask to RGB for visualization
    mask_rgb = np.stack([mask * 255] * 3, axis=-1).astype(np.uint8)
    
    # Add color overlay (red for oil)
    mask_rgb[mask > 0] = [255, 50, 50]  # Red color for oil regions
    
    # Convert to PIL Image
    img = Image.fromarray(mask_rgb)
    
    # Save to bytes
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    
    # Encode to base64
    img_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    
    return img_base64


@app.route('/api/predict', methods=['POST'])
def predict():
    """
    Main prediction endpoint
    Expects: multipart/form-data with 'image' field containing a TIFF file
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
        
        # Preprocess the image
        img, transform, crs = preprocess_sar_image(file_bytes)
        
        # Calculate pixel area for area estimation
        pixel_area_km2 = calculate_pixel_area_km2(transform)
        
        # Prepare for model prediction
        img_batch = np.expand_dims(img, axis=0)
        
        # ============================================================================
        # MODEL PREDICTION - This is where your model runs
        # ============================================================================
        prediction = model.predict(img_batch, verbose=0)
        confidence = float(prediction[0][0])
        has_oil = confidence > CLASSIFICATION_THRESHOLD
        # ============================================================================
        
        response = {
            'has_oil': bool(has_oil),
            'confidence': float(confidence),
            'prediction_value': float(confidence),
            'area_km2': 0.0,
            'area_pixels': 0,
            'drift_prediction': {
                'direction': 0,
                'distance_km': 0.0
            },
            'processing_time_ms': 0  # Will be calculated
        }
        
        # If oil is detected, calculate area and drift
        if has_oil:
            # Generate oil mask
            mask = generate_oil_mask(img)
            
            # Calculate oil spill area
            oil_area = calculate_oil_area(mask, pixel_area_km2)
            num_oil_pixels = int(np.sum(mask > 0))
            
            response['area_km2'] = round(float(oil_area), 2)
            response['area_pixels'] = num_oil_pixels
            
            # Predict drift
            drift_info = predict_oil_drift(mask)
            if drift_info:
                response['drift_prediction'] = {
                    'direction': drift_info['direction'],
                    'distance_km': round(drift_info['speed'] * 24, 2)  # Speed * 24h = distance
                }
            
            # Convert mask to base64 for visualization
            mask_image = mask_to_base64(mask)
            response['mask_image'] = mask_image
        
        return jsonify(response), 200
    
    except Exception as e:
        print(f"Error during prediction: {str(e)}")
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
