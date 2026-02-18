"""
High-level SRTM horizon pipeline.

Orchestrates the three stages:
    1. convert_srtm_to_xyz  – extract lon/lat/elev from SRTM raster tiles
    2. C++ horizon calculator – compute azimuth / dip-angle / distance
    3. aggregate_horizon     – bin and aggregate into a horizon profile

The public function ``compute_srtm_horizon()`` returns a dict in the same
format as ``script.download_hwt()``, so the rest of the plugin (declination,
star matching) works unchanged regardless of the data source.
"""
import os
import sys
import time
import tempfile
import subprocess

from .convert_srtm_to_xyz import convert_srtm_to_xyz
from .aggregate_horizon import aggregate_horizon_profile, interpolate_altitude


# Observer height above ground (metres) added to SRTM ground elevation
_OBSERVER_HEIGHT = 2.0


def _find_cpp_executable(plugin_dir):
    """
    Locate the compiled C++ horizon calculator.

    Search order:
        1. srtm_horizon/ folder inside the plugin directory
        2. plugin directory itself

    Returns the absolute path, or None if not found.
    """
    exe_name = 'horizon_calc.exe' if sys.platform == 'win32' else 'horizon_calc'
    srtm_dir = os.path.join(plugin_dir, 'srtm_horizon')
    candidates = [
        os.path.join(srtm_dir, exe_name),
        os.path.join(plugin_dir, exe_name),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def compute_srtm_horizon(latitude, longitude, srtm_folder, plugin_dir,
                          target_azimuth=-1, on_waiting=None):
    """
    Run the full SRTM-based horizon pipeline for a given observer location.

    Parameters
    ----------
    latitude, longitude : float
        Observer position in decimal degrees (EPSG:4326).
    srtm_folder : str
        Path to the folder containing SRTM raster tiles.
    plugin_dir : str
        Path to the a2i plugin directory (used to find the C++ executable).
    target_azimuth : float
        If >= 0, only compute terrain along this azimuth (speed optimisation).
        Use -1 (default) for a full 360-degree profile.
    on_waiting : callable or None
        Optional ``callback(message)`` for progress feedback.

    Returns
    -------
    dict
        ``{'data': [{'az': float, 'alt': float}, ...],
           'metadata': {'source': 'SRTM', 'elevation': float}}``
        Compatible with the HeyWhatsThat ``hor`` dict consumed by the rest
        of the plugin.
    """
    pipeline_start = time.time()
    print("[SRTM] ===== Starting SRTM horizon pipeline =====")
    print("[SRTM] Observer: ({:.5f}, {:.5f})".format(latitude, longitude))
    print("[SRTM] SRTM folder: {}".format(srtm_folder))

    # --- Locate the compiled C++ executable ---
    cpp_exe = _find_cpp_executable(plugin_dir)
    if cpp_exe is None:
        raise FileNotFoundError(
            "Compiled horizon calculator not found. "
            "Please compile calculate_horizon_topography_new.cpp and place "
            "the executable (horizon_calc) in the srtm_horizon/ folder."
        )
    print("[SRTM] C++ executable: {}".format(cpp_exe))

    # --- Stage 1: SRTM raster → XYZ text file ---
    if on_waiting:
        on_waiting("[SRTM] Stage 1/3: Extracting elevation data from SRTM tiles...")
    t1 = time.time()
    print("[SRTM] Stage 1/3: Extracting elevation from SRTM tiles...")

    xyz_file = tempfile.mktemp(prefix='a2i_xyz_', suffix='.txt')
    try:
        observer_ground_elev = convert_srtm_to_xyz(
            latitude, longitude, srtm_folder, xyz_file)
    except Exception as e:
        _cleanup(xyz_file)
        raise RuntimeError(
            "SRTM tile extraction failed: {}".format(e)) from e

    observer_elev = observer_ground_elev + _OBSERVER_HEIGHT
    xyz_size = os.path.getsize(xyz_file) if os.path.exists(xyz_file) else 0
    t1_elapsed = time.time() - t1
    print("[SRTM] Stage 1 done in {:.1f}s — observer elevation: {:.1f}m "
          "(+{:.0f}m height = {:.1f}m), XYZ file: {:.1f} MB".format(
              t1_elapsed, observer_ground_elev, _OBSERVER_HEIGHT,
              observer_elev, xyz_size / 1048576.0))

    # --- Stage 2: Run C++ horizon calculator ---
    if on_waiting:
        on_waiting("[SRTM] Stage 2/3: Computing horizon topography (C++)...")
    t2 = time.time()
    print("[SRTM] Stage 2/3: Running C++ horizon calculator...")

    cpp_output_file = tempfile.mktemp(prefix='a2i_hor_', suffix='.txt')
    try:
        args = [
            cpp_exe,
            '0',                        # seed
            str(latitude),
            str(longitude),
            str(observer_elev),
            xyz_file,
        ]
        if target_azimuth >= 0:
            args.append(str(target_azimuth))

        creation_flags = 0
        if sys.platform == 'win32':
            creation_flags = getattr(subprocess, 'CREATE_NO_WINDOW',
                                     0x08000000)

        with open(cpp_output_file, 'w') as out_f:
            result = subprocess.run(
                args,
                stdout=out_f,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300,
                creationflags=creation_flags,
            )
        if result.returncode != 0:
            raise RuntimeError(
                "C++ horizon calculator failed (exit {}): {}".format(
                    result.returncode, result.stderr))
    except subprocess.TimeoutExpired:
        _cleanup(xyz_file, cpp_output_file)
        raise RuntimeError(
            "C++ horizon calculator timed out (>5 min). "
            "The SRTM area may be too large.")
    except Exception as e:
        _cleanup(xyz_file, cpp_output_file)
        raise

    cpp_size = os.path.getsize(cpp_output_file) if os.path.exists(
        cpp_output_file) else 0
    t2_elapsed = time.time() - t2
    print("[SRTM] Stage 2 done in {:.1f}s — C++ output: {:.1f} MB".format(
        t2_elapsed, cpp_size / 1048576.0))

    # --- Stage 3: Aggregate C++ output into horizon profile ---
    if on_waiting:
        on_waiting("[SRTM] Stage 3/3: Aggregating horizon profile...")
    t3 = time.time()
    print("[SRTM] Stage 3/3: Aggregating horizon profile...")

    try:
        horizon = aggregate_horizon_profile(cpp_output_file)
    except Exception as e:
        _cleanup(xyz_file, cpp_output_file)
        raise RuntimeError(
            "Horizon aggregation failed: {}".format(e)) from e

    t3_elapsed = time.time() - t3
    total_elapsed = time.time() - pipeline_start
    print("[SRTM] Stage 3 done in {:.1f}s — {} azimuth bins".format(
        t3_elapsed, len(horizon)))
    print("[SRTM] ===== SRTM pipeline complete in {:.1f}s =====".format(
        total_elapsed))

    # Clean up temp files
    _cleanup(xyz_file, cpp_output_file)

    return {
        'data': horizon,
        'metadata': {
            'source': 'SRTM',
            'elevation': observer_ground_elev,
        },
    }


def srtm_hor2alt(hor, azimuth):
    """
    Interpolate altitude at *azimuth* from an SRTM horizon profile.

    Drop-in replacement for ``script.hor2alt()``.

    Parameters
    ----------
    hor : dict
        Horizon dict returned by ``compute_srtm_horizon()``.
    azimuth : float
        Azimuth in degrees (0-360).

    Returns
    -------
    float
        Altitude (dip angle) in degrees, rounded to 2 decimals.
    """
    return interpolate_altitude(hor['data'], azimuth)


def _cleanup(*paths):
    """Silently remove temporary files."""
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except Exception:
            pass
