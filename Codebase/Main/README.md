# Oil Spill Detection and Segmentation Framework

A comprehensive two-step deep learning approach for detecting and segmenting oil spills in SAR (Synthetic Aperture Radar) imagery.

## Framework Overview

### Two-Step Architecture:
1. **Detection Phase**: Binary classification to identify presence of oil spills
2. **Segmentation Phase**: Pixel-level segmentation to delineate spill boundaries

### Key Features:
- Advanced preprocessing pipeline with SAR-specific techniques
- EfficientNet-based detection model
- U-Net with ResNet encoder for segmentation
- Comprehensive evaluation metrics
- End-to-end inference pipeline

## Notebooks Structure

1. **01_Data_Preprocessing.ipynb** - SAR data preprocessing and augmentation
2. **02_Detection_Model.ipynb** - Oil spill detection (Step 1)
3. **03_Segmentation_Model.ipynb** - Oil spill segmentation (Step 2)
4. **04_Evaluation_Visualization.ipynb** - Model evaluation and results visualization
5. **05_End_to_End_Pipeline.ipynb** - Complete inference pipeline

## Installation

```bash
pip install -r requirements.txt
```

## Usage

Run the notebooks in sequence for complete pipeline development and evaluation.
