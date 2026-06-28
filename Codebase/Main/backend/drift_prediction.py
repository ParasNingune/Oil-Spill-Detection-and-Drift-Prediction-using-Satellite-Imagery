import os
import numpy as np
import io
from datetime import datetime, timedelta
import traceback
import base64

try:
    from scipy.spatial import ConvexHull, QhullError
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

try:
    import copernicusmarine
    COPERNICUSMARINE_AVAILABLE = True
except ImportError:
    COPERNICUSMARINE_AVAILABLE = False

try:
    from opendrift.models.oceandrift import OceanDrift
    from opendrift.readers.reader_netCDF_CF_generic import Reader
    OPENDRIFT_AVAILABLE = True
except ImportError:
    OPENDRIFT_AVAILABLE = False

try:
    import folium
    FOLIUM_AVAILABLE = True
except ImportError:
    FOLIUM_AVAILABLE = False

try:
    import rasterio
    from rasterio.transform import xy
    RASTERIO_AVAILABLE = True
except ImportError:
    RASTERIO_AVAILABLE = False

try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

try:
    import netCDF4 as nc
    NETCDF4_AVAILABLE = True
except ImportError:
    NETCDF4_AVAILABLE = False


# ============================================================================
# CONFIGURATION
# ============================================================================

DRIFT_SIMULATION_DURATION_HOURS = 24  # How long to simulate drift (hours)
DRIFT_TIME_STEP = 900  # Time step for simulation (seconds)
NUM_DRIFT_PARTICLES = 300  # Number of particles to seed (optimized)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def generate_synthetic_data_for_bbox(min_lon, max_lon, min_lat, max_lat, start_date, num_days=25, 
                                     currents_filename="currents.nc", wind_filename="wind.nc"):
    """
    Generate synthetic ocean current and wind data for a specific bounding box and time range.
    This avoids the need for Copernicus API calls while providing realistic drift simulation data.
    
    Args:
        min_lon, max_lon: Longitude bounds
        min_lat, max_lat: Latitude bounds
        start_date: Start date (datetime or string 'YYYY-MM-DD')
        num_days: Number of daily samples to generate (default 25)
        currents_filename: Output filename for currents data
        wind_filename: Output filename for wind data
    
    Returns:
        Tuple (currents_file, wind_file) with full paths or (None, None) if generation fails
    """
    try:
        if not NETCDF4_AVAILABLE:
            print("[DRIFT] ⚠️ netCDF4 not available - cannot generate synthetic data")
            return None, None
        
        # Parse start date if string
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d')
        
        print(f"[DRIFT] 🔄 Generating synthetic oceanographic data for bbox...")
        print(f"[DRIFT]    Region: lon [{min_lon:.2f}, {max_lon:.2f}], lat [{min_lat:.2f}, {max_lat:.2f}]")
        print(f"[DRIFT]    Time: {start_date.strftime('%Y-%m-%d')} for {num_days} days")
        
        # Create coordinate arrays
        grid_density = max(10, min(50, int((max_lon - min_lon) * 10)))  # Adaptive grid density
        lons = np.linspace(min_lon, max_lon, grid_density)
        lats = np.linspace(min_lat, max_lat, grid_density)
        
        # Create time array
        times = np.array([(start_date + timedelta(days=i)).timestamp() for i in range(num_days)])
        
        # ===== Generate synthetic currents data =====
        print(f"[DRIFT]    Generating currents ({grid_density}x{grid_density} grid)...")
        
        currents_file = nc.Dataset(currents_filename, 'w', format='NETCDF4')
        
        # Create dimensions
        currents_file.createDimension('time', len(times))
        currents_file.createDimension('lat', len(lats))
        currents_file.createDimension('lon', len(lons))
        
        # Create coordinate variables
        times_var = currents_file.createVariable('time', 'f8', ('time',))
        lats_var = currents_file.createVariable('lat', 'f4', ('lat',))
        lons_var = currents_file.createVariable('lon', 'f4', ('lon',))
        
        times_var.units = 'seconds since 1970-01-01 00:00:00'
        times_var.calendar = 'gregorian'
        lats_var.units = 'degrees_north'
        lons_var.units = 'degrees_east'
        
        times_var[:] = times
        lats_var[:] = lats
        lons_var[:] = lons
        
        # Generate synthetic current data with realistic patterns
        # Typical ocean currents: 0.1-0.5 m/s eastward, -0.2 to 0.2 m/s northward
        uo_data = np.random.normal(0.2, 0.1, (len(times), len(lats), len(lons))).astype(np.float32)
        vo_data = np.random.normal(-0.15, 0.08, (len(times), len(lats), len(lons))).astype(np.float32)
        
        # Add spatial structure for realism
        for i in range(len(lons)):
            for j in range(len(lats)):
                # Normalize coordinates to 0-1
                norm_lon = (lons[i] - min_lon) / (max_lon - min_lon) if max_lon > min_lon else 0.5
                norm_lat = (lats[j] - min_lat) / (max_lat - min_lat) if max_lat > min_lat else 0.5
                
                # Add sinusoidal spatial variation
                lon_factor = np.sin(norm_lon * 2 * np.pi) * 0.1
                lat_factor = np.cos(norm_lat * 2 * np.pi) * 0.08
                uo_data[:, j, i] += lon_factor
                vo_data[:, j, i] += lat_factor
        
        # Create data variables
        uo_var = currents_file.createVariable('uo', 'f4', ('time', 'lat', 'lon'))
        vo_var = currents_file.createVariable('vo', 'f4', ('time', 'lat', 'lon'))
        
        uo_var.units = 'm s-1'
        uo_var.long_name = 'Eastward sea water velocity'
        uo_var.standard_name = 'eastward_sea_water_velocity'
        
        vo_var.units = 'm s-1'
        vo_var.long_name = 'Northward sea water velocity'
        vo_var.standard_name = 'northward_sea_water_velocity'
        
        uo_var[:] = uo_data
        vo_var[:] = vo_data
        
        # Add metadata
        currents_file.Conventions = 'CF-1.6'
        currents_file.title = 'Synthetic ocean current data'
        currents_file.source = 'Generated by oil spill drift simulation system'
        currents_file.history = f'Created for region [{min_lon:.2f}, {max_lon:.2f}] x [{min_lat:.2f}, {max_lat:.2f}]'
        
        currents_file.close()
        print(f"[DRIFT] ✓ Synthetic currents generated: {currents_filename}")
        
        # ===== Generate synthetic wind data =====
        print(f"[DRIFT]    Generating wind data ({grid_density}x{grid_density} grid)...")
        
        wind_file = nc.Dataset(wind_filename, 'w', format='NETCDF4')
        
        # Create dimensions
        wind_file.createDimension('time', len(times))
        wind_file.createDimension('lat', len(lats))
        wind_file.createDimension('lon', len(lons))
        
        # Create coordinate variables
        times_var = wind_file.createVariable('time', 'f8', ('time',))
        lats_var = wind_file.createVariable('lat', 'f4', ('lat',))
        lons_var = wind_file.createVariable('lon', 'f4', ('lon',))
        
        times_var.units = 'seconds since 1970-01-01 00:00:00'
        times_var.calendar = 'gregorian'
        lats_var.units = 'degrees_north'
        lons_var.units = 'degrees_east'
        
        times_var[:] = times
        lats_var[:] = lats
        lons_var[:] = lons
        
        # Generate synthetic wind data with realistic values
        # Typical wind: 2-10 m/s total speed
        eastward_wind_data = np.random.normal(3.5, 2.0, (len(times), len(lats), len(lons))).astype(np.float32)
        northward_wind_data = np.random.normal(2.0, 1.5, (len(times), len(lats), len(lons))).astype(np.float32)
        
        # Add temporal variation (wind patterns change)
        for t in range(len(times)):
            time_factor = np.sin(t / len(times) * 2 * np.pi) * 1.5
            eastward_wind_data[t, :, :] += time_factor
            northward_wind_data[t, :, :] += time_factor * 0.7
        
        # Create data variables
        eastward_wind_var = wind_file.createVariable('eastward_wind', 'f4', ('time', 'lat', 'lon'))
        northward_wind_var = wind_file.createVariable('northward_wind', 'f4', ('time', 'lat', 'lon'))
        
        eastward_wind_var.units = 'm s-1'
        eastward_wind_var.long_name = 'Eastward wind component'
        eastward_wind_var.standard_name = 'eastward_wind'
        
        northward_wind_var.units = 'm s-1'
        northward_wind_var.long_name = 'Northward wind component'
        northward_wind_var.standard_name = 'northward_wind'
        
        eastward_wind_var[:] = eastward_wind_data
        northward_wind_var[:] = northward_wind_data
        
        # Add metadata
        wind_file.Conventions = 'CF-1.6'
        wind_file.title = 'Synthetic wind data'
        wind_file.source = 'Generated by oil spill drift simulation system'
        wind_file.history = f'Created for region [{min_lon:.2f}, {max_lon:.2f}] x [{min_lat:.2f}, {max_lat:.2f}]'
        
        wind_file.close()
        print(f"[DRIFT] ✓ Synthetic wind data generated: {wind_filename}")
        
        return currents_filename, wind_filename
    
    except Exception as e:
        print(f"[DRIFT] ❌ Error generating synthetic data: {e}")
        traceback.print_exc()
        return None, None


