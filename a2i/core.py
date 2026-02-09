SCRIPT_PATH = "C:\\"
#Archaeo-Astro Insight#

#################################################
# Global parameters                            #
#################################################
QGIS_CRS = "EPSG:3857" #canvas coordinates
TARGET_CRS = "EPSG:4326" #coordinates of your map

RESULTS_PATH =''
PYTHON_PATH = ''
LINE_WIDTH = 0.7

SCRIPT_SLEEP = 10

DOWNLOAD_MAP = True 
MAP_TYPE = "mt1.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}"

#################################################
#sys.path.append(SCRIPT_PATH)
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
    def __init__(self, canvas, iface, plugin_dir, resultsPath, PythonPath, scriptSleep, lineWidth, downloadMap):
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
        # Batch mode state management
        self.batch_mode = False
        self.captured_objects = []  # List of tuples: ((point1, point2), (transformed1, transformed2), azimuth_or_none)
        # azimuth_or_none: float if provided/calculated, None if not yet calculated
        self.markers = []  # List of QgsVertexMarker objects for visualization
        self.cluster_results = []  # Store cluster calculation results
        self.batch_results = []  # Store batch (no clustering) calculation results
        self.cluster_layers = []  # List of QgsVectorLayer for cluster visualizations (not used anymore, kept for compatibility)
        self.clustering_method_name = 'dbscan'  # Default clustering method
        
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

        #print(point)
        #print(transformed_point)
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
        # Workflow: horizon profile (HeyWhatsThat) + already computed azimuth + location → declination.
        # 1. Azimuth is computed from the two points (observer → target). 2. Horizon profile gives
        # altitude at that azimuth. 3. Declination = f(altitude, azimuth, latitude) in utility.computeDeclination.
        if not self.batch_mode and len(self.pointList) == 2:
            self.handleRequest()
            self.iface.messageBar().clearWidgets()
            self.iface.messageBar().pushSuccess("Success","[HeyWhatsThat.com] response received")

            if (self.code == ""):
                return

            try:
                self.iface.messageBar().clearWidgets()
                self.iface.messageBar().pushMessage("Running horizon Python script, please wait....", Qgis.Info)
                self.handleScript()
                self.iface.messageBar().clearWidgets()
                self.iface.messageBar().pushSuccess("Success", "Horizon Python script finished successfully")

                self.decl = computeDeclination(self.altitude, self.az, self.transformedPoints)
                self.stars = checkDeclinationBSC5(self.decl, self.scriptPath)
                sunMoon = checkDeclinationSunMoon(self.decl)
                if sunMoon != "None":
                    self.stars.append(sunMoon)

                write_to_csv(self, self.scriptPath, self.transformedPoints[0].x(), self.transformedPoints[0].y(), self.az, self.altitude, self.decl, self.stars)
            except Exception as ex:
                import traceback
                traceback.print_exc()
                err_msg = str(ex)
                self.iface.messageBar().pushCritical(
                    "Single-object result failed",
                    "Error after HeyWhatsThat response: {} See Python console for details.".format(err_msg)
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

            
            #gLine = QgsGeometry.fromPolyline([QgsPoint(self.pointList[0].x(),self.pointList[0].y()), QgsPoint(self.pointList[1].x(),self.pointList[1].y())])
            #self.rubberBand.setToGeometry(gLine, None)
            #print(self.pointList)
    
    #send request for HeyWhatsThat.com code
    def handleRequest(self):
        self.iface.messageBar().pushMessage("Sending HTTP request to [HeyWhatsThat.com]. Please wait for the response.....", Qgis.Info, 2)
        point = QgsPoint(self.transformedPoints[0].x(),self.transformedPoints[0].y())
        #print(point)
        req = "http://heywhatsthat.com/bin/query.cgi?lat={0:.4f}&lon={1:.4f}&name={2}".format(self.transformedPoints[0].y(), self.transformedPoints[0].x(), "Horizon1")
        print(req) 
        #req_test = "http://heywhatsthat.com/bin/query.cgi?lat=44.297147&lon=69.129591&name={}".format("Horizon1")
        r = requests.get(req)
        #print(r)
        i = 0
        while r.text == "" and i <= 10:
            time.sleep(2)
            r = requests.get(req)
            print("[HeyWhatsThat.com] Waiting for server response, please wait...")
            i += 1
        print("[HeyWhatsThat.com] Horizon profile code is " + r.text.strip("\n"))
        self.code = r.text.strip("\n")
        
     
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
            labels = clustering_method.cluster(object_centroids, distance_threshold=distance_threshold)
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
    
    def calculate_single_object_orientation(self, object_id, obj_points, obj_transformed, azimuth, progress=None):
        """Calculate orientation and declination for a single object (classic flow, no clustering)."""
        # Use first point as location for horizon request (same as single-object mode)
        lat = obj_transformed[0].y()
        lon = obj_transformed[0].x()
        
        QCoreApplication.processEvents()
        if progress:
            progress.setLabelText(f"Requesting horizon data for object {object_id + 1}...")
            QCoreApplication.processEvents()
        
        req = "http://heywhatsthat.com/bin/query.cgi?lat={0:.4f}&lon={1:.4f}&name={2}".format(
            lat, lon, f"Object_{object_id}")
        
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
                print(f"Network error for object {object_id}: {e}")
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
        
        QCoreApplication.processEvents()
        if progress:
            progress.setLabelText(f"Calculating altitude for object {object_id + 1}...")
            QCoreApplication.processEvents()
        
        script_path = os.path.join(self.scriptPath, "script.py")
        if not os.path.exists(script_path):
            return None
        try:
            altitude = _run_horizon_script(script_path, code, azimuth)
        except Exception as e:
            print(f"Horizon script error for object {object_id}: {e}")
            return None
        
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
        }
    
    def process_batch_no_clustering(self):
        """Run classic declination computation for each captured object (no clustering)."""
        if len(self.captured_objects) == 0:
            self.iface.messageBar().pushWarning("Warning", "No objects captured. Capture objects or import from CSV first.")
            return
        
        self.iface.messageBar().pushMessage("Processing objects (no clustering)...", Qgis.Info, duration=2)
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
        if not self.batch_results:
            self.iface.messageBar().pushWarning(
                "No results",
                "Horizon data failed for all objects. Try a different location or try again in a minute (HeyWhatsThat may be busy)."
            )
            return
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
        """Save batch (no clustering) results to CSV."""
        if not self.batch_results:
            return
        global RESULTS_PATH
        if RESULTS_PATH == "Empty":
            RESULTS_PATH = os.getcwd()
        from qgis.PyQt.QtWidgets import QFileDialog
        from qgis.PyQt import QtGui
        logo_icon_path = ':/plugins/a2i/logo/icons/logo.png'
        filepath, _ = QFileDialog.getSaveFileName(
            None, "Save Batch Results", RESULTS_PATH, "Comma Separated Values Files (*.csv)")
        if not filepath:
            return
        all_rows = [['object_id', 'latitude', 'longitude', 'azimuth', 'altitude', 'declination', 'stars', 'comments']]
        for r in self.batch_results:
            stars_str = ', '.join(r['stars']) if r['stars'] else 'None'
            all_rows.append([
                r['object_id'], r['latitude'], r['longitude'], r['azimuth'],
                r['altitude'], r['declination'], stars_str, f"Object {r['object_id']}"
            ])
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                csv.writer(f, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL).writerows(all_rows)
            self.iface.messageBar().pushSuccess("Saved", f"Saved {len(self.batch_results)} objects to {os.path.basename(filepath)}")
            print(f"Saved batch results to {filepath}")
        except (IOError, Exception) as e:
            self.iface.messageBar().pushWarning("Save Error", str(e))
            print(f"Error saving batch results: {e}")
    
    def calculate_cluster_orientation(self, cluster_info, progress=None):
        """
        Calculate orientation and declination for a cluster.
        
        Workflow:
        1. Use the cluster's MEAN CENTROID to request ONE horizon profile from HeyWhatsThat.
        2. For EACH OBJECT in the cluster, use the object's own azimuth to interpolate
           altitude from that shared horizon profile, then compute declination individually.
        
        Returns a dict with cluster-level info and a list of per-object results.
        """
        centroid_lat = cluster_info['centroid_lat']
        centroid_lon = cluster_info['centroid_lon']
        objects = cluster_info['objects']
        cluster_id = cluster_info['cluster_id']
        
        # --- Step 1: Get horizon profile for the cluster centroid ---
        
        QCoreApplication.processEvents()
        if progress:
            progress.setLabelText(f"Requesting horizon data for cluster {cluster_id}...")
            QCoreApplication.processEvents()
        
        # Request HeyWhatsThat panorama code using cluster mean centroid
        req = "http://heywhatsthat.com/bin/query.cgi?lat={0:.4f}&lon={1:.4f}&name={2}".format(
            centroid_lat, centroid_lon, f"Cluster_{cluster_id}")
        
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
                print(f"Network error for cluster {cluster_id}: {e}")
                for _ in range(3):
                    QCoreApplication.processEvents()
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
        
        # Download the FULL horizon data (once for the whole cluster)
        QCoreApplication.processEvents()
        if progress:
            progress.setLabelText(f"Downloading horizon profile for cluster {cluster_id}...")
            QCoreApplication.processEvents()
        
        script_path = os.path.join(self.scriptPath, "script.py")
        if not os.path.exists(script_path):
            return None
        try:
            horizon_data = _download_horizon_data(script_path, code)
        except Exception as e:
            print(f"Horizon download error for cluster {cluster_id}: {e}")
            return None
        
        # --- Step 2: For each object, compute altitude + declination using its own azimuth ---
        
        QCoreApplication.processEvents()
        if progress:
            progress.setLabelText(f"Computing declinations for cluster {cluster_id} objects...")
            QCoreApplication.processEvents()
        
        object_results = []
        for item in objects:
            # item format: (global_index, centroid_data)
            # centroid_data: (centroid_lat, centroid_lon, obj_points, obj_transformed, azimuth_or_none)
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
                altitude = _horizon_altitude(script_path, horizon_data, obj_az)
            except Exception as e:
                print(f"Altitude interpolation error for object {global_idx} in cluster {cluster_id}: {e}")
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
                'object_id': global_idx,  # Global object ID (unique across all clusters)
                'latitude': obj_lat,
                'longitude': obj_lon,
                'azimuth': obj_az,
                'altitude': altitude,
                'declination': decl,
                'stars': stars,
            })
        
        if not object_results:
            return None
        
        return {
            'cluster_id': cluster_id,
            'centroid_lat': centroid_lat,
            'centroid_lon': centroid_lon,
            'num_objects': cluster_info['num_objects'],
            'object_results': object_results,  # Per-object declinations
        }
    
    def process_all_clusters(self):
        """Process all clusters and calculate results"""
        if len(self.captured_objects) == 0:
            self.iface.messageBar().pushWarning("Warning", "No objects captured. Please capture objects first.")
            return
        
        try:
            self.iface.messageBar().pushMessage("Processing clusters...", Qgis.Info, duration=3)
            
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
                self.iface.messageBar().pushWarning(
                    "No results",
                    "Horizon data failed for all clusters. Try a different location or try again in a minute (HeyWhatsThat may be busy)."
                )
                return
            
            # Display results
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
        """Save per-object cluster results to a single CSV file."""
        if not self.cluster_results:
            return
        
        global RESULTS_PATH
        if RESULTS_PATH == "Empty":
            RESULTS_PATH = os.getcwd()
        
        from qgis.PyQt.QtWidgets import QFileDialog
        
        filepath, _ = QFileDialog.getSaveFileName(
            None,
            "Save Cluster Results",
            RESULTS_PATH,
            "Comma Separated Values Files (*.csv)"
        )
        
        if not filepath:
            return  # User cancelled
        
        # Header: each row is one object, grouped under its cluster
        all_rows = [['cluster_id', 'object_id', 'centroid_lat', 'centroid_lon',
                     'object_lat', 'object_lon', 'azimuth', 'altitude',
                     'declination', 'stars', 'comments']]
        
        for cr in self.cluster_results:
            cluster_id = cr['cluster_id']
            centroid_lat = cr['centroid_lat']
            centroid_lon = cr['centroid_lon']
            for obj_r in cr['object_results']:
                stars_str = ', '.join(obj_r['stars']) if obj_r['stars'] else 'None'
                all_rows.append([
                    cluster_id,
                    obj_r['object_id'],
                    centroid_lat,
                    centroid_lon,
                    obj_r['latitude'],
                    obj_r['longitude'],
                    obj_r['azimuth'],
                    obj_r['altitude'],
                    obj_r['declination'],
                    stars_str,
                    f'Cluster {cluster_id}, object {obj_r["object_id"]}'
                ])
        
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as file:
                data_writer = csv.writer(file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
                data_writer.writerows(all_rows)
            
            total_objects = sum(len(cr['object_results']) for cr in self.cluster_results)
            num_clusters = len(self.cluster_results)
            self.iface.messageBar().pushSuccess("Saved",
                f"Saved {total_objects} objects across {num_clusters} clusters to {os.path.basename(filepath)}")
            print(f"Saved {total_objects} objects across {num_clusters} clusters to {filepath}")
        except Exception as e:
            self.iface.messageBar().pushWarning("Save Error", f"Failed to save: {e}")
            print(f"Error saving cluster results: {e}")
    
    
    def clear_captured_points(self):
        """Clear all captured objects and markers"""
        self.captured_objects = []
        self.cluster_results = []
        self.batch_results = []
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
def write_to_csv(self, scriptPath, xcoord, ycoord, azimuth, altitude, declination, stars):
    global RESULTS_PATH
    if stars:
        starsString = ', '.join(stars)
    else:
        starsString = ''

    data = []
    data.append(ycoord)
    data.append(xcoord)
    data.append(azimuth)
    data.append(altitude)
    data.append(declination)
    data.append(starsString)

    if (starsString == ''):
        starsString = 'None'

    messageString = "The bearing of the line is: Az: " + str(azimuth) + " Alt: " + str(altitude) + " Declination: " + str(declination) + " pointing to: " + starsString 
    print(messageString)
    self.iface.messageBar().pushMessage("Result", messageString, Qgis.Info)

    if RESULTS_PATH == "Empty":
        RESULTS_PATH = os.getcwd()

    save = Ui_Save(data, RESULTS_PATH, os.path.join(scriptPath, "save_data.ui"))
    save.setWindowIcon(QtGui.QIcon(':/plugins/a2i/logo/icons/logo.png'))
    save.exec()
    
def zoom_to_coords():
    qid = QInputDialog()
    qid.setWindowIcon(QtGui.QIcon(logo_icon_path))
    canvas = iface.mapCanvas()
    input, ok = QInputDialog.getText( qid, "Enter Coordinates", "Enter New Coordinates as 'x.xxx, y.yyy'", QLineEdit.Normal, "lat" + "," + "long")
    if ok:
        y = input.split( "," )[ 0 ]
        #print (y)
        x = input.split( "," )[ 1 ]
        #print (x)
        while (y == "lat" or x == "long") and ok:
            input, ok = QInputDialog.getText( qid, "Enter Coordinates", "Enter New Coordinates as 'x.xxx,y.yyy'", QLineEdit.Normal, "lat" + "," + "long")
            if ok:
                y = input.split( "," )[ 0 ]
                x = input.split( "," )[ 1 ]
        if ok:
            point = QgsPointXY(float(x), float(y))
            tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem(QGIS_CRS), QgsCoordinateReferenceSystem(TARGET_CRS), QgsProject.instance())
            transformed_point = tr.transform(point, QgsCoordinateTransform.ReverseTransform)
            x = transformed_point.x()
            y = transformed_point.y()
            if not x:
                print ("x value is missing!")
            if not y:
                print ("y value is missing!")
            scale=200
            #print(x)
            #print(y)
            rect = QgsRectangle(x-scale,y-scale,x+scale,y+scale)
            canvas.setExtent(rect)
            canvas.refresh()

