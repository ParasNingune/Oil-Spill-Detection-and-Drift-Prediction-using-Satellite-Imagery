import os
import glob
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import cv2
import rasterio
import tensorflow as tf

# ==============================================================================
# CONFIGURATION
# ==============================================================================
DATASET_DIR = "/Volumes/Windows8_OS/Dataset/Dataset-OG/Test"
UNET_MODEL_PATH = "/Users/parasningune/Desktop/Final-Year-Project/Codebase/Main/backend/unet.h5"
CLASS_MODEL_PATH = "/Users/parasningune/Desktop/Final-Year-Project/Codebase/Main/backend/BestModel.keras"
OUTPUT_PATH = "/Users/parasningune/Desktop/Final-Year-Project/Codebase/Main/report_assets/validation_metrics_grid_table.png"

# The 6 test cases from page 57 of the report with their correct folder categorizations
test_cases = [
    {"id": "00062", "name": "00062.tif", "category": "Oil", "true_class": "Oil"},
    {"id": "00006", "name": "00006.tif", "category": "Oil", "true_class": "Oil"},
    {"id": "00070", "name": "00070.tif", "category": "Oil", "true_class": "Oil"},
    {"id": "00057", "name": "00057.tif", "category": "No_Oil", "true_class": "No_Oil"},
    {"id": "00028", "name": "00028.tif", "category": "Oil", "true_class": "Oil"},
    {"id": "00035", "name": "00035.tif", "category": "No_Oil", "true_class": "No_Oil"}
]

# Load actual trained models
print("Loading trained models...")
unet_model = tf.keras.models.load_model(UNET_MODEL_PATH, compile=False)
class_model = tf.keras.models.load_model(CLASS_MODEL_PATH, compile=False)
print("✓ Both models loaded successfully!")

# Preprocessing helpers
def load_sar_image(path):
    with rasterio.open(path) as src:
        vv = src.read(1).astype(np.float32)
        vh = src.read(2).astype(np.float32)
    vv = np.clip(vv, -35, 5)
    vh = np.clip(vh, -40, 0)
    vv = (vv + 35) / 40
    vh = (vh + 40) / 40
    img = np.stack([vv, vh], axis=-1)
    return cv2.resize(img, (512, 512), interpolation=cv2.INTER_LINEAR)

def load_mask_image(path):
    with rasterio.open(path) as src:
        mask = src.read(1).astype(np.float32)
    mask_resized = cv2.resize(mask, (512, 512), interpolation=cv2.INTER_NEAREST)
    return (mask_resized > 0.5).astype(np.uint8)

# Otsu baseline segmentation
def otsu_segmentation(image):
    vv = image[:, :, 0]
    vh = image[:, :, 1]
    fused = 0.3 * vv + 0.7 * vh
    fused_8bit = (fused * 255).astype(np.uint8)
    _, otsu_mask = cv2.threshold(fused_8bit, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return (otsu_mask == 0).astype(np.uint8)

# Function to draw the metric sub-table
def draw_metric_subtable(ax, pred, true, acc):
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 4)
    ax.axis('off')
    rows = [
        ("Metric", "Value", True), 
        ("Pred Class", pred, False),
        ("True Class", true, False),
        ("Accuracy", f"{acc:.4f}" if isinstance(acc, float) else acc, False)
    ]
    border_color = '#dee2e6'
    ax.plot([0.02, 0.98], [4.0, 4.0], color=border_color, lw=1.2)
    for i, (metric, val, is_header) in enumerate(rows):
        y_center = 3.5 - i
        weight = 'bold' if is_header else 'normal'
        color = '#212529' if is_header else '#495057'
        ax.text(0.08, y_center, metric, ha='left', va='center', fontsize=10, fontweight=weight, color=color)
        ax.text(0.92, y_center, val, ha='right', va='center', fontsize=10, fontweight=weight, color=color)
        ax.plot([0.02, 0.98], [y_center - 0.5, y_center - 0.5], color=border_color, lw=1.2)


# ==============================================================================
# MAIN MATRIX PLOT
# ==============================================================================
print("Evaluating test cases on dataset and building table layout...")

fig = plt.figure(figsize=(15, 20.5))
# 7 rows: 1 Header, 6 Data Rows
# 6 columns: S.No, ID, Original SAR, Validation Subtable, Original Mask, Generated Mask
width_ratios = [0.5, 1.2, 2.5, 2.8, 2.5, 2.5]
height_ratios = [0.6, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8]
gs = gridspec.GridSpec(7, 6, width_ratios=width_ratios, height_ratios=height_ratios, wspace=0.06, hspace=0.08)

headers = [
    "S. No.",
    "Sample Data ID",
    "Original SAR Image",
    "Validation Metric Results",
    "Original Mask",
    "Generated Mask"
]

border_color = '#343a40'