def safe_hull(points):
    """
    Compute convex hull of point cloud, fallback to raw points if hull fails
    
    Args:
        points: Nx2 array of (lon, lat) coordinates
    
    Returns:
        Array of hull vertices or raw points
    """
    try:
        if not SCIPY_AVAILABLE:
            return points
        
        if len(points) < 3:
            return points
        
        # Remove duplicate points for hull computation
        unique_points = np.unique(points, axis=0)
        
        if len(unique_points) < 3:
            return points
        
        hull = ConvexHull(unique_points)
        return unique_points[hull.vertices]
    
    except QhullError as e:
        print(f"⚠️ Convex hull computation failed: {e}")
        print(f"   Falling back to raw points ({len(points)} points)")
        return points
    except Exception as e:
        print(f"⚠️ Unexpected error in hull computation: {e}")
        return points


def setup_drift_environment(spill_pixels, start_time, end_time, copernicus_username=None, copernicus_password=None):
    """
    Set up OpenDrift environment with local data files or synthetically generated data
    
    Args:
        spill_pixels: Nx2 array of (lon, lat) oil spill coordinates
        start_time: Start datetime (str 'YYYY-MM-DD' or datetime object)
        end_time: End datetime (str 'YYYY-MM-DD' or datetime object)
    
    Returns:
        OceanDrift object configured with readers, or None if setup fails
    
    Data Strategy:
        1. Checks for local currents.nc and wind.nc files
        2. If local files not found, generates synthetic oceanographic data for the specific bounding box
        3. No external API calls required
    """
    try:
        if not OPENDRIFT_AVAILABLE:
            print("❌ OpenDrift not available")
            return None
        
        print("\n[DRIFT] Setting up OpenDrift environment...")
        
        # Convert datetime objects to strings if needed
        if isinstance(start_time, datetime):
            start_time = start_time.strftime('%Y-%m-%d')
        if isinstance(end_time, datetime):
            end_time = end_time.strftime('%Y-%m-%d')
        
        # Step 1: Compute bounding box with buffer
        min_lon = float(np.min(spill_pixels[:, 0])) - 0.5
        max_lon = float(np.max(spill_pixels[:, 0])) + 0.5
        min_lat = float(np.min(spill_pixels[:, 1])) - 0.5
        max_lat = float(np.max(spill_pixels[:, 1])) + 0.5
        
        print(f"[DRIFT] Region: lon [{min_lon:.2f}, {max_lon:.2f}], lat [{min_lat:.2f}, {max_lat:.2f}]")
        print(f"[DRIFT] Time: {start_time} to {end_time}")
        
        # Step 2: Check for existing local data files
        print(f"[DRIFT] Checking for existing data files...")
        currents_file = None
        wind_file = None
        
        # Look for currents data
        possible_currents_paths = [
            "currents.nc",
            "data/currents.nc",
            "datasets/currents.nc",
            "../data/currents.nc",
            "../../data/currents.nc"
        ]
        
        for path in possible_currents_paths:
            if os.path.exists(path):
                currents_file = path
                print(f"[DRIFT] ✓ Found existing currents data: {currents_file}")
                break
        
        # Look for wind data
        possible_wind_paths = [
            "wind.nc",
            "data/wind.nc",
            "datasets/wind.nc",
            "../data/wind.nc",
            "../../data/wind.nc"
        ]
        
        for path in possible_wind_paths:
            if os.path.exists(path):
                wind_file = path
                print(f"[DRIFT] ✓ Found existing wind data: {wind_file}")
                break
        
        # Step 3: If local files not found, generate synthetic data for the specific bbox
        if currents_file is None:
            print(f"[DRIFT] No local currents data found. Generating synthetic data for this region...")
            synth_currents, synth_wind = generate_synthetic_data_for_bbox(
                min_lon, max_lon, min_lat, max_lat,
                start_time,
                num_days=25,
                currents_filename="currents_synthetic.nc",
                wind_filename="wind_synthetic.nc"
            )
            
            if synth_currents is not None:
                currents_file = synth_currents
                print(f"[DRIFT] ✓ Using synthetically generated currents data")
            else:
                print(f"[DRIFT] ❌ Failed to generate synthetic currents data")
                return None
            
            # If wind file also not found, use the generated synthetic wind
            if wind_file is None and synth_wind is not None:
                wind_file = synth_wind
                print(f"[DRIFT] ✓ Using synthetically generated wind data")
        
        # If we still don't have wind file, try to generate it separately
        if wind_file is None:
            print(f"[DRIFT] No wind data found. Generating synthetic wind data...")
            _, synth_wind = generate_synthetic_data_for_bbox(
                min_lon, max_lon, min_lat, max_lat,
                start_time,
                num_days=25,
                currents_filename="dummy.nc",  # Won't be used
                wind_filename="wind_synthetic.nc"
            )
            if synth_wind is not None:
                wind_file = synth_wind
                print(f"[DRIFT] ✓ Using synthetically generated wind data")
        
        # Step 4: Set up OpenDrift
        print(f"[DRIFT] Initializing OpenDrift...")
        o = OceanDrift(loglevel=20)
        
        # Add currents reader
        try:
            print(f"[DRIFT] Adding currents reader from: {currents_file}")
            reader_currents = Reader(currents_file)
            o.add_reader(reader_currents)
            print(f"[DRIFT] ✓ Currents reader added")
        except Exception as e:
            print(f"[DRIFT] ❌ Failed to add currents reader: {e}")
            return None
        
        # Add wind reader (if available)
        if wind_file is not None and os.path.exists(wind_file):
            try:
                print(f"[DRIFT] Adding wind reader from: {wind_file}")
                reader_wind = Reader(
                    wind_file,
                    standard_name_mapping={
                        'eastward_wind': 'x_wind',
                        'northward_wind': 'y_wind'
                    }
                )
                o.add_reader(reader_wind)
                print(f"[DRIFT] ✓ Wind reader added")
            except Exception as e:
                print(f"[DRIFT] ⚠️ Failed to add wind reader: {e}")
                print(f"[DRIFT] Proceeding with currents only")
        else:
            print(f"[DRIFT] ℹ️ No wind data available - using currents only")
        
        # Step 5: Configure physics
        o.set_config('drift:vertical_mixing', True)
        o.set_config('drift:horizontal_diffusivity', 10)
        
        print(f"[DRIFT] ✓ OpenDrift environment ready")
        return o
    
    except Exception as e:
        print(f"[DRIFT] ❌ Error setting up drift environment: {e}")
        traceback.print_exc()
        return None