def azimuth_tool():
    iface.mapCanvas().setMapTool( canvas_clicked )

def rmvLyr(lyrname):
    qinst = QgsProject.instance()
    layers = qinst.mapLayersByName(lyrname)
    if layers:
        qinst.removeMapLayer(layers[0].id())

def set_params():

    change = False

    ui = Ui_Dialog(SCRIPT_PATH)
    ui.setWindowIcon(QtGui.QIcon(logo_icon_path))
    ui.exec()

    with open(config_path, 'r') as f:
        #SCRIPT_PATH = f.readline().rstrip("\n")
        f.readline()
        RESULTS_PATH = f.readline().rstrip("\n")
        PYTHON_PATH = f.readline().rstrip("\n")

        if f.readline().rstrip("\n") == "Yes":
            DOWNLOAD_MAP = True
            mapType = f.readline().rstrip("\n")
            
            if mapType == "Roadmap":
                if MAP_TYPE != "mt1.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}":
                    change = True
                MAP_TYPE = "mt1.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}"
            elif mapType == "Terrain":
                if MAP_TYPE != "mt1.google.com/vt/lyrs=p&hl=en&x={x}&y={y}&z={z}":
                    change = True
                MAP_TYPE = "mt1.google.com/vt/lyrs=p&hl=en&x={x}&y={y}&z={z}"
            elif mapType == "Satellite":
                if MAP_TYPE != "mt1.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}":
                    change = True
                MAP_TYPE = "mt1.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}"
            elif mapType == "Hybrid":
                if MAP_TYPE != "mt1.google.com/vt/lyrs=y&hl=en&x={x}&y={y}&z={z}":
                    change = True
                MAP_TYPE = "mt1.google.com/vt/lyrs=y&hl=en&x={x}&y={y}&z={z}"
            else:
                DOWNLOAD_MAP = False
                f.readline()

        LINE_WIDTH = float(f.readline().rstrip("\n"))
        SCRIPT_SLEEP = float(f.readline().rstrip("\n"))

    if change:
        rmvLyr("Google Sat")
        service_url = MAP_TYPE
        service_uri = "type=xyz&zmin=0&zmax=21&url=https://"+requests.utils.quote(service_url)
        iface.addRasterLayer(service_uri, "Google Sat", "wms")


