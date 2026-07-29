#!/usr/bin/env python3
"""
Python version of script.R
Downloads horizon data from HeyWhatsThat.com and calculates altitude for a given azimuth.
"""

import sys
import os
import re
import csv
import math
import time
import tempfile
import urllib.request
import urllib.parse


def _notify(on_waiting, msg):
    """Call optional callback and allow UI to update."""
    if on_waiting:
        try:
            on_waiting(msg)
        except Exception:
            pass


def download_hwt(hwt_id, on_waiting=None):
    """
    Download horizon data from HeyWhatsThat.com.
    HeyWhatsThat can take up to ~2 minutes to generate a panorama.

    Args:
        hwt_id: 8-character HeyWhatsThat ID
        on_waiting: Optional callback(message: str) called while waiting, so the UI can show progress.

    Returns:
        dict: Dictionary containing metadata and horizon data
    """
    if len(hwt_id) != 8:
        raise ValueError('Incorrect HeyWhatsThat ID.')

    hor = {}
    lat, lon, elev, name = 0.0, 0.0, 0.0, "Unknown"

    # Request HTML first: server may need this to generate the panorama before CSV is ready
    try:
        _notify(on_waiting, "Requesting HeyWhatsThat panorama (can take up to 2 minutes)...")
        pan_url = f'http://www.heywhatsthat.com/iphone/pan.cgi?id={hwt_id}'
        req_pan = urllib.request.Request(pan_url, headers={'User-Agent': 'Mozilla/5.0 (compatible; A2i/1.0)'})
        with urllib.request.urlopen(req_pan, timeout=15) as resp:
            resp.read()
        _notify(on_waiting, "Still waiting for HeyWhatsThat... (preparing horizon data)")
        time.sleep(6)
    except Exception:
        pass

    temp_dir = tempfile.gettempdir()
    csv_file = os.path.join(temp_dir, f"{hwt_id}.csv")
    csv_url = f'http://www.heywhatsthat.com/api/horizon.csv?id={hwt_id}&resolution=.125'

    def fetch_csv():
        """Fetch CSV; returns True if data was written, False if response was empty."""
        csv_files = [f for f in os.listdir(temp_dir) if f.endswith('.csv') and len(f) >= 8]
        if len(csv_files) > 500:
            file_times = [(f, os.path.getmtime(os.path.join(temp_dir, f))) for f in csv_files]
            file_times.sort(key=lambda x: x[1])
            oldest_id = file_times[0][0][:8]
            for f in os.listdir(temp_dir):
                if f.startswith(oldest_id):
                    try:
                        os.remove(os.path.join(temp_dir, f))
                    except Exception:
                        pass
        req = urllib.request.Request(csv_url, headers={'User-Agent': 'Mozilla/5.0 (compatible; A2i/1.0)'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
        if not raw:
            return False
        with open(csv_file, 'wb') as f:
            f.write(raw)
        return True

    def read_horizon_csv(path):
        data = []
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(row)
        return data

    # Wait up to ~2 minutes with retries every 10 s; notify user so they know we're still working
    MAX_WAIT_SEC = 130
    RETRY_INTERVAL_SEC = 10

    def fetch_csv_with_retries():
        """Fetch CSV with retries; HeyWhatsThat can take up to ~2 min to generate the panorama."""
        attempt = 0
        start = time.time()
        while (time.time() - start) < MAX_WAIT_SEC:
            if fetch_csv():
                return
            attempt += 1
            elapsed = int(time.time() - start)
            _notify(
                on_waiting,
                "Still waiting for HeyWhatsThat... (retry {} in {} s, {} s elapsed)".format(
                    attempt, RETRY_INTERVAL_SEC, elapsed
                ),
            )
            time.sleep(RETRY_INTERVAL_SEC)
        raise ValueError(
            "HeyWhatsThat returned empty horizon data after ~2 minutes. "
            "The panorama may still be generating, or the service may be temporarily unavailable."
        )

    existing_files = [f for f in os.listdir(temp_dir) if f.startswith(hwt_id) and f.endswith('.csv')]
    if not existing_files:
        _notify(on_waiting, "Requesting horizon data from HeyWhatsThat...")
        fetch_csv_with_retries()
    else:
        try:
            with open(csv_file, 'rb') as f:
                peek = f.read(200)
            if not peek or peek.strip().startswith(b'<'):
                _notify(on_waiting, "Re-requesting horizon data from HeyWhatsThat...")
                fetch_csv_with_retries()
        except Exception:
            _notify(on_waiting, "Re-requesting horizon data from HeyWhatsThat...")
            fetch_csv_with_retries()

    horizon_data = read_horizon_csv(csv_file)

    # If no rows, wait and re-fetch (server may still be generating the panorama)
    if not horizon_data:
        try:
            os.remove(csv_file)
        except Exception:
            pass
        _notify(on_waiting, "Still waiting for HeyWhatsThat... (horizon data empty, retrying)")
        time.sleep(RETRY_INTERVAL_SEC)
        fetch_csv_with_retries()
        horizon_data = read_horizon_csv(csv_file)

    if not horizon_data:
        with open(csv_file, 'rb') as f:
            raw = f.read(800)
        if raw.strip().startswith(b'<'):
            raise ValueError(
                "HeyWhatsThat returned an error page instead of horizon data. "
                "The site may be down or the location ID expired. Try again later."
            )
        # Log sample for debugging (first 400 bytes as text)
        sample = raw[:400].decode('utf-8', errors='replace').replace('\r', ' ').replace('\n', ' ')
        print(f"[A2i] Horizon CSV sample (no data rows): {sample!r}")
        raise ValueError(
            "No horizon data found in CSV (empty or invalid). "
            "HeyWhatsThat may still be computing the panorama, or the location is unsupported. Try again in a minute."
        )
    
    # Altitude error (9.73m for SRTM)
    delta = 9.73
    distance_col = None
    for key in horizon_data[0].keys():
        if 'distance' in key.lower():
            distance_col = key
            break
    if distance_col is None:
        raise ValueError("Could not find distance column in CSV")
    
    for row in horizon_data:
        hor_alt = float(row['altitude'])
        distance = float(row[distance_col])
        delta_elev = distance * math.tan(math.radians(hor_alt))
        aux0 = math.degrees(math.atan(delta_elev / distance))
        aux1 = math.degrees(math.atan((delta_elev + delta) / distance))
        aux2 = math.degrees(math.atan((delta_elev - delta) / distance))
        row['error'] = (abs(aux1 - aux0) + abs(aux2 - aux0)) / 2.0
    
    # Azimuth column (bin.bottom or similar)
    bin_col = None
    for key in horizon_data[0].keys():
        if 'bin' in key.lower() and 'bottom' in key.lower():
            bin_col = key
            break
    if bin_col is None:
        for key in ['bin.bottom', 'bin_bottom', 'azimuth', 'az']:
            if key in horizon_data[0]:
                bin_col = key
                break
    if bin_col is None:
        raise ValueError("Could not find bin.bottom/azimuth column in CSV")
    
    hor['data'] = []
    for row in horizon_data:
        hor['data'].append({
            'az': float(row[bin_col]),
            'alt': float(row['altitude']),
            'alt.unc': row.get('error', 0.0)
        })
    
    # Optional: try to parse metadata from HTML (site layout may change)
    try:
        url = f"http://www.heywhatsthat.com/iphone/pan.cgi?id={hwt_id}"
        with urllib.request.urlopen(url, timeout=10) as response:
            html_content = response.read().decode('utf-8')
        pattern = r'<div class="details_data">([^<]*)</div>'
        matches = re.findall(pattern, html_content)
        if len(matches) >= 4:
            lat_str, lon_str, elev_str = matches[0], matches[1], matches[3]
            lat_m = re.search(r'([\d.]+)', lat_str)
            if lat_m:
                lat = float(lat_m.group(1))
                if 'S' in lat_str:
                    lat = -lat
            lon_m = re.search(r'([\d.]+)', lon_str)
            if lon_m:
                lon = float(lon_m.group(1))
                if 'W' in lon_str:
                    lon = -lon
            elev_m = re.search(r'([\d.]+)', elev_str)
            if elev_m:
                elev = float(elev_m.group(1))
        name_pattern = r'<div id="pan_top_title"[^>]*>([^<]*)</div>'
        name_match = re.search(name_pattern, html_content)
        if name_match:
            name = name_match.group(1).strip()
    except Exception:
        pass  # Keep defaults; hor2alt only uses hor['data']
    
    hor['metadata'] = {
        'ID': hwt_id,
        'name': name,
        'georef': {'Lat': lat, 'Lon': lon, 'Elev': elev},
        'elevation': elev
    }
    
    return hor


def hor2alt(hor, az):
    """
    Interpolate altitude for a given azimuth from horizon data
    
    Args:
        hor: Horizon data dictionary
        az: Azimuth in degrees
        
    Returns:
        float: Altitude in degrees
    """
    # Prepare data for interpolation
    az_values = [d['az'] for d in hor['data']]
    alt_values = [d['alt'] for d in hor['data']]
    
    # Create extended arrays for wrapping (az-360, az, az+360)
    az_extended = [a - 360 for a in az_values] + az_values + [a + 360 for a in az_values]
    alt_extended = alt_values * 3
    
    # Interpolate
    if az < min(az_extended) or az > max(az_extended):
        # Find closest value
        closest_idx = min(range(len(az_extended)), key=lambda i: abs(az_extended[i] - az))
        alt = alt_extended[closest_idx]
    else:
        # Linear interpolation
        for i in range(len(az_extended) - 1):
            if az_extended[i] <= az <= az_extended[i + 1]:
                # Linear interpolation
                t = (az - az_extended[i]) / (az_extended[i + 1] - az_extended[i])
                alt = alt_extended[i] + t * (alt_extended[i + 1] - alt_extended[i])
                break
        else:
            # Fallback to closest value
            closest_idx = min(range(len(az_extended)), key=lambda i: abs(az_extended[i] - az))
            alt = alt_extended[closest_idx]
    
    return round(alt, 2)


def main():
    """Main function to process command line arguments and output result"""
    if len(sys.argv) < 3:
        print("Usage: script.py <HWTID> <azimuth>", file=sys.stderr)
        sys.exit(1)
    
    hwt_id = sys.argv[1]
    azimuth = float(sys.argv[2])
    
    try:
        hor = download_hwt(hwt_id)
        output = hor2alt(hor, azimuth)
        print(output)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