def extract_spill_coordinates(file_bytes, mask):
    """
    Extract geo-referenced oil spill coordinates from mask
    
    Args:
        file_bytes: TIFF file content as bytes
        mask: Binary mask array (must be same shape as TIFF image)
    
    Returns:
        Nx2 array of (lon, lat) coordinates for oil pixels
    """
    try:
        if not RASTERIO_AVAILABLE:
            print("❌ Rasterio not available")
            return None
        
        # Load geotransform from TIFF
        with rasterio.open(io.BytesIO(file_bytes)) as src:
            transform = src.transform
        
        # Get pixel coordinates of oil pixels
        rows, cols = np.where(mask > 0)
        
        # Convert pixel coordinates to geo coordinates
        spill_pixels = np.array([
            xy(transform, r, c)
            for r, c in zip(rows, cols)
        ])  # Shape: (N, 2) with columns [lon, lat]
        
        print(f"[DRIFT] ✓ Extracted {len(spill_pixels)} geo-referenced oil pixels")
        
        if len(spill_pixels) > 0:
            print(f"[DRIFT]   Lon range: {spill_pixels[:, 0].min():.4f} to {spill_pixels[:, 0].max():.4f}")
            print(f"[DRIFT]   Lat range: {spill_pixels[:, 1].min():.4f} to {spill_pixels[:, 1].max():.4f}")
        
        return spill_pixels
    
    except Exception as e:
        print(f"[DRIFT] ❌ Error extracting spill coordinates: {e}")
        traceback.print_exc()
        return None


