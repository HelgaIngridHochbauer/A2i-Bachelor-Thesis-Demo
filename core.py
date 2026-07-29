# Global parameters                            

QGIS_CRS = "EPSG:3857" #canvas coordinates
TARGET_CRS = "EPSG:4326" #coordinates of your map

RESULTS_PATH =''
PYTHON_PATH = ''
LINE_WIDTH = 0.7

SCRIPT_SLEEP = 10

DOWNLOAD_MAP = True 
MAP_TYPE = "mt1.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}"

# Unified CSV header for all output modes (single, batch, clustering)
CSV_HEADER = ['object_id', 'cluster_id', 'latitude', 'longitude',
              'centroid_lat', 'centroid_lon', 'azimuth', 'altitude',
              'declination', 'stars', 'processing_time', 'total_processing_time',
              'comments']

from .resources import *
import requests
import time
import csv
import os.path
from os import path
import sys
from qgis.gui import QgsMapToolEmitPoint
from qgis.core import QgsProject
from qgis.core import QgsCoordinateReferenceSystem
from qgis.core import QgsCoordinateTransform
from qgis.core import Qgis
from qgis.gui import QgsMapTool
from qgis.core import QgsPoint
from qgis.core import QgsVectorLayer
from qgis.core import QgsFeature
from qgis.core import QgsGeometry
from qgis.core import QgsField
from qgis.core import QgsLineSymbol
from qgis.gui import QgsVertexMarker
from qgis.PyQt.QtCore import Qt, QVariant, QCoreApplication

from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt import QtGui
from qgis.PyQt.QtWidgets import QInputDialog, QLineEdit, QPushButton, QMessageBox, QProgressDialog
from qgis.core import QgsPointXY, QgsRectangle
from .utility import *
from .dialog import *
from .save_data import *
from pathlib import Path
from .clustering import get_clustering_method, list_methods
from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess


def _format_elapsed_time(seconds):
    """Return a human-readable elapsed time string."""
    if seconds < 60:
        return f"{seconds:.2f} seconds"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes} min {secs:.2f} sec"


def _get_standalone_python():
    """Return path to standalone Python for subprocess if set and different from QGIS Python."""
    global PYTHON_PATH
    if not PYTHON_PATH or not os.path.exists(PYTHON_PATH):
        return None
    try:
        if os.path.normpath(os.path.abspath(PYTHON_PATH)) == os.path.normpath(os.path.abspath(sys.executable)):
            return None
    except Exception:
        return None
    return PYTHON_PATH


