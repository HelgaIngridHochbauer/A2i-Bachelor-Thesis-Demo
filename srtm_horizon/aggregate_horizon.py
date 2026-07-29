"""
Python translation of horizon_dip_angle.R

Reads the C++ horizon topography output (azimuth, dip_angle, distance) and
aggregates by azimuth bins, taking the **maximum** dip angle per bin to
produce the final horizon profile.

The result is a list of {az, alt} dicts identical in structure to what
script.py produces from HeyWhatsThat data, so the rest of the plugin
(declination calculation, star matching) works unchanged.

Original R script by Sherry Towers (smtowers@asu.edu), Nov 2013.
Python port for the A2i QGIS plugin.
"""
import numpy as np


def aggregate_horizon_profile(input_file, az_bin_size=0.1):
    """
    Read the C++ horizon calculator output and aggregate.

    The C++ program writes lines of the form::

        azimuth  dip_angle  distance_km

    with a header line ``azimuth dip distance``.

    For each azimuth bin (floor to *az_bin_size* degrees) we keep the
    **maximum** dip angle -- that is the visible horizon at that bearing.

    Parameters:
        input_file : str
            Path to the C++ output file.
        az_bin_size : float
            Azimuth bin width in degrees (default 0.1, matching the R script's
            ``as.integer(azimuth*10)/10``).

    Returns:
        list[dict]
            ``[{'az': float, 'alt': float}, ...]`` sorted by azimuth, ready for
            ``interpolate_altitude()`` or the existing ``hor2alt()`` logic.
    """
    azimuths = []
    dips = []

    with open(input_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Skip header line (starts with a letter)
            if line[0].isalpha():
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                azimuths.append(float(parts[0]))
                dips.append(float(parts[1]))
            except ValueError:
                continue

    if not azimuths:
        raise ValueError("No valid data found in {}".format(input_file))

    az_arr = np.array(azimuths)
    dip_arr = np.array(dips)

    print("[SRTM] C++ output: {} data points, azimuth range [{:.1f}, {:.1f}], "
          "dip range [{:.3f}, {:.3f}]".format(
              len(az_arr), float(np.min(az_arr)), float(np.max(az_arr)),
              float(np.min(dip_arr)), float(np.max(dip_arr))))

    # Bin azimuths: floor to az_bin_size
    # (matches R: as.integer(azimuth*10)/10 when az_bin_size=0.1)
    az_binned = np.floor(az_arr / az_bin_size) * az_bin_size

    # Aggregate: keep max dip per bin (= the horizon)
    unique_bins = np.unique(az_binned)
    horizon = []
    for az_bin in unique_bins:
        mask = az_binned == az_bin
        max_dip = float(np.max(dip_arr[mask]))
        horizon.append({'az': float(az_bin), 'alt': max_dip})

    horizon.sort(key=lambda d: d['az'])

    # Diagnostic: show max altitude at a few sample azimuths
    sample_azs = [0, 45, 74, 90, 135, 180, 225, 270, 315]
    print("[SRTM] Horizon profile sample (max altitude at key azimuths):")
    for saz in sample_azs:
        nearby = [h for h in horizon if abs(h['az'] - saz) < 1.0]
        if nearby:
            best = max(nearby, key=lambda h: h['alt'])
            print("  Az {:.0f}°: max alt = {:.3f}°".format(saz, best['alt']))

    return horizon


def interpolate_altitude(horizon_data, target_azimuth):
    """
    Interpolate altitude (dip angle) at a given azimuth from the horizon
    profile.  Uses the same circular-wrapping linear interpolation as
    ``hor2alt()`` in ``script.py``.

    Parameters:
        horizon_data : list[dict]
            Output of ``aggregate_horizon_profile()``.
        target_azimuth : float
            Azimuth in degrees (0-360).

    Returns: 
        float
            Interpolated altitude (horizon dip angle) in degrees, rounded to 2 decimals.
    """
    az_values = [d['az'] for d in horizon_data]
    alt_values = [d['alt'] for d in horizon_data]

    # Extend with ±360 for circular wrapping
    az_ext = ([a - 360 for a in az_values] + az_values +
              [a + 360 for a in az_values])
    alt_ext = alt_values * 3

    # Linear interpolation
    for i in range(len(az_ext) - 1):
        if az_ext[i] <= target_azimuth <= az_ext[i + 1]:
            if az_ext[i + 1] == az_ext[i]:
                return round(alt_ext[i], 2)
            t = ((target_azimuth - az_ext[i]) /
                 (az_ext[i + 1] - az_ext[i]))
            return round(alt_ext[i] + t * (alt_ext[i + 1] - alt_ext[i]), 2)

    # Fallback: closest value
    closest_idx = min(range(len(az_ext)),
                      key=lambda idx: abs(az_ext[idx] - target_azimuth))
    return round(alt_ext[closest_idx], 2)