def run_drift_simulation(file_bytes, mask, start_time, end_time, 
                        num_particles=NUM_DRIFT_PARTICLES,
                        copernicus_username=None, copernicus_password=None):
    """
    Run complete drift simulation for oil spill
    
    Args:
        file_bytes: TIFF file as bytes
        mask: Binary oil mask array
        start_time: Simulation start time (datetime or 'YYYY-MM-DD')
        end_time: Simulation end time (datetime or 'YYYY-MM-DD')
        num_particles: Number of particles to seed
        copernicus_username: Copernicus credentials
        copernicus_password: Copernicus credentials
    
    Returns:
        Dictionary with drift results or None if simulation fails
    """
    try:
        if not OPENDRIFT_AVAILABLE:
            print("❌ OpenDrift not available")
            return None
        
        print("\n" + "="*70)
        print("🌊 STARTING DRIFT SIMULATION")
        print("="*70)
        
        # Step 1: Extract oil coordinates
        spill_pixels = extract_spill_coordinates(file_bytes, mask)
        if spill_pixels is None or len(spill_pixels) == 0:
            print("[DRIFT] ❌ No oil pixels found in mask")
            return None
        
        # Step 2: Set up environment
        o = setup_drift_environment(
            spill_pixels, start_time, end_time,
            copernicus_username, copernicus_password
        )
        if o is None:
            print("[DRIFT] ❌ Failed to set up drift environment")
            return None
        
        # Step 3: Sample particles
        if len(spill_pixels) > num_particles:
            indices = np.random.choice(len(spill_pixels), num_particles, replace=False)
            sampled = spill_pixels[indices]
        else:
            sampled = spill_pixels
        
        lons = sampled[:, 0]
        lats = sampled[:, 1]
        print(f"[DRIFT] Seeding {len(lons)} particles for drift simulation")
        
        # Step 4: Run simulation
        if isinstance(start_time, str):
            start_time = datetime.strptime(start_time, '%Y-%m-%d')
        
        print(f"[DRIFT] Running drift simulation...")
        o.seed_elements(lon=lons, lat=lats, time=start_time)
        o.run(
            duration=timedelta(hours=DRIFT_SIMULATION_DURATION_HOURS),
            time_step=DRIFT_TIME_STEP
        )
        
        print(f"[DRIFT] ✓ Drift simulation completed")
        
        # Step 5: Extract results
        lon = o.result.lon.values
        lat = o.result.lat.values
        
        lon_start = lon[0]
        lat_start = lat[0]
        lon_end = lon[-1]
        lat_end = lat[-1]
        
        # Compute convex hulls
        points_start = np.column_stack((lon_start, lat_start))
        hull_points_start = safe_hull(points_start)
        
        points_end = np.column_stack((lon_end, lat_end))
        hull_points_end = safe_hull(points_end)
        
        # Compute centroids
        cx_start = np.mean(lon_start)
        cy_start = np.mean(lat_start)
        cx_end = np.mean(lon_end)
        cy_end = np.mean(lat_end)
        
        # Compute drift metrics
        drift_distance = np.sqrt((cx_end - cx_start)**2 + (cy_end - cy_start)**2) * 111.32  # km/degree
        drift_direction = np.degrees(np.arctan2(cy_end - cy_start, cx_end - cx_start))
        drift_direction = (drift_direction + 360) % 360  # Normalize to 0-360
        
        results = {
            'success': True,
            'initial_center': {'lon': float(cx_start), 'lat': float(cy_start)},
            'final_center': {'lon': float(cx_end), 'lat': float(cy_end)},
            'drift_distance_km': float(np.round(drift_distance, 2)),
            'drift_direction_degrees': float(np.round(drift_direction, 1)),
            'initial_hull': hull_points_start.tolist() if hull_points_start is not None else None,
            'final_hull': hull_points_end.tolist() if hull_points_end is not None else None,
            'opendrift_object': o,  # Store for animation generation
            'num_particles': len(lons),
            'simulation_duration_hours': DRIFT_SIMULATION_DURATION_HOURS
        }
        
        print(f"[DRIFT] ✓ Drift distance: {drift_distance:.2f} km")
        print(f"[DRIFT] ✓ Drift direction: {drift_direction:.1f}°")
        print("="*70 + "\n")
        
        return results
    
    except Exception as e:
        print(f"[DRIFT] ❌ Error during drift simulation: {e}")
        traceback.print_exc()
        return None