def _load_horizon_module(script_path):
    """Load the horizon script module (script.py) for in-process use."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("a2i_horizon_script", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _download_horizon_data(script_path, hwt_id, on_waiting=None):
    """
    Download the full horizon profile from HeyWhatsThat.
    Returns the horizon dict (with 'data' key containing az/alt pairs).
    This allows querying altitude at multiple azimuths without re-downloading.
    HeyWhatsThat can take up to ~2 minutes to generate a panorama.
    """
    mod = _load_horizon_module(script_path)
    return mod.download_hwt(hwt_id, on_waiting=on_waiting)


def _horizon_altitude(script_path, hor, azimuth):
    """
    Interpolate altitude at a given azimuth from previously downloaded horizon data.
    hor: horizon dict from _download_horizon_data().
    Returns altitude in degrees.
    """
    mod = _load_horizon_module(script_path)
    return mod.hor2alt(hor, azimuth)


def _run_horizon_script(script_path, hwt_id, azimuth, on_waiting=None):
    """
    Run horizon script: subprocess if a standalone Python is configured (no QGIS window),
    else in-process. Returns altitude in degrees or raises.
    on_waiting: Optional callback(message) for progress (e.g. "Still waiting for HeyWhatsThat...").
    HeyWhatsThat can take up to ~2 minutes to generate a panorama.
    """
    python_exe = _get_standalone_python()
    if python_exe:
        args = [python_exe, script_path, hwt_id, str(azimuth)]
        creation_flags = 0
        if sys.platform == 'win32':
            creation_flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        # HeyWhatsThat can take up to ~2 minutes; allow 2.5 min
        result = subprocess.run(args, capture_output=True, shell=False, text=True, timeout=150, creationflags=creation_flags)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or "Horizon script failed")
        return float(result.stdout.strip())
    hor = _download_horizon_data(script_path, hwt_id, on_waiting=on_waiting)
    return _horizon_altitude(script_path, hor, azimuth)


#Main tool
class DeclinationTool(QgsMapToolEmitPoint):
    def __init__(self, canvas, iface, plugin_dir, resultsPath, PythonPath, scriptSleep, lineWidth, downloadMap, srtmPath=''):
        self.pointList = []
        self.transformedPoints = []
        self.code = ""
        self.az = 0
        self.altitude = 0
        self.decl = 0
        self.stars = []
        self.canvas = canvas
        self.iface = iface
        self.scriptPath = plugin_dir
        self.srtmPath = srtmPath
        # Batch mode state management
        self.batch_mode = False
        self.captured_objects = []  # List of tuples: ((point1, point2), (transformed1, transformed2), azimuth_or_none)
        # azimuth_or_none: float if provided/calculated, None if not yet calculated
        self.markers = []  # List of QgsVertexMarker objects for visualization
        self.cluster_results = []  # Store cluster calculation results
        self.batch_results = []  # Store batch (no clustering) calculation results
        self.cluster_layers = []  # List of QgsVectorLayer for cluster visualizations (not used anymore, kept for compatibility)
        self.clustering_method_name = 'dbscan'  # Default clustering method
        self.use_silhouette = True  # Silhouette quality gate for Barnes-Hut
        
        global RESULTS_PATH 
        RESULTS_PATH = resultsPath
        global PYTHON_PATH
        PYTHON_PATH = PythonPath
        global LINE_WIDTH
        LINE_WIDTH = lineWidth
        global SCRIPT_SLEEP
        SCRIPT_SLEEP = scriptSleep
        global DOWNLOAD_MAP
        DOWNLOAD_MAP = downloadMap

        QgsMapToolEmitPoint.__init__(self, self.canvas)

    # ------------------------------------------------------------------
    #  Unified horizon helpers – SRTM when configured, HeyWhatsThat otherwise
    # ------------------------------------------------------------------

    def _use_srtm(self):
        """Return True if the SRTM-based pipeline should be used."""
        return bool(self.srtmPath and os.path.isdir(self.srtmPath))

    def _compute_horizon_profile(self, lat, lon, label='', on_waiting=None,
                                  progress=None):
        """
        Compute a full 360-degree horizon profile for the observer at
        (*lat*, *lon*).

        If an SRTM data folder is configured, runs the local SRTM pipeline.
        Otherwise, falls back to HeyWhatsThat.

        Returns
        -------
        dict
            ``{'data': [{'az': float, 'alt': float}, ...], 'metadata': {...}}``
        """
        t_start = time.time()
        if self._use_srtm():
            source = "SRTM"
            print("[A2i] Using LOCAL SRTM data for horizon profile"
                  " (label='{}', lat={:.5f}, lon={:.5f})".format(label, lat, lon))
            from .srtm_horizon.srtm_pipeline import compute_srtm_horizon
            result = compute_srtm_horizon(
                lat, lon,
                srtm_folder=self.srtmPath,
                plugin_dir=self.scriptPath,
                target_azimuth=-1,
                on_waiting=on_waiting,
            )
        else:
            source = "HeyWhatsThat"
            print("[A2i] Using HeyWhatsThat.com for horizon profile"
                  " (label='{}', lat={:.5f}, lon={:.5f})".format(label, lat, lon))
            code = self._request_hwt_code(lat, lon, label or 'horizon',
                                          progress)
            if not code:
                raise RuntimeError(
                    "Failed to obtain a HeyWhatsThat panorama code.")
            script_path = os.path.join(self.scriptPath, "script.py")
            result = _download_horizon_data(script_path, code,
                                            on_waiting=on_waiting)
        elapsed = time.time() - t_start
        n_bins = len(result.get('data', []))
        print("[A2i] Horizon profile complete ({}) — {:.1f}s, "
              "{} azimuth bins".format(source, elapsed, n_bins))
        return result

    def _altitude_from_profile(self, horizon_data, azimuth):
        """
        Interpolate altitude at *azimuth* from a previously computed
        horizon profile (returned by ``_compute_horizon_profile``).

        Works transparently with both SRTM and HeyWhatsThat profiles.
        """
        if self._use_srtm():
            from .srtm_horizon.srtm_pipeline import srtm_hor2alt
            return srtm_hor2alt(horizon_data, azimuth)
        else:
            script_path = os.path.join(self.scriptPath, "script.py")
            return _horizon_altitude(script_path, horizon_data, azimuth)

    def canvasPressEvent( self, e ):
        #get point on click
        point = self.toMapCoordinates(self.canvas.mouseLastXY())

        #transform from map CRS to target CRS
        tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem(QGIS_CRS), QgsCoordinateReferenceSystem(TARGET_CRS), QgsProject.instance())
        transformed_point = tr.transform(point)
        
        #append points to respective lists
        self.pointList.append(point)
        self.transformedPoints.append(transformed_point)

        if len(self.transformedPoints) == 1:
            print('Point 1: ({:.4f}, {:.4f})'.format(transformed_point[1], transformed_point[0]))
        else:
            print('Point 2: ({:.4f}, {:.4f})'.format(transformed_point[1], transformed_point[0]))

        if len(self.pointList) == 2:
            self.drawLine()
            self.az = computeAzimuth(self.pointList)
            
            # If batch mode is enabled, store the object and reset for next object
            if self.batch_mode:
                # Store the object (both points) and calculated azimuth
                object_points = (self.pointList[0], self.pointList[1])
                object_transformed = (self.transformedPoints[0], self.transformedPoints[1])
                self.captured_objects.append((object_points, object_transformed, self.az))
                
                # Add markers for visualization
                self.addObjectMarkers(object_points)
                
                # Reset for next object
                self.pointList = []
                self.transformedPoints = []
                print(f"Object captured. Total objects: {len(self.captured_objects)}")
    
    def canvasReleaseEvent( self, e ):
        # Only process immediately if not in batch mode
        # Workflow: horizon profile + already computed azimuth + location → declination.
        # Uses SRTM data if configured, otherwise falls back to HeyWhatsThat.
        if not self.batch_mode and len(self.pointList) == 2:
            source_label = "SRTM" if self._use_srtm() else "HeyWhatsThat.com"
            try:
                t_total_start = time.time()
                self.iface.messageBar().clearWidgets()
                self.iface.messageBar().pushMessage(
                    "Computing horizon profile from {} ...".format(source_label),
                    Qgis.Info)
                QCoreApplication.processEvents()

                lat = self.transformedPoints[0].y()
                lon = self.transformedPoints[0].x()

                def on_waiting(msg):
                    self.iface.messageBar().pushMessage("A2i", msg, Qgis.Info, duration=0)
                    QCoreApplication.processEvents()

                horizon = self._compute_horizon_profile(
                    lat, lon, label="single object", on_waiting=on_waiting)
                self.altitude = self._altitude_from_profile(horizon, self.az)

                t_total_elapsed = time.time() - t_total_start
                self.iface.messageBar().clearWidgets()
                self.iface.messageBar().pushSuccess(
                    "Success",
                    "[{}] Altitude {:.2f}\u00b0 at azimuth {:.2f}\u00b0 ({:.1f}s)".format(
                        source_label, self.altitude, self.az, t_total_elapsed))

                self.decl = computeDeclination(self.altitude, self.az, self.transformedPoints)
                self.stars = checkDeclinationBSC5(self.decl, self.scriptPath)
                sunMoon = checkDeclinationSunMoon(self.decl)
                if sunMoon != "None":
                    self.stars.append(sunMoon)

                t_total_elapsed = time.time() - t_total_start
                print("[A2i] ========== Single object processing completed ==========")
                print(f"[A2i] Total time: {_format_elapsed_time(t_total_elapsed)}")
                print("[A2i] ==========================================================")

                write_to_csv(self, self.scriptPath, self.transformedPoints[0].x(), self.transformedPoints[0].y(), self.az, self.altitude, self.decl, self.stars, t_total_elapsed)
            except Exception as ex:
                import traceback
                traceback.print_exc()
                err_msg = str(ex)
                self.iface.messageBar().pushCritical(
                    "Single-object result failed",
                    "Error computing horizon ({}): {} See Python console for details.".format(source_label, err_msg)
                )
                print("[A2i] Single-object error: {}".format(err_msg))
                return

            self.pointList = []
            self.transformedPoints = []
    
    #draw the line and compute azimuth
    def drawLine(self):

        #create layer for the line
        start_point = QgsPoint(self.pointList[0].x(),self.pointList[0].y())
        end_point = QgsPoint(self.pointList[1].x(),self.pointList[1].y())
        line_layer = QgsVectorLayer('LineString?crs=epsg:3857', 'line', 'memory')
        # setAbstract is deprecated, use setComment instead if available, or skip
        try:
            line_layer.setComment('Point one ({:.4f},{:.4f}) and point two ({:.4f},{:.4f})'.format(
                self.transformedPoints[0].y(), self.transformedPoints[0].x(), self.transformedPoints[1].y(), self.transformedPoints[1].x()))
        except:
            # Fallback for older QGIS versions
            try:
                line_layer.setAbstract('Point one ({:.4f},{:.4f}) and point two ({:.4f},{:.4f})'.format(
                    self.transformedPoints[0].y(), self.transformedPoints[0].x(), self.transformedPoints[1].y(), self.transformedPoints[1].x()))
            except:
                pass  # Skip if neither method works
        line_layer.renderer().symbol().setWidth(LINE_WIDTH)
        pr = line_layer.dataProvider()
        seg = QgsFeature()
        seg.setGeometry(QgsGeometry.fromPolyline([start_point, end_point]))
        pr.addFeatures([ seg ])
        QgsProject.instance().addMapLayers([line_layer])

            
    #send request for HeyWhatsThat.com code
    def handleRequest(self):
        self.iface.messageBar().pushMessage("Sending HTTP request to [HeyWhatsThat.com]. Please wait for the response.....", Qgis.Info, 2)
        lat = self.transformedPoints[0].y()
        lon = self.transformedPoints[0].x()
        code = self._request_hwt_code(lat, lon, "single object")
        self.code = code if code else ""
        
     
    #call script and get altitude value (in-process to avoid QGIS GUI spawning in batch)
    def handleScript(self):
        script_path = os.path.join(self.scriptPath, "script.py")
        if not os.path.exists(script_path):
            raise ValueError(f"Script not found: {script_path}")
        # So the user sees "Still waiting..." etc. while HeyWhatsThat can take up to ~2 min
        def on_waiting(msg):
            self.iface.messageBar().pushMessage("A2i", msg, Qgis.Info, duration=0)
            QCoreApplication.processEvents()
        try:
            altitude_value = _run_horizon_script(script_path, self.code, self.az, on_waiting=on_waiting)
            print("Altitude is {}".format(altitude_value))
            self.altitude = altitude_value
        except Exception as e:
            print(f"Error running horizon script: {e}")
            raise RuntimeError(f"Failed to run horizon script: {e}") from e

    def reset(self):
        self.pointList = []
        self.transformedPoints = []
        self.isEmittingPoint = False
        if hasattr(self, 'rubberBand'):
            self.rubberBand.reset(True)
        
    def deactivate(self):
        QgsMapTool.deactivate(self)
        if hasattr(self, 'deactivated'):
            self.deactivated.emit()
    
    def addObjectMarkers(self, points):
        """Add vertex markers for object points"""
        for point in points:
            marker = QgsVertexMarker(self.canvas)
            marker.setCenter(QgsPointXY(point.x(), point.y()))
            marker.setColor(QColor(255, 0, 0))  # Red for object points
            marker.setIconSize(8)
            marker.setIconType(QgsVertexMarker.ICON_CROSS)
            marker.setPenWidth(2)
            self.markers.append(marker)
    
    def addCentroidMarker(self, point, cluster_id):
        """Add vertex marker for cluster centroid (the point where calculations are performed)"""
        marker = QgsVertexMarker(self.canvas)
        marker.setCenter(QgsPointXY(point.x(), point.y()))
        marker.setColor(QColor(0, 255, 0))  # Bright green for centroids
        marker.setIconSize(15)  # Larger size for better visibility
        marker.setIconType(QgsVertexMarker.ICON_CIRCLE)
        marker.setPenWidth(4)  # Thicker outline for visibility
        self.markers.append(marker)
        print(f"Added green centroid marker for cluster {cluster_id} at ({point.x():.2f}, {point.y():.2f})")
    
    def clearMarkers(self):
        """Remove all markers from canvas"""
        for marker in self.markers:
            try:
                # QgsVertexMarker should be removed from canvas scene
                if marker and self.canvas.scene():
                    self.canvas.scene().removeItem(marker)
            except:
                pass
        self.markers = []
    
    def clearClusterLayers(self):
        """Remove all cluster visualization layers"""
        for layer in self.cluster_layers:
            try:
                QgsProject.instance().removeMapLayer(layer.id())
            except:
                pass
        self.cluster_layers = []
    
    def process_clusters(self):
        """Group captured objects into clusters and calculate centroids"""
        if len(self.captured_objects) == 0:
            self.iface.messageBar().pushWarning("Warning", "No objects captured. Please capture objects first.")
            return []
        
        self.iface.messageBar().pushMessage("Clustering objects...", Qgis.Info, duration=2)
        
        # Allow Qt to process events
        QCoreApplication.processEvents()
        
        # Extract centroids of each object (midpoint of the two points)
        object_centroids = []
        for obj_data in self.captured_objects:
            # Unpack: (obj_points, obj_transformed, azimuth_or_none)
            if len(obj_data) == 3:
                obj_points, obj_transformed, azimuth_or_none = obj_data
            else:
                # Backward compatibility: old format without azimuth
                obj_points, obj_transformed = obj_data
                azimuth_or_none = None
            # Calculate midpoint (centroid) of the object
            p1 = obj_transformed[0]
            p2 = obj_transformed[1]
            centroid_lat = (p1.y() + p2.y()) / 2.0
            centroid_lon = (p1.x() + p2.x()) / 2.0
            object_centroids.append((centroid_lat, centroid_lon, obj_points, obj_transformed, azimuth_or_none))
        
        # Allow Qt to process events
        QCoreApplication.processEvents()
        
        # Use the selected clustering method
        distance_threshold = 100.0  # 100 meters
        
        try:
            clustering_method = get_clustering_method(self.clustering_method_name)
            labels = clustering_method.cluster(
                object_centroids,
                distance_threshold=distance_threshold,
                use_silhouette=self.use_silhouette,
            )
        except Exception as e:
            print(f"Error in clustering method '{self.clustering_method_name}': {e}")
            self.iface.messageBar().pushWarning("Warning", f"Clustering failed: {e}")
            return []
        
        # Allow Qt to process events after clustering
        QCoreApplication.processEvents()
        
        # Validate labels length matches input data
        if len(labels) != len(object_centroids):
            error_msg = f"Clustering method returned {len(labels)} labels for {len(object_centroids)} objects. Lengths must match."
            print(f"Error: {error_msg}")
            self.iface.messageBar().pushWarning("Warning", f"Clustering failed: {error_msg}")
            return []
        
        # Group objects by cluster, preserving global object index
        clusters = {}
        for idx, label in enumerate(labels):
            if label not in clusters:
                clusters[label] = []
            # Append (global_index, centroid_data) so the global ID is never lost
            clusters[label].append((idx, object_centroids[idx]))
        
        # Cache coordinate transform (create once, reuse many times)
        tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem(TARGET_CRS), 
                                   QgsCoordinateReferenceSystem(QGIS_CRS), 
                                   QgsProject.instance())
        
        # Calculate cluster centroids and prepare results
        cluster_results = []
        total_clusters = len(clusters)
        
        for cluster_idx, (cluster_id, objects) in enumerate(clusters.items()):
            # Allow Qt to process events to prevent freezing
            QCoreApplication.processEvents()
            
            # Calculate mean centroid
            # objects is a list of (global_index, centroid_data) tuples
            num_objects_in_cluster = len(objects)
            if num_objects_in_cluster == 0:
                continue  # Skip empty clusters
            mean_lat = sum(obj[1][0] for obj in objects) / num_objects_in_cluster
            mean_lon = sum(obj[1][1] for obj in objects) / num_objects_in_cluster
            
            # Transform back to map coordinates for visualization
            try:
                centroid_map_point = tr.transform(QgsPointXY(mean_lon, mean_lat), 
                                                 QgsCoordinateTransform.ReverseTransform)
            except Exception as e:
                print(f"Error transforming coordinates for cluster {cluster_id}: {e}")
                continue
            
            # Add centroid marker (this is the point where calculations are performed)
            self.addCentroidMarker(centroid_map_point, cluster_id)
            
            cluster_results.append({
                'cluster_id': cluster_id,
                'centroid_lat': mean_lat,
                'centroid_lon': mean_lon,
                'centroid_map_point': centroid_map_point,
                'num_objects': len(objects),
                'objects': objects
            })
        
        print(f"Found {len(cluster_results)} clusters from {len(self.captured_objects)} objects")
        return cluster_results
    
    def select_clustering_method(self):
        """Open a dialog to select the clustering method"""
        available_methods = list_methods()
        method_descriptions = []
        method_name_map = {}  # Map description to method name
        
        for method_name in available_methods:
            try:
                method = get_clustering_method(method_name)
                description = f"{method.name}: {method.description}"
                method_descriptions.append(description)
                method_name_map[description] = method_name
            except Exception as e:
                print(f"Warning: Could not load method {method_name}: {e}")
                method_descriptions.append(method_name)
                method_name_map[method_name] = method_name
        
        # Find current selection index
        current_index = 0
        if self.clustering_method_name in available_methods:
            try:
                current_method = get_clustering_method(self.clustering_method_name)
                current_description = f"{current_method.name}: {current_method.description}"
                if current_description in method_descriptions:
                    current_index = method_descriptions.index(current_description)
            except:
                if self.clustering_method_name in method_descriptions:
                    current_index = method_descriptions.index(self.clustering_method_name)
        
        item, ok = QInputDialog.getItem(
            self.iface.mainWindow(),
            "Select Clustering Method",
            "Choose a clustering algorithm:",
            method_descriptions,
            current_index,
            False
        )
        
        if ok and item:
            # Map description back to method name
            if item in method_name_map:
                self.clustering_method_name = method_name_map[item]
                try:
                    method = get_clustering_method(self.clustering_method_name)
                    self.iface.messageBar().pushInfo("Clustering Method", f"Selected: {method.name}")
                    print(f"Clustering method set to: {self.clustering_method_name} ({method.name})")
                except:
                    self.iface.messageBar().pushInfo("Clustering Method", f"Selected: {self.clustering_method_name}")
                    print(f"Clustering method set to: {self.clustering_method_name}")
    
    def _request_hwt_code(self, lat, lon, label, progress=None):
        """
        Request a HeyWhatsThat panorama code for a given location.
        Uses a cache so the same coordinates (rounded to 4 decimals, matching the API)
        always return the same panorama code, ensuring identical horizon data.
        """
        # Cache key: coordinates rounded to 4 decimals (same precision as the API URL)
        cache_key = (round(lat, 4), round(lon, 4))
        if not hasattr(self, '_hwt_code_cache'):
            self._hwt_code_cache = {}
        if cache_key in self._hwt_code_cache:
            print(f"[HeyWhatsThat] Reusing cached code for ({cache_key[0]}, {cache_key[1]})")
            return self._hwt_code_cache[cache_key]
        
        # Use fixed name "Horizon1" (same as single-object mode) so the server
        # is more likely to return the same panorama for the same coordinates.
        req = "http://heywhatsthat.com/bin/query.cgi?lat={0:.4f}&lon={1:.4f}&name={2}".format(
            lat, lon, "Horizon1")
        
        r = None
        max_retries = 10
        for i in range(max_retries + 1):
            for _ in range(3):
                QCoreApplication.processEvents()
            if progress and progress.wasCanceled():
                return None
            try:
                r = requests.get(req, timeout=3)
                for _ in range(3):
                    QCoreApplication.processEvents()
                if r and r.text and r.text.strip():
                    break
            except requests.exceptions.RequestException as e:
                print(f"Network error requesting HeyWhatsThat for {label}: {e}")
                if i >= max_retries:
                    return None
            if i < max_retries:
                for wait_step in range(10):
                    QCoreApplication.processEvents()
                    if progress and progress.wasCanceled():
                        return None
                    time.sleep(0.1)
        
        if not r or not r.text or not r.text.strip():
            return None
        code = r.text.strip("\n")
        if code == "":
            return None
        
        self._hwt_code_cache[cache_key] = code
        print(f"[HeyWhatsThat] Got code '{code}' for {label} at ({cache_key[0]}, {cache_key[1]})")
        return code

    def calculate_single_object_orientation(self, object_id, obj_points, obj_transformed, azimuth, progress=None):
        """Calculate orientation and declination for a single object.
        Uses SRTM if configured, otherwise HeyWhatsThat."""
        lat = obj_transformed[0].y()
        lon = obj_transformed[0].x()
        
        QCoreApplication.processEvents()
        source = "SRTM" if self._use_srtm() else "HeyWhatsThat"
        t_obj_start = time.time()
        if progress:
            progress.setLabelText(
                "Computing horizon ({}) for object {}...".format(
                    source, object_id + 1))
            QCoreApplication.processEvents()
        
        try:
            horizon = self._compute_horizon_profile(
                lat, lon,
                label="object {}".format(object_id),
                progress=progress)
            altitude = self._altitude_from_profile(horizon, azimuth)
        except Exception as e:
            print("[A2i] ERROR — Horizon failed for object {} ({}) at "
                  "lat={:.5f}, lon={:.5f}: {}".format(
                      object_id, source, lat, lon, e))
            return None
        
        t_obj_elapsed = time.time() - t_obj_start
        
        decl_point = QgsPointXY(lon, lat)
        decl = computeDeclination(altitude, azimuth, [decl_point])
        stars = checkDeclinationBSC5(decl, self.scriptPath)
        sunMoon = checkDeclinationSunMoon(decl)
        if sunMoon != "None":
            stars.append(sunMoon)
        
        return {
            'object_id': object_id,
            'latitude': lat,
            'longitude': lon,
            'azimuth': azimuth,
            'altitude': altitude,
            'declination': decl,
            'stars': stars,
            'elapsed_time': t_obj_elapsed,
        }
    
    def process_batch_no_clustering(self):
        """Run classic declination computation for each captured object (no clustering)."""
        if len(self.captured_objects) == 0:
            self.iface.messageBar().pushWarning("Warning", "No objects captured. Capture objects or import from CSV first.")
            return
        
        source = "SRTM" if self._use_srtm() else "HeyWhatsThat"
        t_batch_start = time.time()
        print("[A2i] ===== Starting batch processing (horizon source: {}) =====".format(source))
        self.iface.messageBar().pushMessage(
            "Processing objects — no clustering (horizon: {})...".format(source),
            Qgis.Info, duration=2)
        QCoreApplication.processEvents()
        
        progress = QProgressDialog("Computing declinations for each object...", "Cancel", 0, 100, self.canvas)
        progress.setWindowModality(Qt.WindowModal)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setMinimumDuration(0)
        progress.show()
        QCoreApplication.processEvents()
        
        n = len(self.captured_objects)
        self.batch_results = []
        max_workers = min(4, n)
        
        def compute_one(args):
            idx, obj_data = args
            if len(obj_data) == 3:
                obj_points, obj_transformed, azimuth = obj_data
            else:
                obj_points, obj_transformed = obj_data
                azimuth = computeAzimuth([obj_points[0], obj_points[1]])
            return self.calculate_single_object_orientation(idx, obj_points, obj_transformed, azimuth, progress=None)
        
        tasks = list(enumerate(self.captured_objects))
        done = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(compute_one, t): t[0] for t in tasks}
            for future in as_completed(futures):
                if progress.wasCanceled():
                    progress.close()
                    self.iface.messageBar().pushWarning("Cancelled", "Batch computation was cancelled.")
                    return
                try:
                    result = future.result()
                    if result:
                        self.batch_results.append(result)
                except Exception as e:
                    print(f"Batch object error: {e}")
                done += 1
                progress.setValue(int(100 * done / n))
                progress.setLabelText(f"Processing object {done}/{n}...")
                QCoreApplication.processEvents()
        
        progress.setValue(100)
        progress.close()
        t_batch_elapsed = time.time() - t_batch_start
        if not self.batch_results:
            self.iface.messageBar().pushWarning(
                "No results",
                "Horizon data ({}) failed for all objects.{}".format(
                    source,
                    " SRTM tiles may not cover this area — check Python Console."
                    if source == "SRTM" else " Check console for details.")
            )
            return
        print("")
        print("[A2i] ========== Batch processing completed ==========")
        for r in sorted(self.batch_results, key=lambda o: o['object_id']):
            ot = r.get('elapsed_time', 0)
            print(f"[A2i]   Object {r['object_id']}: "
                  f"az={r['azimuth']:.2f}\u00b0, "
                  f"{_format_elapsed_time(ot)}")
        print(f"[A2i] -------------------------------------------------")
        print(f"[A2i] Total objects: {len(self.batch_results)}")
        print(f"[A2i] Horizon source: {source}")
        print(f"[A2i] Total time: {_format_elapsed_time(t_batch_elapsed)}")
        print("[A2i] ====================================================")
        self._last_total_elapsed = round(t_batch_elapsed, 2)
        self.display_batch_results()
        if self.canvas:
            self.canvas.refresh()
    
    def display_batch_results(self):
        """Display batch (no clustering) results."""
        if not self.batch_results:
            return
        results_text = f"=== Batch Results ({len(self.batch_results)} objects) ===\n\n"
        for r in self.batch_results:
            stars_str = ', '.join(r['stars']) if r['stars'] else 'None'
            results_text += f"Object {r['object_id']}:\n"
            results_text += f"  Location: ({r['latitude']:.4f}, {r['longitude']:.4f})\n"
            results_text += f"  Azimuth: {r['azimuth']:.2f}° Altitude: {r['altitude']:.2f}° Declination: {r['declination']:.2f}°\n"
            results_text += f"  Points to: {stars_str}\n\n"
        print(results_text)
        if len(self.batch_results) == 1:
            r = self.batch_results[0]
            stars_str = ', '.join(r['stars']) if r['stars'] else 'None'
            msg = f"Object: Az={r['azimuth']:.1f}° Alt={r['altitude']:.1f}° Decl={r['declination']:.1f}° → {stars_str}"
        else:
            msg = f"Processed {len(self.batch_results)} objects. See console for details."
        self.iface.messageBar().pushSuccess("Batch Complete", msg)
        self.save_batch_results()
    
    def save_batch_results(self):
        """Save batch (no clustering) results to CSV (same format as clustering)."""
        if not self.batch_results:
            return
        global RESULTS_PATH
        if RESULTS_PATH == "Empty":
            RESULTS_PATH = os.getcwd()
        from qgis.PyQt.QtWidgets import QFileDialog
        filepath, _ = QFileDialog.getSaveFileName(
            None, "Save Batch Results", RESULTS_PATH, "Comma Separated Values Files (*.csv)")
        if not filepath:
            return
        total_time = getattr(self, '_last_total_elapsed', '')
        all_rows = [CSV_HEADER]
        for r in self.batch_results:
            stars_str = ', '.join(r['stars']) if r['stars'] else 'None'
            obj_time = round(r.get('elapsed_time', 0), 2)
            all_rows.append([
                r['object_id'], '', r['latitude'], r['longitude'], '', '',
                r['azimuth'], r['altitude'], r['declination'], stars_str,
                obj_time, total_time,
                f"Object {r['object_id']}"
            ])
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                csv.writer(f, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL).writerows(all_rows)
            self.iface.messageBar().pushSuccess("Saved", f"Saved {len(self.batch_results)} objects to {os.path.basename(filepath)}")
            print(f"Saved batch results to {filepath}")
        except Exception as e:
            self.iface.messageBar().pushWarning("Save Error", str(e))
            print(f"Error saving batch results: {e}")
    
    def calculate_cluster_orientation(self, cluster_info, progress=None):
        """
        Calculate orientation and declination for a cluster.
        
        Workflow:
        1. Compute ONE horizon profile for the cluster's mean centroid
           (uses SRTM if configured, otherwise HeyWhatsThat).
        2. For EACH OBJECT in the cluster, interpolate altitude from
           that shared horizon profile using the object's own azimuth,
           then compute declination individually.
        
        Returns a dict with cluster-level info and a list of per-object results.
        """
        centroid_lat = cluster_info['centroid_lat']
        centroid_lon = cluster_info['centroid_lon']
        objects = cluster_info['objects']
        cluster_id = cluster_info['cluster_id']
        
        source = "SRTM" if self._use_srtm() else "HeyWhatsThat"
        t_cluster_start = time.time()
        
        # --- Step 1: Get horizon profile for the cluster centroid ---
        
        QCoreApplication.processEvents()
        if progress:
            progress.setLabelText(
                "Computing horizon ({}) for cluster {}...".format(
                    source, cluster_id))
            QCoreApplication.processEvents()
        
        try:
            horizon_data = self._compute_horizon_profile(
                centroid_lat, centroid_lon,
                label="cluster {}".format(cluster_id),
                progress=progress)
        except Exception as e:
            print("[A2i] ERROR — Horizon failed for cluster {} ({}) at "
                  "lat={:.5f}, lon={:.5f}: {}".format(
                      cluster_id, source, centroid_lat, centroid_lon, e))
            return None
        
        # --- Step 2: For each object, compute altitude + declination using its own azimuth ---
        
        QCoreApplication.processEvents()
        if progress:
            progress.setLabelText(
                "Computing declinations for cluster {} objects...".format(
                    cluster_id))
            QCoreApplication.processEvents()
        
        object_results = []
        for item in objects:
            global_idx, obj = item
            
            # Get object's own azimuth
            if len(obj) >= 5 and obj[4] is not None:
                obj_az = obj[4]
            else:
                obj_points = obj[2]
                obj_az = computeAzimuth([obj_points[0], obj_points[1]])
            
            # Get object's own location (midpoint of transformed points)
            obj_transformed = obj[3]
            obj_lat = (obj_transformed[0].y() + obj_transformed[1].y()) / 2.0
            obj_lon = (obj_transformed[0].x() + obj_transformed[1].x()) / 2.0
            
            # Interpolate altitude at this object's azimuth from the cluster's horizon profile
            try:
                altitude = self._altitude_from_profile(horizon_data, obj_az)
            except Exception as e:
                print("Altitude interpolation error for object {} in cluster {}: {}".format(
                    global_idx, cluster_id, e))
                continue
            
            # Compute declination using object's own azimuth, altitude, and latitude
            decl_point = QgsPointXY(obj_lon, obj_lat)
            decl = computeDeclination(altitude, obj_az, [decl_point])
            
            # Check celestial bodies
            stars = checkDeclinationBSC5(decl, self.scriptPath)
            sunMoon = checkDeclinationSunMoon(decl)
            if sunMoon != "None":
                stars.append(sunMoon)
            
            object_results.append({
                'object_id': global_idx,
                'latitude': obj_lat,
                'longitude': obj_lon,
                'azimuth': obj_az,
                'altitude': altitude,
                'declination': decl,
                'stars': stars,
            })
        
        if not object_results:
            return None
        
        t_cluster_elapsed = time.time() - t_cluster_start
        
        return {
            'cluster_id': cluster_id,
            'centroid_lat': centroid_lat,
            'centroid_lon': centroid_lon,
            'num_objects': cluster_info['num_objects'],
            'object_results': object_results,
            'elapsed_time': t_cluster_elapsed,
        }
    
    def process_all_clusters(self):
        """Process all clusters and calculate results"""
        if len(self.captured_objects) == 0:
            self.iface.messageBar().pushWarning("Warning", "No objects captured. Please capture objects first.")
            return
        
        try:
            source = "SRTM" if self._use_srtm() else "HeyWhatsThat"
            t_all_start = time.time()
            print("[A2i] ===== Starting cluster processing (horizon source: {}) =====".format(source))
            self.iface.messageBar().pushMessage(
                "Processing clusters (horizon: {})...".format(source),
                Qgis.Info, duration=3)
            
            # Create progress dialog to keep UI responsive
            progress = QProgressDialog("Processing clusters...", "Cancel", 0, 100, self.canvas)
            progress.setWindowModality(Qt.WindowModal)
            progress.setAutoClose(False)
            progress.setAutoReset(False)
            progress.setMinimumDuration(0)  # Show immediately
            progress.show()
            QCoreApplication.processEvents()
            
            # Get clusters
            progress.setLabelText("Grouping objects into clusters...")
            progress.setValue(5)
            QCoreApplication.processEvents()
            
            # Process clusters - this may take time, but clustering methods now process events internally
            clusters = self.process_clusters()
            
            # Process events immediately after clustering
            QCoreApplication.processEvents()
            
            if len(clusters) == 0:
                progress.close()
                self.iface.messageBar().pushWarning("Warning", "No clusters found.")
                return
            
            # Calculate results for each cluster (parallel, max 4 workers)
            self.cluster_results = []
            total_clusters = len(clusters)
            progress.setMaximum(100)
            max_workers = min(4, total_clusters)
            done = 0
            
            def compute_cluster(cluster_info):
                return self.calculate_cluster_orientation(cluster_info, progress=None)
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(compute_cluster, c): i for i, c in enumerate(clusters)}
                for future in as_completed(futures):
                    if progress.wasCanceled():
                        progress.close()
                        self.iface.messageBar().pushWarning("Cancelled", "Processing was cancelled by user.")
                        return
                    try:
                        result = future.result()
                        if result:
                            self.cluster_results.append(result)
                    except Exception as e:
                        print(f"Cluster error: {e}")
                    done += 1
                    progress.setValue(5 + int(95 * done / total_clusters))
                    progress.setLabelText(f"Processing cluster {done}/{total_clusters}...")
                    QCoreApplication.processEvents()
            
            progress.setValue(100)
            progress.setLabelText("Creating visualizations...")
            QCoreApplication.processEvents()
            progress.close()
            
            if not self.cluster_results:
                source = "SRTM" if self._use_srtm() else "HeyWhatsThat"
                if source == "SRTM":
                    hint = (" — your SRTM tiles may not cover this area. "
                            "Check Python Console for coordinates.")
                else:
                    hint = ""
                self.iface.messageBar().pushWarning(
                    "No results",
                    "Horizon data ({}) failed for all clusters{}".format(
                        source, hint)
                )
                print("[A2i] HINT: Open Plugins > Python Console to see "
                      "which coordinates failed and compare with your SRTM "
                      "tile coverage.")
                return
            
            # Display results
            t_all_elapsed = time.time() - t_all_start
            n_clusters = len(self.cluster_results)
            n_objs = sum(len(cr['object_results']) for cr in self.cluster_results)
            print("")
            print("[A2i] ========== Clustering processing completed ==========")
            for cr in sorted(self.cluster_results, key=lambda c: c['cluster_id']):
                ct = cr.get('elapsed_time', 0)
                print(f"[A2i]   Cluster {cr['cluster_id']}: "
                      f"{len(cr['object_results'])} objects, "
                      f"{_format_elapsed_time(ct)}")
            print(f"[A2i] -------------------------------------------------")
            print(f"[A2i] Total clusters: {n_clusters}, Total objects: {n_objs}")
            print(f"[A2i] Horizon source: {source}")
            print(f"[A2i] Total time: {_format_elapsed_time(t_all_elapsed)}")
            print("[A2i] =====================================================")
            self._last_total_elapsed = round(t_all_elapsed, 2)
            self.display_cluster_results()
            
            if self.canvas:
                self.canvas.refresh()
            
        except KeyError as e:
            error_msg = f"Missing data key: {str(e)}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            self.iface.messageBar().pushCritical("Clustering Error", error_msg)
        except Exception as e:
            error_msg = f"Error during clustering: {str(e)}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            self.iface.messageBar().pushCritical("Clustering Error", error_msg)
    
    def display_cluster_results(self):
        """Display cluster results: per-object declinations grouped by cluster."""
        if not self.cluster_results:
            return
        
        total_objects = sum(len(cr['object_results']) for cr in self.cluster_results)
        results_text = f"=== Cluster Results ({len(self.cluster_results)} clusters, {total_objects} objects) ===\n\n"
        
        for cr in self.cluster_results:
            results_text += f"Cluster {cr['cluster_id']} (centroid: {cr['centroid_lat']:.4f}, {cr['centroid_lon']:.4f}, {cr['num_objects']} objects):\n"
            results_text += f"  Horizon profile from cluster centroid.\n"
            for obj_r in cr['object_results']:
                stars_str = ', '.join(obj_r['stars']) if obj_r['stars'] else 'None'
                results_text += f"  Object {obj_r['object_id']}:  "
                results_text += f"Az={obj_r['azimuth']:.2f}°  Alt={obj_r['altitude']:.2f}°  "
                results_text += f"Decl={obj_r['declination']:.2f}°  → {stars_str}\n"
            results_text += "\n"
        
        print(results_text)
        
        # Show summary in message bar
        if total_objects == 1:
            obj_r = self.cluster_results[0]['object_results'][0]
            stars_str = ', '.join(obj_r['stars']) if obj_r['stars'] else 'None'
            msg = f"Az={obj_r['azimuth']:.1f}° Alt={obj_r['altitude']:.1f}° Decl={obj_r['declination']:.1f}° → {stars_str}"
        else:
            msg = f"Processed {total_objects} objects across {len(self.cluster_results)} clusters. See console for details."
        
        self.iface.messageBar().pushSuccess("Clustering Complete", msg)
        
        # Save results
        self.save_cluster_results()
    
    def save_cluster_results(self):
        """Save per-object cluster results to CSV (same format as batch)."""
        if not self.cluster_results:
            return
        
        global RESULTS_PATH
        if RESULTS_PATH == "Empty":
            RESULTS_PATH = os.getcwd()
        
        from qgis.PyQt.QtWidgets import QFileDialog
        
        filepath, _ = QFileDialog.getSaveFileName(
            None, "Save Cluster Results", RESULTS_PATH,
            "Comma Separated Values Files (*.csv)")
        
        if not filepath:
            return
        
        total_time = getattr(self, '_last_total_elapsed', '')
        all_rows = [CSV_HEADER]
        for cr in self.cluster_results:
            cluster_id = cr['cluster_id']
            centroid_lat = cr['centroid_lat']
            centroid_lon = cr['centroid_lon']
            cluster_time = round(cr.get('elapsed_time', 0), 2)
            for obj_r in cr['object_results']:
                stars_str = ', '.join(obj_r['stars']) if obj_r['stars'] else 'None'
                all_rows.append([
                    obj_r['object_id'], cluster_id,
                    obj_r['latitude'], obj_r['longitude'],
                    centroid_lat, centroid_lon,
                    obj_r['azimuth'], obj_r['altitude'], obj_r['declination'],
                    stars_str, cluster_time, total_time,
                    f'Cluster {cluster_id}, object {obj_r["object_id"]}'
                ])
        
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                csv.writer(f, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL).writerows(all_rows)
            total_objects = sum(len(cr['object_results']) for cr in self.cluster_results)
            num_clusters = len(self.cluster_results)
            self.iface.messageBar().pushSuccess("Saved",
                f"Saved {total_objects} objects across {num_clusters} clusters to {os.path.basename(filepath)}")
            print(f"Saved {total_objects} objects across {num_clusters} clusters to {filepath}")
        except Exception as e:
            self.iface.messageBar().pushWarning("Save Error", f"Failed to save: {e}")
            print(f"Error saving cluster results: {e}")

    # -----------------------------------------------------------------
    # Experiment mode: run N times with auto-save
    # -----------------------------------------------------------------

    def _save_cluster_results_to_file(self, filepath):
        """Write cluster results to *filepath* without showing a dialog."""
        if not self.cluster_results:
            return False
        total_time = getattr(self, '_last_total_elapsed', '')
        all_rows = [CSV_HEADER]
        for cr in self.cluster_results:
            cluster_id = cr['cluster_id']
            centroid_lat = cr['centroid_lat']
            centroid_lon = cr['centroid_lon']
            cluster_time = round(cr.get('elapsed_time', 0), 2)
            for obj_r in cr['object_results']:
                stars_str = ', '.join(obj_r['stars']) if obj_r['stars'] else 'None'
                all_rows.append([
                    obj_r['object_id'], cluster_id,
                    obj_r['latitude'], obj_r['longitude'],
                    centroid_lat, centroid_lon,
                    obj_r['azimuth'], obj_r['altitude'], obj_r['declination'],
                    stars_str, cluster_time, total_time,
                    f'Cluster {cluster_id}, object {obj_r["object_id"]}'
                ])
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            csv.writer(f, delimiter=',', quotechar='"',
                       quoting=csv.QUOTE_MINIMAL).writerows(all_rows)
        return True

    def _save_batch_results_to_file(self, filepath):
        """Write batch results to *filepath* without showing a dialog."""
        if not self.batch_results:
            return False
        total_time = getattr(self, '_last_total_elapsed', '')
        all_rows = [CSV_HEADER]
        for r in self.batch_results:
            stars_str = ', '.join(r['stars']) if r['stars'] else 'None'
            obj_time = round(r.get('elapsed_time', 0), 2)
            all_rows.append([
                r['object_id'], '', r['latitude'], r['longitude'], '', '',
                r['azimuth'], r['altitude'], r['declination'], stars_str,
                obj_time, total_time,
                f"Object {r['object_id']}"
            ])
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            csv.writer(f, delimiter=',', quotechar='"',
                       quoting=csv.QUOTE_MINIMAL).writerows(all_rows)
        return True

    def run_experiment_clustering(self, n_runs, folder):
        """Run clustering + processing *n_runs* times, saving each to folder/1.csv … n.csv."""
        print(f"\n[A2i] ===== Experiment: clustering x{n_runs} =====")
        self.iface.messageBar().pushMessage(
            f"Experiment: running clustering {n_runs} times...",
            Qgis.Info, duration=3)
        QCoreApplication.processEvents()

        # We temporarily replace save/display so the loop doesn't pop dialogs
        orig_display = self.display_cluster_results
        orig_save = self.save_cluster_results
        self.display_cluster_results = lambda: None
        self.save_cluster_results = lambda: None

        try:
            for run_idx in range(1, n_runs + 1):
                print(f"\n[A2i] --- Experiment run {run_idx}/{n_runs} ---")
                self.iface.messageBar().pushMessage(
                    f"Experiment run {run_idx}/{n_runs}...",
                    Qgis.Info, duration=2)
                QCoreApplication.processEvents()

                self.process_all_clusters()

                filepath = os.path.join(folder, f"{run_idx}.csv")
                try:
                    if self._save_cluster_results_to_file(filepath):
                        print(f"[A2i]   Saved run {run_idx} → {filepath}")
                    else:
                        print(f"[A2i]   Run {run_idx}: no results to save")
                except Exception as e:
                    print(f"[A2i]   Run {run_idx} save error: {e}")
        finally:
            self.display_cluster_results = orig_display
            self.save_cluster_results = orig_save

        print(f"\n[A2i] ===== Experiment complete: {n_runs} runs saved to {folder} =====")
        self.iface.messageBar().pushSuccess(
            "Experiment Complete",
            f"Saved {n_runs} CSV files to {folder}")

    def run_experiment_batch(self, n_runs, folder):
        """Run batch (no clustering) *n_runs* times, saving each to folder/1.csv … n.csv."""
        print(f"\n[A2i] ===== Experiment: batch x{n_runs} =====")
        self.iface.messageBar().pushMessage(
            f"Experiment: running batch {n_runs} times...",
            Qgis.Info, duration=3)
        QCoreApplication.processEvents()

        orig_display = self.display_batch_results
        orig_save = self.save_batch_results
        self.display_batch_results = lambda: None
        self.save_batch_results = lambda: None

        try:
            for run_idx in range(1, n_runs + 1):
                print(f"\n[A2i] --- Experiment run {run_idx}/{n_runs} ---")
                self.iface.messageBar().pushMessage(
                    f"Experiment run {run_idx}/{n_runs}...",
                    Qgis.Info, duration=2)
                QCoreApplication.processEvents()

                self.process_batch_no_clustering()

                filepath = os.path.join(folder, f"{run_idx}.csv")
                try:
                    if self._save_batch_results_to_file(filepath):
                        print(f"[A2i]   Saved run {run_idx} → {filepath}")
                    else:
                        print(f"[A2i]   Run {run_idx}: no results to save")
                except Exception as e:
                    print(f"[A2i]   Run {run_idx} save error: {e}")
        finally:
            self.display_batch_results = orig_display
            self.save_batch_results = orig_save

        print(f"\n[A2i] ===== Experiment complete: {n_runs} runs saved to {folder} =====")
        self.iface.messageBar().pushSuccess(
            "Experiment Complete",
            f"Saved {n_runs} CSV files to {folder}")

    def clear_captured_points(self):
        """Clear all captured objects and markers"""
        self.captured_objects = []
        self.cluster_results = []
        self.batch_results = []
        self._hwt_code_cache = {}  # Clear HeyWhatsThat panorama cache
        self.clearMarkers()
        self.clearClusterLayers()
        self.pointList = []
        self.transformedPoints = []
        self.iface.messageBar().pushSuccess("Cleared", "All captured points and markers cleared.")
        print("Cleared all captured points")
    
    def import_from_csv(self, filepath):
        """
        Import objects from a CSV file.
        
        CSV Format (one row per object):
        - Required columns: lat1, lon1, lat2, lon2 (decimal degrees, EPSG:4326)
        - Optional column: azimuth (degrees, 0-360)
        
        Example CSV:
        lat1,lon1,lat2,lon2,azimuth
        45.1234,-73.5678,45.1240,-73.5680,45.5
        45.1300,-73.5700,45.1305,-73.5705,46.2
        
        If azimuth is not provided, it will be calculated from the points.
        """
        try:
            import csv as csv_module
            from qgis.PyQt.QtWidgets import QFileDialog
            
            # If no filepath provided, show file dialog
            if not filepath:
                global RESULTS_PATH
                if RESULTS_PATH == "Empty":
                    RESULTS_PATH = os.getcwd()
                
                filepath, _ = QFileDialog.getOpenFileName(
                    None,
                    "Import Objects from CSV",
                    RESULTS_PATH,
                    "Comma Separated Values Files (*.csv)"
                )
                
                if not filepath:
                    return False  # User cancelled
            
            # Read CSV file
            imported_count = 0
            errors = []
            
            # Cache coordinate transforms
            tr_to_target = QgsCoordinateTransform(
                QgsCoordinateReferenceSystem(QGIS_CRS),
                QgsCoordinateReferenceSystem(TARGET_CRS),
                QgsProject.instance()
            )
            
            with open(filepath, 'r', encoding='utf-8') as f:
                # Try to detect header
                reader = csv_module.reader(f)
                rows = list(reader)
                
                if not rows:
                    self.iface.messageBar().pushWarning("Import Error", "CSV file is empty.")
                    return False
                
                # Detect if first row is header
                header = rows[0]
                start_row = 0
                
                # Try to find column indices
                lat1_idx = lon1_idx = lat2_idx = lon2_idx = azimuth_idx = None
                
                # Check if header exists (non-numeric values)
                try:
                    float(header[0])
                    # No header, use indices 0-4
                    lat1_idx, lon1_idx, lat2_idx, lon2_idx = 0, 1, 2, 3
                    if len(header) >= 5:
                        azimuth_idx = 4
                    start_row = 0
                except (ValueError, IndexError):
                    # Header exists, find column names
                    header_lower = [col.lower().strip() for col in header]
                    for idx, col in enumerate(header_lower):
                        if col in ['lat1', 'latitude1', 'lat_1']:
                            lat1_idx = idx
                        elif col in ['lon1', 'longitude1', 'lon_1', 'lng1']:
                            lon1_idx = idx
                        elif col in ['lat2', 'latitude2', 'lat_2']:
                            lat2_idx = idx
                        elif col in ['lon2', 'longitude2', 'lon_2', 'lng2']:
                            lon2_idx = idx
                        elif col in ['azimuth', 'az', 'bearing']:
                            azimuth_idx = idx
                    start_row = 1
                
                # Validate required columns found
                if None in [lat1_idx, lon1_idx, lat2_idx, lon2_idx]:
                    self.iface.messageBar().pushCritical(
                        "Import Error",
                        "CSV must contain columns: lat1, lon1, lat2, lon2 (or latitude1/longitude1, etc.)"
                    )
                    return False
                
                # Process data rows
                for row_idx, row in enumerate(rows[start_row:], start=start_row + 1):
                    try:
                        if len(row) < max(lat1_idx, lon1_idx, lat2_idx, lon2_idx) + 1:
                            errors.append(f"Row {row_idx}: Not enough columns")
                            continue
                        
                        # Parse coordinates
                        lat1 = float(row[lat1_idx])
                        lon1 = float(row[lon1_idx])
                        lat2 = float(row[lat2_idx])
                        lon2 = float(row[lon2_idx])
                        
                        # Validate coordinate ranges
                        if not (-90 <= lat1 <= 90) or not (-90 <= lat2 <= 90):
                            errors.append(f"Row {row_idx}: Latitude out of range (-90 to 90)")
                            continue
                        if not (-180 <= lon1 <= 180) or not (-180 <= lon2 <= 180):
                            errors.append(f"Row {row_idx}: Longitude out of range (-180 to 180)")
                            continue
                        
                        # Parse optional azimuth
                        azimuth = None
                        if azimuth_idx is not None and azimuth_idx < len(row):
                            try:
                                azimuth_str = row[azimuth_idx].strip()
                                if azimuth_str:
                                    azimuth = float(azimuth_str)
                                    # Normalize to 0-360 range
                                    while azimuth < 0:
                                        azimuth += 360
                                    while azimuth >= 360:
                                        azimuth -= 360
                            except (ValueError, IndexError):
                                pass  # Azimuth not provided or invalid, will calculate
                        
                        # Create QgsPointXY objects in EPSG:4326 (target CRS)
                        point1_transformed = QgsPointXY(lon1, lat1)
                        point2_transformed = QgsPointXY(lon2, lat2)
                        
                        # Transform to map CRS (EPSG:3857) for visualization
                        point1_map = tr_to_target.transform(
                            point1_transformed,
                            QgsCoordinateTransform.ReverseTransform
                        )
                        point2_map = tr_to_target.transform(
                            point2_transformed,
                            QgsCoordinateTransform.ReverseTransform
                        )
                        
                        # Calculate azimuth if not provided
                        if azimuth is None:
                            azimuth = computeAzimuth([point1_map, point2_map])
                        
                        # Store object (same format as manual capture)
                        object_points = (point1_map, point2_map)
                        object_transformed = (point1_transformed, point2_transformed)
                        self.captured_objects.append((object_points, object_transformed, azimuth))
                        
                        # Add visualization markers and line
                        self.addObjectMarkers(object_points)
                        self.drawLineBetweenPoints(point1_map, point2_map)
                        
                        imported_count += 1
                        
                    except (ValueError, IndexError) as e:
                        errors.append(f"Row {row_idx}: {str(e)}")
                        continue
                
                # Report results
                if imported_count > 0:
                    self.iface.messageBar().pushSuccess(
                        "Import Complete",
                        f"Imported {imported_count} object(s) from CSV. Total objects: {len(self.captured_objects)}"
                    )
                    print(f"Imported {imported_count} object(s) from CSV file: {filepath}")
                    
                    if errors:
                        error_msg = f"({len(errors)} row(s) had errors - see console)"
                        print(f"Import errors: {errors}")
                        self.iface.messageBar().pushWarning("Import Warnings", error_msg)
                    
                    return True
                else:
                    self.iface.messageBar().pushWarning(
                        "Import Failed",
                        "No valid objects imported. Check CSV format."
                    )
                    if errors:
                        print(f"Import errors: {errors}")
                    return False
                    
        except Exception as e:
            error_msg = f"Error importing CSV: {str(e)}"
            self.iface.messageBar().pushCritical("Import Error", error_msg)
            print(f"CSV import error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def drawLineBetweenPoints(self, point1, point2):
        """Draw a line between two points on the canvas"""
        # Create or get line layer
        line_layer_name = "Imported Objects Lines"
        layer = None
        layers = QgsProject.instance().mapLayersByName(line_layer_name)
        
        if layers:
            layer = layers[0]
        else:
            # Create new layer
            layer = QgsVectorLayer("LineString?crs=" + QGIS_CRS, line_layer_name, "memory")
            QgsProject.instance().addMapLayer(layer)
            
            # Style the layer
            try:
                symbol = QgsLineSymbol.createSimple({
                    'line_color': '255,0,0,255',
                    'line_width': str(LINE_WIDTH)
                })
                layer.renderer().setSymbol(symbol)
            except:
                # Fallback: set width directly
                try:
                    layer.renderer().symbol().setWidth(LINE_WIDTH)
                except:
                    pass
        
        # Add feature
        provider = layer.dataProvider()
        feat = QgsFeature()
        geom = QgsGeometry.fromPolylineXY([point1, point2])
        feat.setGeometry(geom)
        provider.addFeature(feat)
        layer.updateExtents()


#Various functions
def write_to_csv(self, scriptPath, xcoord, ycoord, azimuth, altitude, declination, stars, elapsed_time=0):
    global RESULTS_PATH
    starsString = ', '.join(stars) if stars else 'None'
    proc_time = round(elapsed_time, 2)

    data = [0, '', ycoord, xcoord, '', '', azimuth, altitude, declination, starsString, proc_time, proc_time]

    messageString = "The bearing of the line is: Az: " + str(azimuth) + " Alt: " + str(altitude) + " Declination: " + str(declination) + " pointing to: " + starsString 
    print(messageString)
    self.iface.messageBar().pushMessage("Result", messageString, Qgis.Info)

    if RESULTS_PATH == "Empty":
        RESULTS_PATH = os.getcwd()

    save = Ui_Save(data, RESULTS_PATH, os.path.join(scriptPath, "save_data.ui"))
    save.setWindowIcon(QtGui.QIcon(':/plugins/a2i/logo/icons/logo.png'))
    save.exec()