# Draw Headers
for col_idx in range(6):
    ax = fig.add_subplot(gs[0, col_idx])
    ax.set_xticks([])
    ax.set_yticks([])
    ax.text(0.5, 0.5, headers[col_idx], ha='center', va='center', fontsize=12, fontweight='bold', color='#1a1a1a')
    ax.spines['left'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['top'].set_visible(True)
    ax.spines['top'].set_color(border_color)
    ax.spines['top'].set_linewidth(2.0)
    ax.spines['bottom'].set_visible(True)
    ax.spines['bottom'].set_color(border_color)
    ax.spines['bottom'].set_linewidth(1.2)

# Evaluate and Draw Data Rows
for row_idx, case in enumerate(test_cases):
    r = row_idx + 1
    sample_id = case["id"]
    category = case["category"]
    
    # Establish direct actual file paths
    img_path = os.path.join(DATASET_DIR, "Images", category, f"{sample_id}.tif")
    mask_path = os.path.join(DATASET_DIR, "Mask", category, f"{sample_id}_segmentation.tif")
    
    if not os.path.exists(img_path) or not os.path.exists(mask_path):
        raise FileNotFoundError(f"Error: Could not find required dataset files:\nImage: {img_path}\nMask: {mask_path}")
        
    # Load actual image and mask
    image = load_sar_image(img_path)
    gt_mask = load_mask_image(mask_path)
    
    # Run classification model inference
    pred_prob = class_model.predict(np.expand_dims(image, axis=0), verbose=0)[0][0]
    pred_class = "Oil" if pred_prob > 0.5 else "No_Oil"
    
    # Run U-Net segmentation model inference
    pred_mask_raw = unet_model.predict(np.expand_dims(image, axis=0), verbose=0)[0]
    pred_mask = pred_mask_raw[..., 0] if pred_mask_raw.ndim == 3 else pred_mask_raw
    unet_mask = (pred_mask > 0.5).astype(np.uint8)
    
    # Compute actual pixel-wise accuracy of U-Net segmentation compared to Ground Truth
    accuracy = (gt_mask == unet_mask).sum() / gt_mask.size
    
    fused = 0.3 * image[:, :, 0] + 0.7 * image[:, :, 1]
    fused_viz = (fused - fused.min()) / (fused.max() - fused.min() + 1e-6)
    
    # Column 0: S. No.
    ax_no = fig.add_subplot(gs[r, 0])
    ax_no.text(0.5, 0.5, f"{r}", ha='center', va='center', fontsize=12, fontweight='bold')
    
    # Column 1: Sample Data ID
    ax_id = fig.add_subplot(gs[r, 1])
    ax_id.text(0.5, 0.5, case["name"], ha='center', va='center', fontsize=11, fontfamily='monospace')
    
    for ax_txt in [ax_no, ax_id]:
        ax_txt.set_xticks([])
        ax_txt.set_yticks([])
        ax_txt.spines['left'].set_visible(False)
        ax_txt.spines['right'].set_visible(False)
        ax_txt.spines['top'].set_visible(False)
        if r == 6:
            ax_txt.spines['bottom'].set_visible(True)
            ax_txt.spines['bottom'].set_color(border_color)
            ax_txt.spines['bottom'].set_linewidth(2.0)
        else:
            ax_txt.spines['bottom'].set_visible(False)
            
    # Column 2: Original SAR Image
    ax_sar = fig.add_subplot(gs[r, 2])
    ax_sar.imshow(fused_viz, cmap='gray')
    ax_sar.text(0.5, 0.08, "Original SAR", color='white', ha='center', va='bottom', fontsize=9.5,
                transform=ax_sar.transAxes, bbox=dict(facecolor='black', alpha=0.6, edgecolor='none', boxstyle='round,pad=0.25'))
    
    # Column 3: Validation Metric Results Sub-table
    ax_sub = fig.add_subplot(gs[r, 3])
    draw_metric_subtable(ax_sub, pred_class, case["true_class"], accuracy)
    
    # Column 4: Original Mask (Ground Truth)
    ax_gt = fig.add_subplot(gs[r, 4])
    ax_gt.imshow(gt_mask, cmap='gray')
    ax_gt.text(0.5, 0.08, "Ground Truth", color='white', ha='center', va='bottom', fontsize=9.5,
                transform=ax_gt.transAxes, bbox=dict(facecolor='black', alpha=0.6, edgecolor='none', boxstyle='round,pad=0.25'))
    
    # Column 5: Generated Mask (U-Net)
    ax_unet = fig.add_subplot(gs[r, 5])
    ax_unet.imshow(unet_mask, cmap='gray')
    ax_unet.text(0.5, 0.08, "U-Net Mask", color='white', ha='center', va='bottom', fontsize=9.5,
                transform=ax_unet.transAxes, bbox=dict(facecolor='black', alpha=0.6, edgecolor='none', boxstyle='round,pad=0.25'))

    # Borders
    for ax_img in [ax_sar, ax_sub, ax_gt, ax_unet]:
        if ax_img != ax_sub:
            ax_img.set_xticks([])
            ax_img.set_yticks([])
        ax_img.spines['left'].set_visible(False)
        ax_img.spines['right'].set_visible(False)
        ax_img.spines['top'].set_visible(False)
        if r == 6:
            ax_img.spines['bottom'].set_visible(True)
            ax_img.spines['bottom'].set_color(border_color)
            ax_img.spines['bottom'].set_linewidth(2.0)
        else:
            ax_img.spines['bottom'].set_visible(False)

# Save high-res output
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
plt.savefig(OUTPUT_PATH, dpi=300, bbox_inches='tight', facecolor='white')
plt.close()
print("✓ Actual validation grid table successfully generated and saved to:", OUTPUT_PATH)