def create_drift_map_html(drift_results):
    """
    Create interactive Folium map visualization
    
    Args:
        drift_results: Dictionary from run_drift_simulation()
    
    Returns:
        HTML string of map or None if creation fails
    """
    try:
        if not FOLIUM_AVAILABLE or drift_results is None:
            return None
        
        initial = drift_results['initial_center']
        final = drift_results['final_center']
        hull_start = drift_results['initial_hull']
        hull_end = drift_results['final_hull']
        
        # Create map centered on initial position
        m = folium.Map(
            location=[initial['lat'], initial['lon']],
            zoom_start=8,
            tiles="OpenStreetMap"
        )
        
        # Initial oil polygon (gold)
        if hull_start:
            folium.Polygon(
                locations=[(lat, lon) for lon, lat in hull_start],
                color='gold',
                fill=True,
                fill_opacity=0.6,
                popup="Initial Oil Spill",
                tooltip="Initial position"
            ).add_to(m)
        
        # Final oil polygon (orange)
        if hull_end:
            folium.Polygon(
                locations=[(lat, lon) for lon, lat in hull_end],
                color='orange',
                fill=True,
                fill_opacity=0.6,
                popup="Drifted Oil Spill",
                tooltip="Final position"
            ).add_to(m)
        
        # Drift path
        folium.PolyLine(
            locations=[(initial['lat'], initial['lon']), (final['lat'], final['lon'])],
            color='black',
            weight=3,
            dash_array='5,10',
            popup=f"Drift path: {drift_results['drift_distance_km']} km"
        ).add_to(m)
        
        # Start marker (green)
        folium.Marker(
            [initial['lat'], initial['lon']],
            popup=f"Start<br>Lat: {initial['lat']:.4f}<br>Lon: {initial['lon']:.4f}",
            icon=folium.Icon(color='green', icon='play'),
            tooltip="Start position"
        ).add_to(m)
        
        # End marker (red)
        folium.Marker(
            [final['lat'], final['lon']],
            popup=f"End<br>Lat: {final['lat']:.4f}<br>Lon: {final['lon']:.4f}",
            icon=folium.Icon(color='red', icon='stop'),
            tooltip="End position"
        ).add_to(m)
        
        # Convert to HTML
        map_html = m._repr_html_()
        return map_html
    
    except Exception as e:
        print(f"[DRIFT] ❌ Error creating drift map: {e}")
        traceback.print_exc()
        return None


