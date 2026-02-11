import { useState } from 'react';
import './App.css';

function App() {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const handleFileChange = (e) => {
    const selectedFile = e.target.files[0];
    if (selectedFile) {
      setFile(selectedFile);
      setError(null);
      setResult(null);
      
      const reader = new FileReader();
      reader.onloadend = () => {
        setPreview(reader.result);
      };
      reader.readAsDataURL(selectedFile);
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
      } else {
        setError(data.error || 'An error occurred');
      }
    } catch (err) {
      setError('Failed to connect to server. Make sure backend is running on port 5001.');
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setFile(null);
    setPreview(null);
    setResult(null);
    setError(null);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-blue-900 to-slate-900 py-12 px-4">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="text-center mb-12">
          <h1 className="text-5xl font-bold bg-gradient-to-r from-blue-400 to-cyan-400 bg-clip-text text-transparent mb-4">
            SAR Oil Spill Detection
          </h1>
          <p className="text-xl text-gray-300">AI-Powered Marine Environmental Monitoring</p>
          <p className="text-gray-400 mt-2">Final Year Project 2026</p>
        </div>

        {/* Main Card */}
        <div className="bg-white/5 backdrop-blur-md border border-white/10 rounded-2xl shadow-2xl p-8">
          {!result ? (
            /* Upload Form */
            <form onSubmit={handleSubmit} className="space-y-6">
              {/* File Upload */}
              <div className="border-2 border-dashed border-blue-400/30 rounded-xl p-12 text-center hover:border-blue-400/60 transition-all cursor-pointer group">
                <input
                  type="file"
                  onChange={handleFileChange}
                  accept="image/*"
                  className="hidden"
                  id="file-upload"
                />
                <label htmlFor="file-upload" className="cursor-pointer">
                  <div className="flex flex-col items-center">
                    <svg className="w-16 h-16 text-blue-400 mb-4 group-hover:scale-110 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                    </svg>
                    <span className="text-xl font-semibold text-white mb-2">
                      {file ? file.name : 'Click to upload SAR image'}
                    </span>
                    <span className="text-sm text-gray-400">PNG, JPG, or TIFF • Max 50MB</span>
                  </div>
                </label>
              </div>

              {/* Image Preview */}
              {preview && (
                <div className="animate-fadeIn">
                  <h3 className="text-lg font-semibold text-white mb-3">Preview</h3>
                  <img src={preview} alt="Preview" className="w-full rounded-xl border border-white/10" />
                </div>
              )}

              {/* Error Message */}
              {error && (
                <div className="bg-red-500/10 border border-red-500/50 p-4 rounded-xl">
                  <p className="text-red-300">{error}</p>
                </div>
              )}

              {/* Submit Button */}
              <button
                type="submit"
                disabled={!file || loading}
                className="w-full bg-gradient-to-r from-blue-500 to-cyan-500 text-white py-4 px-8 rounded-xl font-bold text-lg hover:from-blue-600 hover:to-cyan-600 disabled:from-gray-600 disabled:to-gray-700 disabled:cursor-not-allowed transition-all shadow-lg"
              >
                {loading ? (
                  <span className="flex items-center justify-center gap-3">
                    <svg className="animate-spin h-6 w-6" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                    Analyzing...
                  </span>
                ) : (
                  'Analyze Image'
                )}
              </button>
            </form>
          ) : (
            /* Results Display */
            <div className="space-y-6 animate-fadeIn">
              {/* Header with Reset Button */}
              <div className="flex justify-between items-center mb-6">
                <h2 className="text-2xl font-bold text-white">Analysis Results</h2>
                <button onClick={handleReset} className="px-6 py-2 bg-white/10 hover:bg-white/20 text-white rounded-lg transition-all">
                  New Analysis
                </button>
              </div>

              {/* Main Status Card */}
              <div className={`p-6 rounded-xl border-2 ${result.has_oil ? 'bg-red-500/20 border-red-500/50' : 'bg-green-500/20 border-green-500/50'}`}>
                <div className="flex items-center gap-4">
                  {result.has_oil ? (
                    <svg className="w-16 h-16 text-red-400" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd"/>
                    </svg>
                  ) : (
                    <svg className="w-16 h-16 text-green-400" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd"/>
                    </svg>
                  )}
                  <div>
                    <h3 className={`text-3xl font-bold ${result.has_oil ? 'text-red-200' : 'text-green-200'}`}>
                      {result.has_oil ? 'Oil Spill Detected' : 'No Oil Detected'}
                    </h3>
                    <p className={`text-lg ${result.has_oil ? 'text-red-300' : 'text-green-300'}`}>
                      {result.has_oil ? 'Environmental response required' : 'Area is clear and safe'}
                    </p>
                  </div>
                </div>
              </div>

              {/* Confidence Score */}
              <div className="bg-white/5 p-6 rounded-xl border border-white/10">
                <div className="flex justify-between items-center mb-3">
                  <h3 className="text-xl font-semibold text-white">Confidence</h3>
                  <span className="text-3xl font-bold text-cyan-400">{(result.confidence * 100).toFixed(2)}%</span>
                </div>
                <div className="h-4 bg-gray-700/50 rounded-full overflow-hidden">
                  <div
                    className={`h-full transition-all duration-1000 ${result.has_oil ? 'bg-gradient-to-r from-red-500 to-orange-500' : 'bg-gradient-to-r from-green-500 to-emerald-500'}`}
                    style={{ width: `${result.confidence * 100}%` }}
                  />
                </div>
              </div>

              {/* Oil Detection Details */}
              {result.has_oil && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Area */}
                  <div className="bg-blue-500/10 border border-blue-500/30 p-6 rounded-xl">
                    <h3 className="text-lg font-semibold text-blue-200 mb-2">Affected Area</h3>
                    <div className="flex items-baseline gap-2">
                      <span className="text-4xl font-bold text-white">{result.area_km2}</span>
                      <span className="text-xl text-blue-300">km²</span>
                    </div>
                    <p className="text-blue-300 text-sm mt-1">{result.area_pixels?.toLocaleString()} pixels</p>
                  </div>

                  {/* Drift */}
                  <div className="bg-purple-500/10 border border-purple-500/30 p-6 rounded-xl">
                    <h3 className="text-lg font-semibold text-purple-200 mb-2">Drift Prediction</h3>
                    <div className="space-y-2">
                      <div>
                        <span className="text-sm text-purple-300">Direction: </span>
                        <span className="text-2xl font-bold text-white">{result.drift_prediction?.direction}°</span>
                      </div>
                      <div>
                        <span className="text-sm text-purple-300">Distance (24h): </span>
                        <span className="text-2xl font-bold text-white">{result.drift_prediction?.distance_km} km</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Metadata */}
              <div className="bg-white/5 p-4 rounded-xl border border-white/10">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-center text-sm">
                  <div>
                    <p className="text-gray-400 mb-1">Processing Time</p>
                    <p className="text-white font-bold">{result.processing_time_ms}ms</p>
                  </div>
                  <div>
                    <p className="text-gray-400 mb-1">Model Version</p>
                    <p className="text-white font-bold">v2.0</p>
                  </div>
                  <div>
                    <p className="text-gray-400 mb-1">Image Size</p>
                    <p className="text-white font-bold">{file?.size ? (file.size / 1024 / 1024).toFixed(2) : 0} MB</p>
                  </div>
                  <div>
                    <p className="text-gray-400 mb-1">Timestamp</p>
                    <p className="text-white font-bold">{new Date().toLocaleTimeString()}</p>
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
    </div>
  );
}

export default App;
