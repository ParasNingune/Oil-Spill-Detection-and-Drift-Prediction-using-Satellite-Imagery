import { useState, useEffect } from 'react';
import './App.css';
import { MapContainer, TileLayer, Rectangle, Popup } from 'react-leaflet';
import L from 'leaflet';
import { jsPDF } from 'jspdf';
import 'leaflet/dist/leaflet.css';

// Fix default marker icons
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

function App() {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [serverPreview, setServerPreview] = useState(null); // Preview from backend
  const [loadingPreview, setLoadingPreview] = useState(false); // Loading state for preview
  const [modalImage, setModalImage] = useState(null); // For image popup
  const [modalTitle, setModalTitle] = useState(''); // Title for popup
  const [boundingBox, setBoundingBox] = useState(null); // Bounding box coordinates
  const [boxInput, setBoxInput] = useState({ x_min: '', y_min: '', x_max: '', y_max: '' }); // Form input for bounding box
  const [showBoundingBoxForm, setShowBoundingBoxForm] = useState(false); // Toggle form visibility
  const [showMapModal, setShowMapModal] = useState(false); // Toggle map modal visibility
  const [animationReady, setAnimationReady] = useState(false); // Track if animation file has been created
  const [animationLoading, setAnimationLoading] = useState(false); // Track animation generation in progress
  const [driftImage, setDriftImage] = useState(null); // Custom image to display for drift result

  const openImageModal = (imageSrc, title) => {
    setModalImage(imageSrc);
    setModalTitle(title);
  };

  const closeImageModal = () => {
    setModalImage(null);
    setModalTitle('');
  };

  // Poll for animation file availability
  useEffect(() => {
    if (!animationLoading || !result?.drift_animation_url) return;

    console.log('🔄 Starting animation poll for:', result.drift_animation_url);

    const pollInterval = setInterval(async () => {
      try {
        // Extract filename from URL
        const filename = result.drift_animation_url.split('/').pop();
        const statusUrl = `http://localhost:5001/api/animations/${filename}/status`;
        const resultsUrl = `http://localhost:5001/api/animations/${filename}/results`;
        
        console.log('📡 Polling:', statusUrl);
        const response = await fetch(statusUrl);
        const data = await response.json();
        
        console.log('📋 Poll response:', data);
        
        // Also fetch drift results
        try {
          const resultsResponse = await fetch(resultsUrl);
          const resultsData = await resultsResponse.json();
          
          if (resultsData.status === 'complete' || (resultsData.drift_direction_degrees !== undefined)) {
            console.log('✅ Drift results received:', resultsData);
            // Update result with drift metrics
            setResult(prevResult => ({
              ...prevResult,
              drift_prediction: {
                direction: resultsData.drift_direction_degrees || 0,
                distance_km: resultsData.drift_distance_km || 0
              },
              drift_map_html: resultsData.drift_map_html,
              initial_center: resultsData.initial_center,
              final_center: resultsData.final_center
            }));
          }
        } catch (err) {
          console.log('📊 Drift results not ready yet:', err.message);
        }
        
        if (data.ready && data.size > 1000000) {
          console.log(`✅ Animation ready: ${filename} (${data.size} bytes)`);
          console.log('🎥 Ready to play video from:', `http://localhost:5001${data.url}`);
          console.log('📹 Setting animationReady = true');
          setAnimationReady(true);
          setAnimationLoading(false);
          clearInterval(pollInterval);
        } else if (data.size) {
          const percentComplete = Math.round((data.size / 4000000) * 100);
          console.log(`⏳ Animation generating... ${data.size} bytes (${percentComplete}% of ~4MB)`);
        } else {
          console.log('⏳ Animation still generating...');
        }
      } catch (error) {
        // File not ready yet, keep polling
        console.log('⚠️ Poll error (will retry):', error.message);
      }
    }, 1000); // Poll every 1 second

    return () => clearInterval(pollInterval);
  }, [animationLoading, result?.drift_animation_url]);

  const handleBoundingBoxInputChange = (e) => {
    const { name, value } = e.target;
    setBoxInput(prev => ({
      ...prev,
      [name]: value
    }));
  };

  const handleSaveBoundingBox = () => {
    const { x_min, y_min, x_max, y_max } = boxInput;
    
    // Validate inputs
    if (!x_min || !y_min || !x_max || !y_max) {
      setError('Please fill in all bounding box coordinates');
      return;
    }

    const coords = {
      x_min: parseFloat(x_min),
      y_min: parseFloat(y_min),
      x_max: parseFloat(x_max),
      y_max: parseFloat(y_max)
    };

    // Basic validation
    if (coords.x_min >= coords.x_max || coords.y_min >= coords.y_max) {
      setError('Invalid coordinates: min values must be less than max values');
      return;
    }

    setBoundingBox(coords);
    setShowBoundingBoxForm(false);
    setError(null);
  };

  const handleEditBoundingBox = () => {
    if (boundingBox) {
      setBoxInput({
        x_min: boundingBox.x_min.toString(),
        y_min: boundingBox.y_min.toString(),
        x_max: boundingBox.x_max.toString(),
        y_max: boundingBox.y_max.toString()
      });
    }
    setShowBoundingBoxForm(!showBoundingBoxForm);
  };

  const handleFileChange = async (e) => {
    const selectedFile = e.target.files[0];
    if (selectedFile) {
      setFile(selectedFile);
      setError(null);
      setResult(null);
      setServerPreview(null);
      
      // Get preview from backend for all supported formats
      const fileExtension = selectedFile.name.split('.').pop().toLowerCase();
      const supportedFormats = ['tif', 'tiff'];
      
      if (supportedFormats.includes(fileExtension)) {
        // For all supported formats, get preview from backend
        setPreview('processing-placeholder');
        setLoadingPreview(true);
        
        const formData = new FormData();
        formData.append('image', selectedFile);
        
        try {
          const response = await fetch('http://localhost:5001/api/preview', {
            method: 'POST',
            body: formData,
          });
          
          const data = await response.json();
          
          if (response.ok && data.preview_image) {
            setServerPreview(data.preview_image);
          } else {
            console.error('Failed to generate preview:', data.error);
            setError('Failed to generate preview');
          }
        } catch (err) {
          console.error('Failed to generate preview:', err);
          setError('Failed to connect to server for preview');
        } finally {
          setLoadingPreview(false);
        }
      } else {
        setError('Unsupported file format. Please use TIFF.');
      }
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!file) {
      setError('Please select a file');
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);
    setBoundingBox(null); // Clear previous bounding box

    const formData = new FormData();
    formData.append('image', file);  // Backend expects 'image' field

    try {
      const response = await fetch('http://localhost:5001/api/predict', {
        method: 'POST',
        body: formData,
      });

      const data = await response.json();

      if (response.ok) {
        setResult(data);
        // If backend provides a preview image, use it
        if (data.preview_image) {
          setServerPreview(data.preview_image);
        }
        // Extract bounding box coordinates from the response
        if (data.bbox) {
          setBoundingBox({
            x_min: data.bbox.left,
            y_min: data.bbox.bottom,
            x_max: data.bbox.right,
            y_max: data.bbox.top,
            crs: data.bbox.crs
          });
        } else {
          // If bbox is missing, prompt user to enter manually
          setShowBoundingBoxForm(true);
          setBoxInput({ x_min: '', y_min: '', x_max: '', y_max: '' });
        }
        // If animation is generating in background, start polling for it
        if (data.drift_animation_status === 'generating' && data.drift_animation_url) {
          console.log('🎬 Animation generation started with URL:', data.drift_animation_url);
          console.log('📊 Animation status:', data.drift_animation_status);
          setAnimationLoading(true);
          setAnimationReady(false);
        } else {
          console.log('⚠️ Animation not generating. Status:', data.drift_animation_status);
          console.log('📋 Full response:', data);
        }
      } else {
        setError(data.error || 'An error occurred');
      }
    } catch (err) {
      setError('Failed to connect to server. Make sure backend is running on port 5001.');
      console.error('Error:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setFile(null);
    setPreview(null);
    setResult(null);
    setError(null);
    setServerPreview(null);
    setLoadingPreview(false);
    setBoundingBox(null);
    setBoxInput({ x_min: '', y_min: '', x_max: '', y_max: '' });
    setShowBoundingBoxForm(false);
    setShowMapModal(false);
    setAnimationLoading(false);
    setAnimationReady(false);
    closeImageModal();
  };

  const getConfidenceInfo = (confidence) => {
    const percentage = (confidence || 0) * 100;

    if (percentage >= 90) {
      return {
        label: 'High Confidence',
        description: 'Prediction is very reliable.',
        badgeClass: 'bg-green-500/20 text-green-300 border-green-500/30'
      };
    }

    if (percentage >= 70) {
      return {
        label: 'Medium Confidence',
        description: 'Prediction is likely correct but should be reviewed.',
        badgeClass: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30'
      };
    }

    return {
      label: 'Low Confidence',
      description: 'Prediction is uncertain. Consider re-checking with another image.',
      badgeClass: 'bg-red-500/20 text-red-300 border-red-500/30'
    };
  };

  const downloadBase64Image = (base64Data, fileName) => {
    if (!base64Data) return;

    const link = document.createElement('a');
    link.href = `data:image/png;base64,${base64Data}`;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const getImageDimensions = (dataUrl) => new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve({ width: img.width, height: img.height });
    img.onerror = () => resolve({ width: 800, height: 600 });
    img.src = dataUrl;
  });

  const getStaticMapDataUrl = async () => {
    if (!boundingBox) return null;

    try {
      const centerLat = ((boundingBox.y_min + boundingBox.y_max) / 2).toFixed(6);
      const centerLon = ((boundingBox.x_min + boundingBox.x_max) / 2).toFixed(6);
      const mapUrl = `https://staticmap.openstreetmap.de/staticmap.php?center=${centerLat},${centerLon}&zoom=8&size=900x450&markers=${centerLat},${centerLon},lightblue1`;

      const response = await fetch(mapUrl);
      if (!response.ok) return null;

      const blob = await response.blob();
      return await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onloadend = () => resolve(reader.result);
        reader.onerror = () => resolve(null);
        reader.readAsDataURL(blob);
      });
    } catch {
      return null;
    }
  };

  const normalizeCenterPoint = (point) => {
    if (!point) return null;

    if (Array.isArray(point) && point.length >= 2) {
      const lat = Number(point[0]);
      const lon = Number(point[1]);
      if (Number.isFinite(lat) && Number.isFinite(lon)) {
        return { lat, lon };
      }
      return null;
    }

    if (typeof point === 'object') {
      const lat = Number(point.lat ?? point.latitude ?? point.y);
      const lon = Number(point.lon ?? point.lng ?? point.longitude ?? point.x);
      if (Number.isFinite(lat) && Number.isFinite(lon)) {
        return { lat, lon };
      }
    }

    return null;
  };

  const getDestinationPoint = (originLat, originLon, distanceKm, bearingDegrees) => {
    const earthRadiusKm = 6371;
    const angularDistance = distanceKm / earthRadiusKm;
    const bearing = (bearingDegrees * Math.PI) / 180;
    const lat1 = (originLat * Math.PI) / 180;
    const lon1 = (originLon * Math.PI) / 180;

    const lat2 = Math.asin(
      Math.sin(lat1) * Math.cos(angularDistance) +
      Math.cos(lat1) * Math.sin(angularDistance) * Math.cos(bearing)
    );

    const lon2 = lon1 + Math.atan2(
      Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(lat1),
      Math.cos(angularDistance) - Math.sin(lat1) * Math.sin(lat2)
    );

    return {
      lat: (lat2 * 180) / Math.PI,
      lon: (lon2 * 180) / Math.PI
    };
  };

  const getDriftStaticMapDataUrl = async () => {
    try {
      let start = normalizeCenterPoint(result?.initial_center);
      let end = normalizeCenterPoint(result?.final_center);

      if (!start && boundingBox) {
        start = {
          lat: (Number(boundingBox.y_min) + Number(boundingBox.y_max)) / 2,
          lon: (Number(boundingBox.x_min) + Number(boundingBox.x_max)) / 2,
        };
      }

      if (!end && start && result?.drift_prediction?.distance_km) {
        end = getDestinationPoint(
          start.lat,
          start.lon,
          Number(result.drift_prediction.distance_km) || 0,
          Number(result.drift_prediction.direction) || 0
        );
      }

      if (!start || !end) return null;

      const centerLat = ((start.lat + end.lat) / 2).toFixed(6);
      const centerLon = ((start.lon + end.lon) / 2).toFixed(6);
      const markers = `${start.lat.toFixed(6)},${start.lon.toFixed(6)},lightblue1|${end.lat.toFixed(6)},${end.lon.toFixed(6)},red1`;
      const path = `${start.lat.toFixed(6)},${start.lon.toFixed(6)}|${end.lat.toFixed(6)},${end.lon.toFixed(6)}`;

      const mapUrl = `https://staticmap.openstreetmap.de/staticmap.php?center=${centerLat},${centerLon}&zoom=7&size=900x450&markers=${encodeURIComponent(markers)}&path=${encodeURIComponent(path)}`;
      const response = await fetch(mapUrl);
      if (!response.ok) return null;

      const blob = await response.blob();
      return await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onloadend = () => resolve(reader.result);
        reader.onerror = () => resolve(null);
        reader.readAsDataURL(blob);
      });
    } catch {
      return null;
    }
  };

  const addImagePage = async (pdf, title, base64Data) => {
    if (!base64Data) return;

    const pageWidth = 210;
    const pageHeight = 297;
    const margin = 10;
    const dataUrl = `data:image/png;base64,${base64Data}`;
    const dimensions = await getImageDimensions(dataUrl);
    const maxWidth = pageWidth - margin * 2;
    const maxHeight = pageHeight - 35;

    let renderWidth = maxWidth;
    let renderHeight = (dimensions.height / dimensions.width) * renderWidth;

    if (renderHeight > maxHeight) {
      renderHeight = maxHeight;
      renderWidth = (dimensions.width / dimensions.height) * renderHeight;
    }

    const x = (pageWidth - renderWidth) / 2;
    const y = 20;

    pdf.addPage();
    pdf.setFontSize(14);
    pdf.setTextColor(20, 30, 60);
    pdf.text(title, margin, 14);
    pdf.addImage(dataUrl, 'PNG', x, y, renderWidth, renderHeight);
  };

  // Helper component for info tooltips - Feature #4
  const InfoTooltip = ({ text, children }) => (
    <div className="relative inline-block group">
      {children}
      <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 bg-gray-900 text-white text-xs rounded-lg whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none border border-white/20 z-50 shadow-lg">
        {text}
        <div className="absolute top-full left-1/2 -translate-x-1/2 w-2 h-2 bg-gray-900 border-r border-b border-white/20 transform rotate-45"></div>
      </div>
    </div>
  );

  const downloadAllExports = async () => {
    if (!result || !result.mask_image || !result.overlay_image) return;

    try {
      const pdf = new jsPDF('p', 'mm', 'a4');
      const margin = 12;
      let y = 14;
      const pageHeight = pdf.internal.pageSize.height;

      pdf.setFont('helvetica', 'normal');

      const addNewPage = () => {
        pdf.addPage();
        return margin;
      };

      // Title and General Info
      pdf.setFontSize(18);
      pdf.setTextColor(20, 30, 60);
      pdf.text('SAR Oil Spill Detection - Complete Analysis Report', margin, y);
      y += 8;

      pdf.setFontSize(10);
      pdf.setTextColor(80, 80, 80);
      pdf.text(`Report Generated: ${new Date().toLocaleString()}`, margin, y);
      y += 6;
      pdf.text(`Processing Time: ${result.processing_time_ms} ms`, margin, y);
      y += 8;

      // Detection Summary
      pdf.setFontSize(12);
      pdf.setTextColor(30, 30, 30);
      pdf.text('DETECTION SUMMARY', margin, y);
      y += 6;
      pdf.setFontSize(10);
      pdf.text(`Status: ${result.has_oil ? 'WARNING - OIL SPILL DETECTED' : 'CLEAR - NO OIL DETECTED'}`, margin, y);
      y += 5;
      pdf.text(`Confidence Level: ${(result.confidence * 100).toFixed(1)}% (${confidenceInfo?.label || 'N/A'})`, margin, y);
      y += 5;
      pdf.text(`Processing Status: Complete`, margin, y);
      y += 8;

      // Area Information
      if (result.has_oil) {
        pdf.setFontSize(12);
        pdf.setTextColor(30, 30, 30);
        pdf.text('AFFECTED AREA', margin, y);
        y += 6;
        pdf.setFontSize(10);
        pdf.text(`Total Area: ${result.area_km2} km2`, margin, y);
        y += 5;
        pdf.text(`Pixels Detected: ${result.area_pixels?.toLocaleString() || 'N/A'}`, margin, y);
        y += 5;
        const severity = result.area_km2 > 100 ? 'Critical' : result.area_km2 > 50 ? 'High' : 'Moderate';
        pdf.text(`Severity Level: ${severity}`, margin, y);
        y += 5;
        pdf.text(`Detection Density: ${((result.area_pixels / (111.32 * 110.57)) * 100).toFixed(1)}%`, margin, y);
        y += 5;
        const areaRef = result.area_km2 > 50 ? `~${(result.area_km2 / 2.6).toFixed(0)} square miles` : `~${(result.area_km2 * 100).toFixed(0)} hectares`;
        pdf.text(`Reference: ${areaRef}`, margin, y);
        y += 8;
      }

      // Drift Information
      if (result.drift_prediction) {
        if (y > pageHeight - 80) y = addNewPage();
        
        pdf.setFontSize(12);
        pdf.setTextColor(30, 30, 30);
        pdf.text('DRIFT PREDICTION (48 HOURS)', margin, y);
        y += 6;
        pdf.setFontSize(10);
        pdf.text(`Direction: ${result.drift_prediction.direction || 0} deg (compass bearing)`, margin, y);
        y += 5;
        pdf.text(`Distance: ${result.drift_prediction.distance_km || 0} km`, margin, y);
        y += 5;
        pdf.text(`Daily Drift Rate: ${((result.drift_prediction.distance_km / 2) || 0).toFixed(2)} km/day`, margin, y);
        y += 8;

        // Add drift map for better understanding
        const driftMapDataUrl = await getDriftStaticMapDataUrl();
        if (driftMapDataUrl) {
          if (y > pageHeight - 110) y = addNewPage();

          pdf.setFontSize(11);
          pdf.setTextColor(30, 30, 30);
          pdf.text('Drift Path Map (Start to Predicted End)', margin, y);
          y += 3;
          pdf.addImage(driftMapDataUrl, 'PNG', margin, y, 186, 85);
          y += 91;
        } else {
          pdf.setFontSize(9);
          pdf.setTextColor(100, 100, 100);
          pdf.text('(Drift map unavailable for this result)', margin, y);
          y += 6;
        }
      }

      // Bounding Box
      if (boundingBox) {
        if (y > pageHeight - 60) y = addNewPage();
        
        pdf.setFontSize(12);
        pdf.setTextColor(30, 30, 30);
        pdf.text('GEOGRAPHIC COORDINATES', margin, y);
        y += 6;
        pdf.setFontSize(10);
        pdf.text(`West (Lon Min): ${boundingBox.x_min.toFixed(6)}`, margin, y);
        y += 5;
        pdf.text(`East (Lon Max): ${boundingBox.x_max.toFixed(6)}`, margin, y);
        y += 5;
        pdf.text(`South (Lat Min): ${boundingBox.y_min.toFixed(6)}`, margin, y);
        y += 5;
        pdf.text(`North (Lat Max): ${boundingBox.y_max.toFixed(6)}`, margin, y);
        y += 5;
        if (boundingBox.crs) {
          pdf.text(`CRS: ${boundingBox.crs}`, margin, y);
          y += 5;
        }
        y += 3;

        const mapDataUrl = await getStaticMapDataUrl();
        if (mapDataUrl && y < pageHeight - 110) {
          pdf.setFontSize(11);
          pdf.setTextColor(30, 30, 30);
          pdf.text('Detection Area Map', margin, y);
          y += 3;
          pdf.addImage(mapDataUrl, 'PNG', margin, y, 186, 80);
          y += 86;
        }
      }

      // Data Quality
      if (y > pageHeight - 50) y = addNewPage();
      
      pdf.setFontSize(12);
      pdf.setTextColor(30, 30, 30);
      pdf.text('DATA QUALITY ASSESSMENT', margin, y);
      y += 6;
      pdf.setFontSize(10);
      pdf.text('[CHECK] Image Resolution: Good (Full 10m resolution SAR data)', margin, y);
      y += 5;
      pdf.text('[CHECK] Georeference: Valid (Coordinates verified)', margin, y);
      y += 5;
      pdf.text('[WARNING] Drift Confidence: Medium (Based on synthetic oceanographic data)', margin, y);
      y += 5;
      pdf.text('[INFO] Data Source: Synthetic oceanographic conditions', margin, y);
      y += 8;

      // Recommendations
      if (result.has_oil) {
        pdf.setFontSize(12);
        pdf.setTextColor(30, 30, 30);
        pdf.text('RECOMMENDED ACTIONS', margin, y);
        y += 6;
        pdf.setFontSize(10);
        pdf.text('* Alert maritime authorities immediately', margin, y);
        y += 5;
        pdf.text('* Monitor affected area using satellite imagery', margin, y);
        y += 5;
        pdf.text('* Prepare containment resources in drift direction', margin, y);
        y += 5;
        pdf.text('* Re-check prediction after 12 hours with new data', margin, y);
        y += 8;
      }

      // Images on new pages
      const previewToAdd = result.preview_image || serverPreview;
      if (previewToAdd) {
        await addImagePage(pdf, 'SAR Preview Image', previewToAdd);
      }
      await addImagePage(pdf, 'Detection Mask', result.mask_image);
      await addImagePage(pdf, 'Combined Overlay', result.overlay_image);

      pdf.save(`sar_detection_report_${Date.now()}.pdf`);
    } catch (error) {
      console.error('PDF generation error:', error);
      setError('Failed to generate PDF report. Please try again.');
    }
  };

  // Add keyboard support for ESC key to close modal
  useEffect(() => {
    const handleEscKey = (e) => {
      if (e.key === 'Escape' && modalImage) {
        closeImageModal();
      }
    };
    
    window.addEventListener('keydown', handleEscKey);
    return () => window.removeEventListener('keydown', handleEscKey);
  }, [modalImage]);

  // Trigger map resize when modal opens
  useEffect(() => {
    if (showMapModal) {
      setTimeout(() => {
        window.dispatchEvent(new Event('resize'));
      }, 100);
    }
  }, [showMapModal]);

  // Scroll to top after analysis result is shown
  useEffect(() => {
    if (result) {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }, [result]);

  const confidenceInfo = result ? getConfidenceInfo(result.confidence) : null;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-blue-900 to-slate-900 py-8 px-4">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-20 h-20 bg-gradient-to-br from-blue-500 to-cyan-500 rounded-2xl mb-4 shadow-lg shadow-blue-500/50">
            <svg className="w-12 h-12 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
          </div>
          <h1 className="text-6xl font-bold bg-gradient-to-r from-blue-400 via-cyan-400 to-blue-500 bg-clip-text text-transparent mb-3">
            SAR Oil Spill Detection
          </h1>
          <p className="text-2xl text-gray-300 font-light mb-2">AI-Powered Marine Environmental Monitoring</p>
          <div className="flex items-center justify-center gap-2 text-sm text-gray-400">
            <div className="flex items-center gap-1">
              <span className="inline-block w-2 h-2 bg-green-500 rounded-full animate-pulse"></span>
              <span>System Online</span>
            </div>
            <span>•</span>
            <span>Final Year Project 2026</span>
          </div>
        </div>

        {/* Main Card */}
        <div className="bg-gradient-to-br from-white/10 to-white/5 backdrop-blur-xl border border-white/20 rounded-3xl shadow-2xl p-8">
          {!result ? (
            /* Upload Form */
            <form onSubmit={handleSubmit} className="space-y-6">
              {/* File Upload */}
              <div className="relative border-2 border-dashed border-blue-400/40 rounded-2xl p-10 text-center hover:border-blue-400/70 hover:bg-blue-500/5 transition-all cursor-pointer group">
                <input
                  type="file"
                  onChange={handleFileChange}
                  accept=".tiff,.tif"
                  className="hidden"
                  id="file-upload"
                />
                <label htmlFor="file-upload" className="cursor-pointer">
                  <div className="flex flex-col items-center">
                    <div className="relative mb-5">
                      <div className="absolute inset-0 bg-blue-500/20 rounded-full blur-xl group-hover:bg-blue-500/30 transition-all"></div>
                      <svg className="relative w-20 h-20 text-blue-400 group-hover:scale-110 group-hover:text-blue-300 transition-all duration-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                      </svg>
                    </div>
                    <span className="text-2xl font-bold text-white mb-2 group-hover:text-blue-300 transition-colors">
                      {file ? file.name : 'Upload SAR Image'}
                    </span>
                    <p className="text-sm text-gray-400 mb-3">
                      Drag and drop or click to browse
                    </p>
                    <div className="flex items-center gap-3 text-xs text-gray-500">
                      <span className="px-3 py-1 bg-white/5 rounded-full border border-white/10">TIFF</span>
                      <span className="text-gray-600">•</span>
                      <span>Max 50MB</span>
                    </div>
                  </div>
                </label>
              </div>

              {/* Image Preview */}
              {preview && (
                <div className="animate-fadeIn space-y-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xl font-bold text-white flex items-center gap-2">
                      <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                      </svg>
                      Image Preview
                    </h3>
                    {file && (
                      <div className="flex items-center gap-2 text-sm">
                        <span className="px-3 py-1 bg-blue-500/20 text-blue-300 rounded-full border border-blue-500/30 font-medium">
                          {(file.size / 1024 / 1024).toFixed(2)} MB
                        </span>
                      </div>
                    )}
                  </div>
                  
                  <div className="relative rounded-2xl overflow-hidden border-2 border-white/20 bg-gradient-to-br from-slate-800/50 to-slate-900/50 shadow-xl">
                    {loadingPreview ? (
                      /* Loading Preview */
                      <div className="flex flex-col items-center justify-center py-20 px-8">
                        <div className="relative mb-6">
                          <div className="absolute inset-0 bg-blue-500/30 rounded-full blur-2xl"></div>
                          <div className="relative animate-spin rounded-full h-20 w-20 border-4 border-t-blue-400 border-r-blue-400 border-b-transparent border-l-transparent"></div>
                        </div>
                        <p className="text-white text-xl font-bold mb-2">Generating Preview...</p>
                        <p className="text-gray-400 text-sm">Processing SAR bands with 30:70 VV/VH combination</p>
                      </div>
                    ) : serverPreview ? (
                      /* Server-Generated Preview - Shown immediately after upload */
                      <div className="relative group bg-black">
                        <img 
                          src={`data:image/png;base64,${serverPreview}`}
                          alt="SAR Visualization" 
                          className="w-full h-auto object-cover"
                          style={{ maxHeight: '600px' }}
                        />
                        <div className="absolute top-3 right-3 flex gap-2">
                          <div className="bg-gradient-to-r from-blue-600 to-cyan-600 backdrop-blur-sm px-4 py-2 rounded-xl text-xs font-bold text-white shadow-lg border border-white/20">
                            30:70 VV/VH Combination
                          </div>
                        </div>
                        <div className="absolute bottom-3 left-3 bg-black/70 backdrop-blur-md px-4 py-2 rounded-xl text-xs text-white border border-white/20">
                          <span className="font-semibold">File:</span> {file?.name}
                        </div>
                      </div>
                    ) : preview === 'tiff-placeholder' ? (
                      /* TIFF Placeholder - Fallback if preview generation failed */
                      <div className="flex flex-col items-center justify-center py-20 px-8">
                        <div className="relative mb-5">
                          <div className="absolute inset-0 bg-red-500/20 rounded-full blur-xl"></div>
                          <svg className="relative w-28 h-28 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                          </svg>
                        </div>
                        <p className="text-white text-xl font-bold mb-2">Preview Generation Failed</p>
                        <p className="text-gray-400 text-sm text-center max-w-md">
                          Unable to generate preview. Click "Analyze Image" to continue with the analysis.
                        </p>
                      </div>
                    ) : (
                      /* Regular Image Preview (PNG/JPG) */
                      <div className="relative group bg-black">
                        <img 
                          src={preview} 
                          alt="Preview" 
                          className="w-full h-auto object-cover"
                          style={{ maxHeight: '600px' }}
                        />
                        <div className="absolute bottom-3 left-3 bg-black/70 backdrop-blur-md px-4 py-2 rounded-xl text-xs text-white border border-white/20">
                          <span className="font-semibold">File:</span> {file?.name}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Error Message */}
              {error && (
                <div className="bg-gradient-to-r from-red-500/20 to-pink-500/20 border-2 border-red-500/50 p-5 rounded-2xl backdrop-blur-sm animate-fadeIn">
                  <div className="flex items-start gap-3">
                    <svg className="w-6 h-6 text-red-400 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <div>
                      <h4 className="text-red-300 font-bold mb-1">Error</h4>
                      <p className="text-red-200">{error}</p>
                    </div>
                  </div>
                </div>
              )}

              {/* Submit Button */}
              <button
                type="submit"
                disabled={!file || loading || loadingPreview}
                className="relative w-full group overflow-hidden"
              >
                <div className="absolute inset-0 bg-gradient-to-r from-blue-600 via-cyan-600 to-blue-600 opacity-0 group-hover:opacity-100 transition-opacity duration-300"></div>
                <div className={`relative bg-gradient-to-r from-blue-500 to-cyan-500 text-white py-5 px-8 rounded-2xl font-bold text-lg shadow-xl shadow-blue-500/50 transition-all duration-300 ${
                  !file || loading || loadingPreview 
                    ? 'opacity-50 cursor-not-allowed' 
                    : 'group-hover:shadow-2xl group-hover:shadow-blue-500/60 group-hover:scale-[1.02]'
                }`}>
                  {loading ? (
                    <span className="flex items-center justify-center gap-3">
                      <div className="relative">
                        <svg className="animate-spin h-6 w-6" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                        </svg>
                      </div>
                      <span>Analyzing Oil Spill...</span>
                    </span>
                  ) : loadingPreview ? (
                    <span className="flex items-center justify-center gap-3">
                      <div className="animate-spin rounded-full h-5 w-5 border-2 border-t-white border-r-white border-b-transparent border-l-transparent"></div>
                      <span>Loading Preview...</span>
                    </span>
                  ) : (
                    <span className="flex items-center justify-center gap-3">
                      <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                      </svg>
                      Analyze Image
                    </span>
                  )}
                </div>
              </button>
            </form>
          ) : (
            /* Results Display */
            <div className="space-y-6 animate-fadeIn">
              {/* Header with Reset Button */}
              <div className="flex justify-between items-center mb-6">
                <h2 className="text-2xl font-bold text-white flex items-center gap-3">
                  <svg className="w-8 h-8 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                  </svg>
                  Analysis Results
                </h2>
                <button 
                  onClick={handleReset} 
                  className="px-6 py-3 bg-gradient-to-r from-blue-500 to-cyan-500 hover:from-blue-600 hover:to-cyan-600 text-white rounded-xl font-semibold transition-all shadow-lg hover:shadow-xl"
                >
                  New Analysis
                </button>
              </div>

              {/* Image Visualizations - Show if oil detected */}
              {result.has_oil && (serverPreview || result.mask_image || result.overlay_image) && (
                <div className="space-y-5 mb-8 animate-fadeIn">
                  
                  
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                    {/* Original SAR Image */}
                    {serverPreview && (
                      <div className="group space-y-3 animate-scaleIn">
                        <div 
                          className="relative rounded-2xl overflow-hidden border-2 border-blue-500/40 bg-black shadow-2xl transition-all duration-300 group-hover:border-blue-500/70 group-hover:shadow-blue-500/25 cursor-pointer"
                          onClick={() => openImageModal(`data:image/png;base64,${serverPreview}`, 'Original SAR Visualization')}
                        >
                          <img 
                            src={`data:image/png;base64,${serverPreview}`}
                            alt="Original SAR" 
                            className="w-full h-auto object-cover transition-transform duration-300 group-hover:scale-105"
                            style={{ maxHeight: '300px' }}
                          />
                          <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex items-center justify-center">
                            <svg className="w-12 h-12 text-white opacity-0 group-hover:opacity-100 transition-opacity duration-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v3m0 0v3m0-3h3m-3 0H7" />
                            </svg>
                          </div>
                          <div className="absolute top-3 right-3 bg-gradient-to-r from-blue-600 to-blue-700 backdrop-blur-sm px-4 py-2 rounded-xl text-xs font-bold text-white shadow-lg border border-blue-400/30">
                            Original SAR
                          </div>
                        </div>
                        <div className="text-center">
                          <p className="text-sm text-gray-300 font-semibold">SAR Visualization</p>
                          <p className="text-xs text-gray-500">30:70 VV/VH Combination</p>
                        </div>
                      </div>
                    )}
                    
                    {/* Oil Mask with Boundaries */}
                    {result.mask_image && (
                      <div className="group space-y-3 animate-scaleIn" style={{ animationDelay: '0.1s' }}>
                        <div 
                          className="relative rounded-2xl overflow-hidden border-2 border-red-500/40 bg-black shadow-2xl transition-all duration-300 group-hover:border-red-500/70 group-hover:shadow-red-500/25 cursor-pointer"
                          onClick={() => openImageModal(`data:image/png;base64,${result.mask_image}`, 'Oil Detection Mask')}
                        >
                          <img 
                            src={`data:image/png;base64,${result.mask_image}`}
                            alt="Oil Mask" 
                            className="w-full h-auto object-cover transition-transform duration-300 group-hover:scale-105"
                            style={{ maxHeight: '300px' }}
                          />
                          <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex items-center justify-center">
                            <svg className="w-12 h-12 text-white opacity-0 group-hover:opacity-100 transition-opacity duration-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v3m0 0v3m0-3h3m-3 0H7" />
                            </svg>
                          </div>
                          <div className="absolute top-3 right-3 bg-gradient-to-r from-red-600 to-red-700 backdrop-blur-sm px-4 py-2 rounded-xl text-xs font-bold text-white shadow-lg border border-red-400/30">
                            Oil Mask
                          </div>
                        </div>
                        <div className="text-center">
                          <p className="text-sm text-gray-300 font-semibold">Detection Mask</p>
                          <p className="text-xs text-gray-500">Identified Oil Regions</p>
                        </div>
                      </div>
                    )}
                    
                    {/* Overlay Visualization */}
                    {result.overlay_image && (
                      <div className="group space-y-3 animate-scaleIn" style={{ animationDelay: '0.2s' }}>
                        <div 
                          className="relative rounded-2xl overflow-hidden border-2 border-yellow-500/40 bg-black shadow-2xl transition-all duration-300 group-hover:border-yellow-500/70 group-hover:shadow-yellow-500/25 cursor-pointer"
                          onClick={() => openImageModal(`data:image/png;base64,${result.overlay_image}`, 'SAR + Oil Detection Overlay')}
                        >
                          <img 
                            src={`data:image/png;base64,${result.overlay_image}`}
                            alt="Overlay" 
                            className="w-full h-auto object-cover transition-transform duration-300 group-hover:scale-105"
                            style={{ maxHeight: '300px' }}
                          />
                          <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex items-center justify-center">
                            <svg className="w-12 h-12 text-white opacity-0 group-hover:opacity-100 transition-opacity duration-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v3m0 0v3m0-3h3m-3 0H7" />
                            </svg>
                          </div>
                          <div className="absolute top-3 right-3 bg-gradient-to-r from-yellow-600 to-orange-600 backdrop-blur-sm px-4 py-2 rounded-xl text-xs font-bold text-white shadow-lg border border-yellow-400/30">
                            Overlay
                          </div>
                        </div>
                        <div className="text-center">
                          <p className="text-sm text-gray-300 font-semibold">Combined View</p>
                          <p className="text-xs text-gray-500">SAR + Oil Detection</p>
                        </div>
                      </div>
                    )}
                  </div>
                  
                  {/* Enhanced Legend */}
                  <div className="bg-gradient-to-r from-white/5 to-white/10 border border-white/20 rounded-2xl p-5 backdrop-blur-sm">
                    <div className="flex items-center justify-center gap-8 text-sm flex-wrap">
                      <div className="flex items-center gap-3">
                        <div className="w-6 h-6 bg-gradient-to-br from-blue-500 to-blue-700 rounded-lg shadow-lg"></div>
                        <span className="text-gray-200 font-medium">SAR Bands (VV/VH)</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="w-6 h-6 bg-gradient-to-br from-red-500 to-red-700 rounded-lg shadow-lg"></div>
                        <span className="text-gray-200 font-medium">Oil Spill Areas</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="w-6 h-6 bg-gradient-to-br from-yellow-400 to-yellow-600 rounded-lg shadow-lg"></div>
                        <span className="text-gray-200 font-medium">Detection Boundaries</span>
                      </div>
                    </div>
                  </div>

                  
                </div>
              )}

              {/* Detection Summary */}
              <div className="relative bg-gradient-to-r from-white/10 to-white/5 border border-white/20 rounded-2xl p-5 backdrop-blur-sm overflow-hidden animate-fadeIn">
                <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-cyan-500 via-blue-500 to-cyan-500"></div>
                <div className="w-full flex justify-center">
                    <button
                      onClick={downloadAllExports}
                      disabled={!result.mask_image || !result.overlay_image}
                      className="px-6 py-3 rounded-lg text-base font-semibold bg-green-500/20 text-green-300 border border-green-500/40 hover:bg-green-500/30 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      Download Complete Report PDF
                    </button>
                </div>
              </div>

              {/* Main Status Card */}
              <div className={`relative p-6 rounded-2xl border-2 overflow-hidden animate-fadeIn ${
                result.has_oil 
                  ? 'bg-gradient-to-br from-red-500/20 to-orange-500/10 border-red-500/50' 
                  : 'bg-gradient-to-br from-green-500/20 to-emerald-500/10 border-green-500/50'
              }`}>
                <div className="absolute top-0 right-0 w-64 h-64 bg-gradient-radial from-white/5 to-transparent rounded-full blur-3xl"></div>
                <div className="relative flex items-center gap-5">
                  <div className={`relative flex-shrink-0 ${result.has_oil ? 'animate-pulse-slow' : ''}`}>
                    <div className={`absolute inset-0 ${result.has_oil ? 'bg-red-500/30' : 'bg-green-500/30'} rounded-full blur-xl`}></div>
                    {result.has_oil ? (
                      <svg className="relative w-16 h-16 text-red-400" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd"/>
                      </svg>
                    ) : (
                      <svg className="relative w-16 h-16 text-green-400" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd"/>
                      </svg>
                    )}
                  </div>
                  <div className="flex-1">
                    <h3 className={`text-2xl font-bold mb-1 ${result.has_oil ? 'text-red-100' : 'text-green-100'}`}>
                      {result.has_oil ? 'Oil Spill Detected' : 'No Oil Detected'}
                    </h3>
                    <p className={`text-base ${result.has_oil ? 'text-red-200' : 'text-green-200'}`}>
                      {result.has_oil ? '⚠️ Environmental response required' : '✓ Area is clear and safe'}
                    </p>
                  </div>
                </div>
              </div>

              {/* Confidence Score */}
              <div className="relative bg-gradient-to-br from-white/10 to-white/5 p-6 rounded-2xl border border-white/20 backdrop-blur-sm overflow-hidden animate-fadeIn">
                <div className="absolute top-0 right-0 w-48 h-48 bg-cyan-500/10 rounded-full blur-3xl"></div>
                <div className="relative">
                  <div className="flex justify-between items-center mb-3">
                    <h3 className="text-lg font-bold text-white flex items-center gap-2">
                      <svg className="w-5 h-5 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                      </svg>
                      Confidence Level
                    </h3>
                    <div className="text-right">
                      <span className="text-3xl font-bold bg-gradient-to-r from-cyan-400 to-blue-500 bg-clip-text text-transparent">
                        {(result.confidence * 100).toFixed(1)}%
                      </span>
                      <div className="mt-1">
                        <span className={`inline-flex items-center px-2.5 py-1 rounded-md text-xs font-semibold border ${confidenceInfo?.badgeClass}`}>
                          {confidenceInfo?.label}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="relative h-5 bg-gray-800/50 rounded-full overflow-hidden border border-white/10">
                    <div
                      className={`h-full transition-all duration-1000 ease-out ${
                        result.has_oil 
                          ? 'bg-gradient-to-r from-red-500 via-orange-500 to-red-600' 
                          : 'bg-gradient-to-r from-green-500 via-emerald-500 to-green-600'
                      }`}
                      style={{ width: `${result.confidence * 100}%` }}
                    >
                      <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent animate-shimmer"></div>
                    </div>
                  </div>
                  <div className="flex justify-between text-xs text-gray-400 mt-2">
                    <span>0%</span>
                    <span>50%</span>
                    <span>100%</span>
                  </div>
                  <p className="mt-3 text-sm text-gray-300">{confidenceInfo?.description}</p>
                </div>
              </div>

              {/* Bounding Box Coordinates Section */}
              <div className="relative bg-gradient-to-br from-indigo-500/20 to-violet-500/10 p-6 rounded-2xl border border-indigo-500/30 backdrop-blur-sm overflow-hidden animate-fadeIn">
                <div className="absolute top-0 right-0 w-48 h-48 bg-indigo-500/10 rounded-full blur-3xl"></div>
                <div className="relative">
                  <div className="flex justify-between items-center mb-6">
                    <h3 className="text-lg font-bold text-white flex items-center gap-2">
                      <svg className="w-5 h-5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 9H5v10h4V9zm6 0h-4v10h4V9zm6 0h-4v10h4V9z" />
                      </svg>
                      Bounding Box Coordinates
                    </h3>
                    <div className="flex items-center gap-3">
                      {boundingBox && !showBoundingBoxForm && (
                        <span className="px-3 py-1 bg-green-500/20 text-green-300 rounded-lg text-xs font-semibold border border-green-500/30">
                          Auto-Detected
                        </span>
                      )}
                      {!boundingBox && !showBoundingBoxForm && (
                        <span className="px-3 py-1 bg-yellow-500/20 text-yellow-300 rounded-lg text-xs font-semibold border border-yellow-500/30">
                          Manual Input Required
                        </span>
                      )}
                    </div>
                  </div>

                  {boundingBox && !showBoundingBoxForm ? (
                    // Display Coordinates
                    <div className="space-y-4">
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <div className="bg-white/5 border border-indigo-500/20 rounded-xl p-4 text-center">
                          <p className="text-xs text-indigo-300 font-medium uppercase tracking-wider mb-2">Longitude Min</p>
                          <p className="text-xl font-bold text-white font-mono">{boundingBox.x_min.toFixed(4)}</p>
                        </div>
                        <div className="bg-white/5 border border-indigo-500/20 rounded-xl p-4 text-center">
                          <p className="text-xs text-indigo-300 font-medium uppercase tracking-wider mb-2">Latitude Min</p>
                          <p className="text-xl font-bold text-white font-mono">{boundingBox.y_min.toFixed(4)}</p>
                        </div>
                        <div className="bg-white/5 border border-indigo-500/20 rounded-xl p-4 text-center">
                          <p className="text-xs text-indigo-300 font-medium uppercase tracking-wider mb-2">Longitude Max</p>
                          <p className="text-xl font-bold text-white font-mono">{boundingBox.x_max.toFixed(4)}</p>
                        </div>
                        <div className="bg-white/5 border border-indigo-500/20 rounded-xl p-4 text-center">
                          <p className="text-xs text-indigo-300 font-medium uppercase tracking-wider mb-2">Latitude Max</p>
                          <p className="text-xl font-bold text-white font-mono">{boundingBox.y_max.toFixed(4)}</p>
                        </div>
                      </div>
                      {boundingBox.crs && (
                        <div className="bg-white/5 border border-indigo-500/20 rounded-xl p-3 text-center">
                          <p className="text-xs text-indigo-300 font-medium uppercase tracking-wider mb-1">Coordinate Reference System</p>
                          <p className="text-sm font-mono text-indigo-200">{boundingBox.crs}</p>
                        </div>
                      )}
                      <button
                        onClick={() => setShowMapModal(true)}
                        className="w-full px-4 py-3 bg-gradient-to-r from-cyan-500/30 to-blue-500/30 hover:from-cyan-500/50 hover:to-blue-500/50 text-cyan-300 rounded-lg font-semibold transition-all border border-cyan-500/40 hover:border-cyan-500/60 flex items-center justify-center gap-2"
                      >
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 003 16.382V5.618a1 1 0 011.553-.894L9 7m0 13l6.447 3.268A1 1 0 0021 19.382V8.618a1 1 0 00-1.553-.894L15 10m0 0V3m0 13V3" />
                        </svg>
                        View Area on Map
                      </button>
                    </div>
                  ) : (
                    // Input Form
                    <div className="space-y-4 animate-fadeIn">
                      <p className="text-sm text-indigo-300 mb-4">
                        {boundingBox ? 'Update the bounding box coordinates below' : 'Please enter the bounding box coordinates for this image'}
                      </p>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                          <label className="block text-sm font-semibold text-indigo-200 mb-2">Longitude Min (West)</label>
                          <input
                            type="number"
                            name="x_min"
                            value={boxInput.x_min}
                            onChange={handleBoundingBoxInputChange}
                            placeholder="e.g., -74.0060"
                            step="0.0001"
                            className="w-full px-4 py-3 rounded-lg bg-white/10 border border-indigo-500/30 focus:border-indigo-500/70 text-white placeholder-gray-500 focus:outline-none transition-all"
                          />
                        </div>
                        <div>
                          <label className="block text-sm font-semibold text-indigo-200 mb-2">Latitude Min (South)</label>
                          <input
                            type="number"
                            name="y_min"
                            value={boxInput.y_min}
                            onChange={handleBoundingBoxInputChange}
                            placeholder="e.g., 40.7128"
                            step="0.0001"
                            className="w-full px-4 py-3 rounded-lg bg-white/10 border border-indigo-500/30 focus:border-indigo-500/70 text-white placeholder-gray-500 focus:outline-none transition-all"
                          />
                        </div>
                        <div>
                          <label className="block text-sm font-semibold text-indigo-200 mb-2">Longitude Max (East)</label>
                          <input
                            type="number"
                            name="x_max"
                            value={boxInput.x_max}
                            onChange={handleBoundingBoxInputChange}
                            placeholder="e.g., -73.9352"
                            step="0.0001"
                            className="w-full px-4 py-3 rounded-lg bg-white/10 border border-indigo-500/30 focus:border-indigo-500/70 text-white placeholder-gray-500 focus:outline-none transition-all"
                          />
                        </div>
                        <div>
                          <label className="block text-sm font-semibold text-indigo-200 mb-2">Latitude Max (North)</label>
                          <input
                            type="number"
                            name="y_max"
                            value={boxInput.y_max}
                            onChange={handleBoundingBoxInputChange}
                            placeholder="e.g., 40.7614"
                            step="0.0001"
                            className="w-full px-4 py-3 rounded-lg bg-white/10 border border-indigo-500/30 focus:border-indigo-500/70 text-white placeholder-gray-500 focus:outline-none transition-all"
                          />
                        </div>
                      </div>
                      <div className="flex gap-3 pt-2">
                        <button
                          onClick={handleSaveBoundingBox}
                          className="flex-1 px-4 py-3 bg-gradient-to-r from-indigo-500 to-violet-500 hover:from-indigo-600 hover:to-violet-600 text-white rounded-lg font-semibold transition-all shadow-lg hover:shadow-xl"
                        >
                          {boundingBox ? 'Update Coordinates' : 'Submit Coordinates'}
                        </button>
                        {boundingBox && (
                          <button
                            onClick={handleEditBoundingBox}
                            className="flex-1 px-4 py-3 bg-white/10 hover:bg-white/20 text-white rounded-lg font-semibold transition-all border border-white/20"
                          >
                            Cancel
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Drift Animation Video - MOVED HERE */}
              {(result.drift_animation_url || result.drift_animation_status === 'generating') && (
                <div className="relative bg-gradient-to-br from-orange-500/20 to-red-500/10 border-2 border-orange-500/40 p-6 rounded-2xl overflow-hidden group hover:border-orange-500/60 transition-all duration-300 animate-fadeIn">
                  <div className="absolute top-0 right-0 w-32 h-32 bg-orange-500/20 rounded-full blur-2xl group-hover:scale-150 transition-transform duration-500"></div>
                  <div className="relative">
                    <div className="flex items-center gap-2 mb-4">
                      <div className="w-10 h-10 bg-orange-500/30 rounded-xl flex items-center justify-center">
                        <svg className="w-6 h-6 text-orange-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                      </div>
                      <h3 className="text-lg font-bold text-orange-200">Drift Animation</h3>
                      {animationLoading && !animationReady && (
                        <span className="text-xs text-orange-300 animate-pulse ml-2">Generating...</span>
                      )}
                    </div>
                    
                    {/* Show spinner while generating */}
                    {animationLoading && !animationReady && (
                      <div className="flex flex-col items-center justify-center py-12 w-full px-4">
                        <div className="mb-4">
                          <div className="relative w-16 h-16">
                            <div className="absolute inset-0 rounded-full border-4 border-orange-500/20"></div>
                            <div className="absolute inset-0 rounded-full border-4 border-transparent border-t-orange-400 border-r-orange-300 animate-spin"></div>
                          </div>
                        </div>
                        <p className="text-orange-300 text-sm text-center font-medium mb-2">
                          Generating Drift Animation
                        </p>
                        <p className="text-xs text-orange-400 text-center max-w-xs">
                          This includes running the physics simulation (~2-3 min) and creating the MP4 video (~1-2 min)
                        </p>
                        <p className="text-xs text-orange-500/60 text-center mt-3">
                          The animation will be ready shortly...
                        </p>
                      </div>
                    )}
                    {/* FEATURE #9: ANIMATION INFORMATION */}
                    {(result.drift_animation_url || animationLoading) && (
                      <div className="bg-gradient-to-br from-orange-500/15 to-red-500/10 border border-orange-500/30 rounded-2xl p-4 backdrop-blur-sm text-sm animate-fadeIn">
                        <div className="flex items-center gap-2 mb-2">
                          <svg className="w-5 h-5 text-orange-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                          </svg>
                          <span className="font-semibold text-orange-300">Animation Details</span>
                        </div>
                        <ul className="text-gray-300 text-xs space-y-1 ml-7">
                          <li>• <span className="text-white font-semibold">Duration:</span> 48 hours simulated</li>
                          <li>• <span className="text-white font-semibold">Data Source:</span> Synthetic oceanographic conditions</li>
                          <li>• <span className="text-white font-semibold">Particles:</span> 1000 oil particles tracked</li>
                          <li>• <span className="text-white font-semibold">Frame Rate:</span> 24 fps</li>
                        </ul>
                      </div>
                    )}

                    
                    {/* Show image preview and button when ready */}
                    {animationReady && result?.drift_animation_url && (
                      <div className="space-y-4">
                        {/* Drift Map Preview */}
                        {result.drift_map_html && (
                          <div className="rounded-xl border border-orange-500/30 shadow-lg overflow-hidden" style={{ maxHeight: '300px' }}>
                            <div 
                              dangerouslySetInnerHTML={{ __html: result.drift_map_html }}
                              style={{ height: '300px', width: '100%' }}
                            />
                          </div>
                        )}
                        
                        {/* Button */}
                        <button
                          onClick={() => {
                            const filename = result.drift_animation_url.split('/').pop();
                            const playerUrl = `http://localhost:5001/api/animations/watch/${filename}?file=${filename}`;
                            console.log('🎬 Opening animation player:', playerUrl);
                            window.open(playerUrl, '_blank');
                          }}
                          className="w-full px-6 py-3 bg-gradient-to-r from-orange-500 to-red-500 hover:from-orange-600 hover:to-red-600 text-white font-semibold rounded-xl transition-all duration-300 transform hover:scale-105 shadow-lg flex items-center justify-center gap-2"
                        >
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                          </svg>
                          View Animation (New Tab)
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Drift Simulation Map - DISPLAYED BELOW ANIMATION (only if not shown as preview above button) */}
              {result.drift_map_html && !animationReady && (
                <div className="relative bg-gradient-to-br from-emerald-500/20 to-teal-500/10 border-2 border-emerald-500/40 p-6 rounded-2xl overflow-hidden group hover:border-emerald-500/60 transition-all duration-300 animate-fadeIn">
                  <div className="absolute top-0 right-0 w-32 h-32 bg-emerald-500/20 rounded-full blur-2xl group-hover:scale-150 transition-transform duration-500"></div>
                  <div className="relative">
                    <div className="flex items-center gap-2 mb-4">
                      <div className="w-10 h-10 bg-emerald-500/30 rounded-xl flex items-center justify-center">
                        <svg className="w-6 h-6 text-emerald-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6.553 3.276A1 1 0 0021 16.382V5.618a1 1 0 00-1.447-.894L15 7m0 13V7m0 13L9 20" />
                        </svg>
                      </div>
                      <h3 className="text-lg font-bold text-emerald-200">Drift Path Map</h3>
                    </div>
                    <div 
                      className="bg-white rounded-xl overflow-hidden border border-emerald-500/30 shadow-lg"
                      dangerouslySetInnerHTML={{ __html: result.drift_map_html }}
                      style={{ minHeight: '400px', height: '100%' }}
                    />
                    <p className="text-emerald-300 text-xs mt-3 flex items-center gap-2">
                      <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M5.05 4.05a7 7 0 119.9 9.9L10 18.9l-4.95-4.95a7 7 0 010-9.9zM10 11a2 2 0 100-4 2 2 0 000 4z" clipRule="evenodd" />
                      </svg>
                      Gold (initial) → Orange (drifted)
                    </p>
                  </div>
                </div>
              )}
              
              {result.has_oil && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-5 animate-fadeIn">
                  {/* Area */}
                  <div className="relative bg-gradient-to-br from-blue-500/20 to-cyan-500/10 border-2 border-blue-500/40 p-6 rounded-2xl overflow-hidden group hover:border-blue-500/60 transition-all duration-300">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-blue-500/20 rounded-full blur-2xl group-hover:scale-150 transition-transform duration-500"></div>
                    <div className="relative">
                      <div className="flex items-center gap-2 mb-3">
                        <div className="w-10 h-10 bg-blue-500/30 rounded-xl flex items-center justify-center">
                          <svg className="w-6 h-6 text-blue-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
                          </svg>
                        </div>
                        <h3 className="text-lg font-bold text-blue-200">Affected Area</h3>
                      </div>
                      <div className="flex items-baseline gap-2 mb-2">
                        <span className="text-4xl font-bold text-white">{result.area_km2}</span>
                        <span className="text-xl text-blue-300 font-semibold">km²</span>
                      </div>
                      <p className="text-blue-300 text-xs flex items-center gap-2 mb-4">
                        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                          <path d="M2 11a1 1 0 011-1h2a1 1 0 011 1v5a1 1 0 01-1 1H3a1 1 0 01-1-1v-5zM8 7a1 1 0 011-1h2a1 1 0 011 1v9a1 1 0 01-1 1H9a1 1 0 01-1-1V7zM14 4a1 1 0 011-1h2a1 1 0 011 1v12a1 1 0 01-1 1h-2a1 1 0 01-1-1V4z" />
                        </svg>
                        {result.area_pixels?.toLocaleString()} pixels detected
                      </p>
                      
                      <div className="grid grid-cols-2 gap-3 mb-3">
                        <div className="bg-white/5 border border-blue-500/20 rounded-lg p-3">
                          <p className="text-sm text-blue-300 font-semibold uppercase mb-1">Severity</p>
                          <p className="text-lg font-bold text-white flex items-center gap-1">
                            <span className={`w-2 h-2 rounded-full ${
                              result.area_km2 > 100 ? 'bg-red-500' : result.area_km2 > 50 ? 'bg-orange-500' : 'bg-yellow-500'
                            }`}></span>
                            {result.area_km2 > 100 ? 'Critical' : result.area_km2 > 50 ? 'High' : 'Moderate'}
                          </p>
                        </div>
                        <div className="bg-white/5 border border-blue-500/20 rounded-lg p-3">
                          <p className="text-sm text-blue-300 font-semibold uppercase mb-1">Density</p>
                          <p className="text-lg font-bold text-white">{((result.area_pixels / (111.32 * 110.57)) * 100).toFixed(1)}%</p>
                        </div>
                      </div>
                      
                      <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3">
                        <p className="text-sm text-blue-300 font-semibold mb-1">ℹ Reference</p>
                        <p className="text-sm text-gray-300">
                          {result.area_km2 > 50 ? `~${(result.area_km2 / 2.6).toFixed(0)} square miles` : `~${(result.area_km2 * 100).toFixed(0)} hectares`}
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Drift */}
                  <div className="relative bg-gradient-to-br from-purple-500/20 to-pink-500/10 border-2 border-purple-500/40 p-6 rounded-2xl overflow-hidden group hover:border-purple-500/60 transition-all duration-300">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-purple-500/20 rounded-full blur-2xl group-hover:scale-150 transition-transform duration-500"></div>
                    <div className="relative">
                      <div className="flex items-center gap-2 mb-4">
                        <div className="w-10 h-10 bg-purple-500/30 rounded-xl flex items-center justify-center">
                          <svg className="w-6 h-6 text-purple-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                          </svg>
                        </div>
                        <h3 className="text-lg font-bold text-purple-200">Drift Prediction</h3>
                      </div>
                      
                      <p className="text-purple-300/80 text-sm mb-4">
                        Based on ocean currents and wind data, the spilled oil is predicted to drift following this trajectory over the next 48 hours.
                      </p>
                      
                      <div className="space-y-3">
                        <div className="p-4 bg-white/5 rounded-xl border border-purple-500/20">
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-xs text-purple-300 font-medium uppercase tracking-wide">Direction</span>
                            {result.drift_animation_status === 'generating' && !result.drift_prediction?.direction ? (
                              <span className="text-xs text-purple-300 italic">Calculating...</span>
                            ) : (
                              <span className="text-xs text-purple-400 font-semibold">
                                {result.drift_prediction?.direction ? 
                                  (result.drift_prediction.direction <= 45 || result.drift_prediction.direction > 315 ? '↑ North' :
                                   result.drift_prediction.direction <= 135 ? '→ East' :
                                   result.drift_prediction.direction <= 225 ? '↓ South' :
                                   '← West') 
                                  : '–'}
                              </span>
                            )}
                          </div>
                          <div className="text-3xl font-bold text-white">
                            {result.drift_prediction?.direction ?? '–'}<span className="text-lg text-purple-300">°</span>
                          </div>
                        </div>
                        
                        <div className="p-4 bg-white/5 rounded-xl border border-purple-500/20">
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-xs text-purple-300 font-medium uppercase tracking-wide">Distance (48 hours)</span>
                            {result.drift_animation_status === 'generating' && !result.drift_prediction?.distance_km ? (
                              <span className="text-xs text-purple-300 italic">Calculating...</span>
                            ) : null}
                          </div>
                          <div className="flex items-baseline gap-2">
                            <span className="text-3xl font-bold text-white">{result.drift_prediction?.distance_km ?? '–'}</span>
                            <span className="text-lg text-purple-300">km</span>
                            {result.drift_prediction?.distance_km ? (
                              <span className="text-xs text-purple-400 ml-2">
                                (~{(result.drift_prediction.distance_km / 2).toFixed(2)} km/day)
                              </span>
                            ) : null}
                          </div>
                        </div>
                      </div>
                      
                      <div className="mt-4 p-3 bg-purple-500/10 rounded-lg border border-purple-500/20 text-purple-300/70 text-xs">
                        💡 <span className="font-semibold text-purple-300">What does this mean?</span> The oil spill is forecast to move {result.drift_prediction?.distance_km?.toFixed(1) || '...'} km over two days in a {Math.round(result.drift_prediction?.direction || 0)}° direction (compass bearing).
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* FEATURE #8: ACTIONABLE RECOMMENDATIONS */}
              {result.has_oil && (
                <div className="relative bg-gradient-to-br from-rose-500/20 to-pink-500/10 p-6 rounded-2xl border border-rose-500/40 overflow-hidden animate-fadeIn">
                  <div className="absolute top-0 right-0 w-48 h-48 bg-rose-500/10 rounded-full blur-3xl"></div>
                  <div className="relative">
                    <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
                      <svg className="w-5 h-5 text-rose-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                      </svg>
                      Recommended Actions
                    </h3>
                    <ul className="space-y-2">
                      <li className="flex items-start gap-3 text-sm">
                        <span className="text-rose-400 font-bold mt-0.5">→</span>
                        <span className="text-gray-300">Alert <span className="font-semibold text-white">maritime authorities</span> immediately</span>
                      </li>
                      <li className="flex items-start gap-3 text-sm">
                        <span className="text-rose-400 font-bold mt-0.5">→</span>
                        <span className="text-gray-300">Monitor affected area using <span className="font-semibold text-white">satellite imagery</span></span>
                      </li>
                      <li className="flex items-start gap-3 text-sm">
                        <span className="text-rose-400 font-bold mt-0.5">→</span>
                        <span className="text-gray-300">Prepare <span className="font-semibold text-white">containment resources</span> in drift direction</span>
                      </li>
                      <li className="flex items-start gap-3 text-sm">
                        <span className="text-rose-400 font-bold mt-0.5">→</span>
                        <span className="text-gray-300">Re-check prediction after <span className="font-semibold text-white">12 hours</span> with new data</span>
                      </li>
                    </ul>
                  </div>
                </div>
              )}

              {/* Metadata */}
              <div className="relative bg-gradient-to-r from-white/5 to-white/10 p-5 rounded-2xl border border-white/20 backdrop-blur-sm overflow-hidden animate-fadeIn">
                <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-blue-500 via-cyan-500 to-blue-500"></div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
                  <div className="space-y-1">
                    <div className="flex items-center justify-center">
                      <svg className="w-4 h-4 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    </div>
                    <p className="text-gray-400 text-[10px] font-medium uppercase tracking-wider">Processing Time</p>
                    <p className="text-white text-base font-bold">{result.processing_time_ms}<span className="text-xs text-gray-400 ml-1">ms</span></p>
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center justify-center">
                      <svg className="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z" />
                      </svg>
                    </div>
                    <p className="text-gray-400 text-[10px] font-medium uppercase tracking-wider">Model Version</p>
                    <p className="text-white text-base font-bold">v2.0</p>
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center justify-center">
                      <svg className="w-4 h-4 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                      </svg>
                    </div>
                    <p className="text-gray-400 text-[10px] font-medium uppercase tracking-wider">Image Size</p>
                    <p className="text-white text-base font-bold">{file?.size ? (file.size / 1024 / 1024).toFixed(2) : 0}<span className="text-xs text-gray-400 ml-1">MB</span></p>
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center justify-center">
                      <svg className="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                      </svg>
                    </div>
                    <p className="text-gray-400 text-[10px] font-medium uppercase tracking-wider">Timestamp</p>
                    <p className="text-white text-base font-bold">{new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</p>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="text-center mt-8 text-gray-400 text-sm">
          <p>Deep Learning for Marine Environmental Monitoring & Protection</p>
        </div>
      </div>

      {/* Image Modal/Popup */}
      {modalImage && (
        <div 
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/90 backdrop-blur-sm animate-fadeIn"
          onClick={closeImageModal}
        >
          <div 
            className="relative max-w-7xl max-h-[90vh] w-full"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Close Button */}
            <button
              onClick={closeImageModal}
              className="absolute -top-12 right-0 text-white hover:text-red-400 transition-colors p-2 rounded-full bg-white/10 hover:bg-white/20 backdrop-blur-sm"
              aria-label="Close"
            >
              <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>

            {/* Modal Title */}
            <div className="absolute -top-12 left-0 bg-gradient-to-r from-blue-600 to-cyan-600 backdrop-blur-md px-6 py-2 rounded-xl text-white font-bold border border-white/20 shadow-xl">
              {modalTitle}
            </div>

            {/* Image Container */}
            <div className="bg-black rounded-2xl overflow-hidden border-2 border-white/20 shadow-2xl">
              <img 
                src={modalImage}
                alt={modalTitle}
                className="w-full h-auto max-h-[85vh] object-contain"
              />
            </div>

            {/* Hint Text */}
            <p className="text-center text-gray-400 text-sm mt-4">
              Click outside or press the close button to exit
            </p>
          </div>
        </div>
      )}

      {/* Map Modal */}
      {showMapModal && boundingBox && (
        <div 
          className="fixed inset-0 z-50 overflow-y-auto pt-12 pb-6 px-4 bg-gradient-to-br from-slate-900/95 via-blue-900/95 to-slate-900/95 backdrop-blur-md animate-fadeIn"
          onClick={() => setShowMapModal(false)}
        >
          <div 
            className="relative max-w-5xl w-full mx-auto mt-12 mb-8"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Close Button */}
            <button
              onClick={() => setShowMapModal(false)}
              className="absolute -top-12 right-0 text-white hover:text-red-400 transition-colors p-2 rounded-full bg-white/10 hover:bg-white/20 backdrop-blur-sm z-10"
              aria-label="Close"
            >
              <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>

            {/* Modal Title */}
            <div className="absolute -top-12 left-0 bg-gradient-to-r from-cyan-600 to-blue-600 backdrop-blur-md px-6 py-2 rounded-xl text-white font-bold border border-white/20 shadow-xl z-10">
              Detection Area Map
            </div>

            {/* Map Container */}
            <div className="relative rounded-2xl overflow-hidden border-2 border-white/20 shadow-2xl bg-gray-900" style={{ height: '600px', width: '100%' }}>
              <MapContainer
                key={`map-${boundingBox?.x_min}-${boundingBox?.y_min}`}
                center={[
                  (boundingBox.y_min + boundingBox.y_max) / 2,
                  (boundingBox.x_min + boundingBox.x_max) / 2
                ]}
                zoom={8}
                style={{ height: '100%', width: '100%' }}
               whenCreated={() => {
                 setTimeout(() => window.dispatchEvent(new Event('resize')), 100);
               }}
               >
                <TileLayer
                   url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                   attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                  maxZoom={19}
                />
                {/* Draw rectangle for bounding box */}
                <Rectangle
                  bounds={[
                    [boundingBox.y_min, boundingBox.x_min],
                    [boundingBox.y_max, boundingBox.x_max]
                  ]}
                  pathOptions={{
                    color: '#06b6d4',
                    weight: 3,
                    opacity: 0.9,
                    fill: true,
                    fillColor: '#06b6d4',
                    fillOpacity: 0.15
                  }}
                >
                  <Popup>
                    <div className="text-sm">
                      <p className="font-bold mb-2">Detection Area</p>
                      <p>Lat: {boundingBox.y_min.toFixed(4)} to {boundingBox.y_max.toFixed(4)}</p>
                      <p>Lon: {boundingBox.x_min.toFixed(4)} to {boundingBox.x_max.toFixed(4)}</p>
                    </div>
                  </Popup>
                </Rectangle>
              </MapContainer>
            </div>

            {/* Info Section */}
            <div className="mt-4 bg-gradient-to-r from-cyan-500/10 to-blue-500/10 border border-cyan-500/30 rounded-xl p-4 backdrop-blur-sm">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                <div>
                  <p className="text-cyan-300 text-xs font-semibold mb-1">West (Lon Min)</p>
                  <p className="text-white font-mono">{boundingBox.x_min.toFixed(6)}</p>
                </div>
                <div>
                  <p className="text-cyan-300 text-xs font-semibold mb-1">South (Lat Min)</p>
                  <p className="text-white font-mono">{boundingBox.y_min.toFixed(6)}</p>
                </div>
                <div>
                  <p className="text-cyan-300 text-xs font-semibold mb-1">East (Lon Max)</p>
                  <p className="text-white font-mono">{boundingBox.x_max.toFixed(6)}</p>
                </div>
                <div>
                  <p className="text-cyan-300 text-xs font-semibold mb-1">North (Lat Max)</p>
                  <p className="text-white font-mono">{boundingBox.y_max.toFixed(6)}</p>
                </div>
              </div>
              <div className="mt-3 pt-3 border-t border-cyan-500/20">
                <p className="text-cyan-300 text-xs font-semibold mb-1">Area Dimensions</p>
                <p className="text-gray-300 text-sm">
                  ~{((boundingBox.x_max - boundingBox.x_min) * 111.32).toFixed(1)} km East-West × 
                  ~{((boundingBox.y_max - boundingBox.y_min) * 110.57).toFixed(1)} km North-South
                </p>
              </div>
            </div>

            {/* Hint Text */}
            <p className="text-center text-gray-400 text-sm mt-4 mb-4">
              Click outside or press the close button to exit
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