def create_trajectory_plot_image(drift_object):
    """
    Create OpenDrift trajectory plot visualization as base64 image
    
    Args:
        drift_object: OpenDrift simulation object with results
    
    Returns:
        Base64 encoded PNG image string or None if creation fails
    """
    try:
        if drift_object is None:
            print("[DRIFT] ⚠️ Drift object is None")
            return None
        
        if not MATPLOTLIB_AVAILABLE:
            print("[DRIFT] ⚠️ Matplotlib not available")
            return None
        
        print("[DRIFT] 🎨 Generating trajectory plot...")
        
        # Clear any previous figures
        plt.close('all')
        
        try:
            # Try to create the trajectory plot using OpenDrift's built-in method
            print("[DRIFT]   Calling drift_object.plot()...")
            fig = drift_object.plot(show_elements=False, show_trajectories=True, density=False)
            print("[DRIFT]   ✓ Plot created successfully")
        except AttributeError as attr_err:
            print(f"[DRIFT]   ⚠️ OpenDrift plot method not available, using fallback")
            # Fallback: create a simple scatter plot if plot() method doesn't work
            try:
                lon = drift_object.result.lon.values
                lat = drift_object.result.lat.values
                
                fig, ax = plt.subplots(figsize=(12, 8))
                
                # Plot initial positions (blue)
                ax.scatter(lon[0], lat[0], c='blue', s=10, alpha=0.6, label='Initial (1000)')
                
                # Plot final positions (green)
                ax.scatter(lon[-1], lat[-1], c='green', s=10, alpha=0.6, label='Final (1000)')
                
                # Plot trajectories
                for i in range(len(lon)):
                    ax.plot(lon[i], lat[i], 'gray', alpha=0.1, linewidth=0.5)
                
                ax.set_xlabel('Longitude (°)')
                ax.set_ylabel('Latitude (°)')
                ax.set_title('OpenDrift - OceanDrift')
                ax.legend()
                ax.grid(True, alpha=0.3)
                
                print("[DRIFT]   ✓ Fallback plot created")
            except Exception as fallback_err:
                print(f"[DRIFT]   ✗ Fallback plot also failed: {fallback_err}")
                traceback.print_exc()
                return None
        
        try:
            # Convert figure to base64 image
            print("[DRIFT]   Converting to PNG...")
            img_buffer = io.BytesIO()
            fig.savefig(img_buffer, format='png', dpi=100, bbox_inches='tight', facecolor='white')
            img_buffer.seek(0)
            
            # Close figure to free memory
            plt.close(fig)
            
            # Encode to base64
            img_bytes = img_buffer.getvalue()
            img_base64 = base64.b64encode(img_bytes).decode('utf-8')
            data_uri = f"data:image/png;base64,{img_base64}"
            
            print(f"[DRIFT] ✓ Trajectory plot created ({len(img_base64)} base64 chars, {len(img_bytes)} bytes)")
            return data_uri
        
        except Exception as encode_err:
            print(f"[DRIFT]   ✗ Error encoding image: {encode_err}")
            traceback.print_exc()
            return None
    
    except Exception as e:
        print(f"[DRIFT] ❌ Error creating trajectory plot: {e}")
        traceback.print_exc()
        return None


