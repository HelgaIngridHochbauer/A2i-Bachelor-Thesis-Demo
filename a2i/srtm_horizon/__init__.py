# SRTM-based horizon profile computation module
#
# Pipeline:
#   1. convert_srtm_to_xyz.py  - Extract lon/lat/elev from SRTM raster tiles
#   2. calculate_horizon_topography_new.cpp - Compute azimuth/dip/distance (C++ with OpenMP)
#   3. aggregate_horizon.py    - Aggregate C++ output into a horizon profile