#'Main' code, executed first when you run the script
def initA2i(scriptPath, iface):
    #Print empty line between console ouputs
    print('\n')
    SCRIPT_PATH = scriptPath

    #Set paths to useful files
    config_path = os.path.join(SCRIPT_PATH, "config.txt")
    ui_path = os.path.join(SCRIPT_PATH, "dialog.ui")
    save_path = os.path.join(SCRIPT_PATH, "save_data.ui")
    tool_icon_path = ':/plugins/a2i/toolbar/icons/bearing.png'
    location_icon_path = ':/plugins/a2i/toolbar/icons/location.png'
    params_icon_path = ':/plugins/a2i/toolbar/icons/settings.png'
    logo_icon_path = ':/plugins/a2i/logo/icons/logo.png'

    #Read config file
    with open(config_path, 'r') as f:
        #SCRIPT_PATH = f.readline().rstrip("\n")
        f.readline()
        RESULTS_PATH = f.readline().rstrip("\n")
        PYTHON_PATH = f.readline().rstrip("\n")

        if f.readline().rstrip("\n") == "Yes":
            DOWNLOAD_MAP = True
            mapType = f.readline().rstrip("\n")
            if mapType == "Roadmap":
                MAP_TYPE = "mt1.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}"
            elif mapType == "Terrain":
                MAP_TYPE = "mt1.google.com/vt/lyrs=p&hl=en&x={x}&y={y}&z={z}"
            elif mapType == "Satellite":
                MAP_TYPE = "mt1.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}"
            elif mapType == "Hybrid":
                MAP_TYPE = "mt1.google.com/vt/lyrs=y&hl=en&x={x}&y={y}&z={z}"
            else:
                DOWNLOAD_MAP = False
                f.readline()

        LINE_WIDTH = float(f.readline().rstrip("\n"))
        SCRIPT_SLEEP = float(f.readline().rstrip("\n"))

    #Set the first too as the pan tool
    iface.actionPan().trigger()

    #Deal with map download and type
    if DOWNLOAD_MAP:
        service_url = MAP_TYPE
        service_uri = "type=xyz&zmin=0&zmax=21&url=https://"+requests.utils.quote(service_url)
        #print ("YES!")

        if QgsProject.instance().mapLayersByName("Google Sat"):
            print("Google image is already loaded!")
        else:
            iface.addRasterLayer(service_uri, "Google Sat", "wms")

    #Initialize the tool
    canvas_clicked = DeclinationTool(iface.mapCanvas(), iface)

    #Set the buttons on the toolbar
    action_tool = QAction(QIcon(tool_icon_path), 'Start Tool')
    action_tool.triggered.connect(azimuth_tool)
    iface.addToolBarIcon(action_tool)

    action_zoom = QAction(QIcon(location_icon_path), 'Go to Coords')
    action_zoom.triggered.connect(zoom_to_coords)
    iface.addToolBarIcon(action_zoom)

    set_parameters = QAction(QIcon(params_icon_path), 'Set Params')
    set_parameters.triggered.connect(set_params)
    iface.addToolBarIcon(set_parameters)

    print ('OK')



	  	