def generate_drift_animation(drift_object, output_filename):
    """
    Generate MP4 animation from drift simulation results
    
    Args:
        drift_object: OpenDrift simulation object with results
        output_filename: Output MP4 filename (without path)
    
    Returns:
        Full path to generated MP4 file or None if generation fails
    """
    try:
        if not OPENDRIFT_AVAILABLE or drift_object is None:
            return None
        
        animations_dir = os.path.abspath('animations')
        animation_path = os.path.join(animations_dir, output_filename)
        
        print(f"\n[DRIFT] 🎬 Generating animation: {output_filename}")
        print(f"[DRIFT] Output path: {animation_path}")
        
        # Ensure animations directory exists
        os.makedirs(animations_dir, exist_ok=True)
        
        # Generate animation with clean visualization (no density/intensity overlay)
        drift_object.animation(
            filename=animation_path,
            markersize=5,
            fast=True,
            fps=10,
            show_arrow=False,
            density=False       # Clean visualization without intensity heatmap
        )
        
        # Verify file was created
        if os.path.exists(animation_path):
            file_size = os.path.getsize(animation_path)
            print(f"[DRIFT] ✓ Animation generated: {file_size} bytes")
            return animation_path
        else:
            print(f"[DRIFT] ❌ Animation file not created at {animation_path}")
            return None
    
    except Exception as e:
        print(f"[DRIFT] ❌ Error generating animation: {e}")
        traceback.print_exc()
        return None


def cleanup_drift_files():
    """Delete temporary NetCDF files created during drift simulation"""
    files_to_delete = ["wind.nc", "currents.nc"]
    for file in files_to_delete:
        if os.path.exists(file):
            try:
                os.remove(file)
                print(f"[DRIFT] ✓ Deleted {file}")
            except Exception as e:
                print(f"[DRIFT] ⚠️ Failed to delete {file}: {e}")


def get_drift_module_status():
    """Get availability status of all drift simulation dependencies"""
    return {
        'scipy': SCIPY_AVAILABLE,
        'copernicusmarine': COPERNICUSMARINE_AVAILABLE,
        'opendrift': OPENDRIFT_AVAILABLE,
        'folium': FOLIUM_AVAILABLE,
        'matplotlib': MATPLOTLIB_AVAILABLE,
        'rasterio': RASTERIO_AVAILABLE,
        'netcdf4': NETCDF4_AVAILABLE,
        'all_available': all([
            SCIPY_AVAILABLE, OPENDRIFT_AVAILABLE,
            FOLIUM_AVAILABLE, RASTERIO_AVAILABLE, MATPLOTLIB_AVAILABLE, NETCDF4_AVAILABLE
        ])
    }
