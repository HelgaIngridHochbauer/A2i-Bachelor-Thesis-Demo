# CSV Import Format Guide

This guide explains how to format CSV files for importing objects into the ArchaeoAstroInsight plugin clustering feature.

## Overview

The CSV import feature allows you to import objects (defined by two points) from a CSV file instead of clicking manually on the map. This is useful for:
- Batch importing data collected elsewhere
- Using pre-calculated azimuths (if available)
- Working with external datasets or survey data
- Reusing previously exported data

## CSV File Structure

### Required Columns

Your CSV file **must** contain the following columns (or variations):

1. **First Point Coordinates:**
   - `lat1` (or `latitude1`, `lat_1`) - Latitude of first point
   - `lon1` (or `longitude1`, `lon_1`, `lng1`) - Longitude of first point

2. **Second Point Coordinates:**
   - `lat2` (or `latitude2`, `lat_2`) - Latitude of second point
   - `lon2` (or `longitude2`, `lon_2`, `lng2`) - Longitude of second point

### Optional Columns

- **`azimuth`** (or `az`, `bearing`) - Pre-calculated azimuth in degrees (0-360)
  - If provided, this azimuth will be used directly (skips recalculation)
  - If not provided, azimuth will be automatically calculated from the two points
  - Must be between 0-360 degrees

## Supported Column Name Variations

The import function recognizes these column name variations:

| Purpose | Supported Names |
|---------|----------------|
| Latitude 1 | `lat1`, `latitude1`, `lat_1` |
| Longitude 1 | `lon1`, `longitude1`, `lon_1`, `lng1` |
| Latitude 2 | `lat2`, `latitude2`, `lat_2` |
| Longitude 2 | `lon2`, `longitude2`, `lon_2`, `lng2` |
| Azimuth | `azimuth`, `az`, `bearing` |

## Coordinate System

- **CRS**: All coordinates must be in **EPSG:4326** (WGS84)
- **Format**: Decimal degrees
- **Latitude range**: -90 to +90
- **Longitude range**: -180 to +180

**Examples:**
- ✅ `45.1234` (correct - decimal degrees)
- ❌ `45°12'34"` (incorrect - degrees/minutes/seconds not supported)
- ❌ `451234` (incorrect - needs decimal point)

## CSV Format Examples

### Example 1: With Header and Azimuth

```csv
lat1,lon1,lat2,lon2,azimuth
45.1234,-73.5678,45.1240,-73.5680,45.5
45.1300,-73.5700,45.1305,-73.5705,46.2
45.1400,-73.5800,45.1405,-73.5805,47.8
```

### Example 2: With Header, No Azimuth

```csv
latitude1,longitude1,latitude2,longitude2
45.1234,-73.5678,45.1240,-73.5680
45.1300,-73.5700,45.1305,-73.5705
45.1400,-73.5800,45.1405,-73.5805
```

Azimuths will be automatically calculated from the points.

### Example 3: Without Header (Positional)

If your CSV has no header row, the import will use the first 4-5 columns:

```csv
45.1234,-73.5678,45.1240,-73.5680,45.5
45.1300,-73.5700,45.1305,-73.5705,46.2
45.1400,-73.5800,45.1405,-73.5805,47.8
```

Column order: `lat1, lon1, lat2, lon2, [azimuth]`

### Example 4: Mixed Azimuths (Some Provided, Some Missing)

```csv
lat1,lon1,lat2,lon2,azimuth
45.1234,-73.5678,45.1240,-73.5680,45.5
45.1300,-73.5700,45.1305,-73.5705,
45.1400,-73.5800,45.1405,-73.5805,47.8
```

- Row 1: Uses provided azimuth (45.5°)
- Row 2: Azimuth will be calculated from points
- Row 3: Uses provided azimuth (47.8°)

### Example 5: Alternative Column Names

```csv
lat_1,lon_1,lat_2,lon_2,bearing
45.1234,-73.5678,45.1240,-73.5680,45.5
45.1300,-73.5700,45.1305,-73.5705,46.2
```

## How to Use CSV Import

1. **Prepare your CSV file** following the format above
2. **In QGIS**, click the **"A2i import from CSV"** toolbar button
3. **Select your CSV file** from the file dialog
4. **Objects are imported automatically:**
   - Lines are drawn between point pairs
   - Red markers appear at each point
   - Objects are added to the capture list
   - If azimuths were provided, they're stored for use during clustering

5. **Run clustering** as normal using the "A2i run clustering" button

## File Requirements

- **File extension**: `.csv`
- **Encoding**: UTF-8 (recommended)
- **Delimiter**: Comma (`,`)
- **Quotes**: Optional (for values containing commas)
- **Line endings**: Unix (`\n`), Windows (`\r\n`), or Mac (`\r`) - all supported

## Data Validation

The import function will:

- ✅ **Validate** coordinate ranges (lat: -90 to 90, lon: -180 to 180)
- ✅ **Normalize** azimuth values to 0-360 range if needed
- ✅ **Calculate** missing azimuths automatically
- ✅ **Report** errors for invalid rows (skips bad rows, continues with valid ones)
- ✅ **Show** summary of imported objects and any errors

## Error Handling

If errors occur during import:

- **Invalid coordinates**: Row is skipped, error message shown in console
- **Missing required columns**: Import fails with clear error message
- **Invalid azimuth**: Azimuth is ignored, will be calculated from points
- **Empty rows**: Skipped automatically

Check the QGIS message bar and console for detailed error information.

## Tips and Best Practices

1. **Always include a header row** for clarity (recommended)
2. **Use consistent column names** throughout your file
3. **Verify coordinate format** is decimal degrees (EPSG:4326)
4. **Check for empty cells** - missing required values will cause row to be skipped
5. **Test with a small file first** before importing large datasets
6. **Keep azimuths in 0-360 range** (values outside will be normalized)

## Combining CSV Import with Manual Capture

You can **mix both methods**:

1. Import some objects from CSV
2. Manually add more objects by clicking on the map
3. Run clustering on all objects together

The system handles both imported and manually captured objects seamlessly.

## Export → Import Workflow

You can export results to CSV and re-import them later:

1. Run clustering and save results to CSV
2. Extract the object rows from the saved CSV
3. Reformat as import CSV (keep: lat, lon columns from object rows)
4. Import back into the plugin

**Note**: The export CSV format is different from the import format. You'll need to extract and reformat the coordinate data.

## Troubleshooting

### "CSV must contain columns: lat1, lon1, lat2, lon2"
- **Problem**: Required columns not found
- **Solution**: Check column names match supported variations (see table above)

### "Row X: Not enough columns"
- **Problem**: Row has fewer values than required
- **Solution**: Ensure all rows have at least 4 columns (lat1, lon1, lat2, lon2)

### "Row X: invalid literal for float()"
- **Problem**: Non-numeric value in coordinate/azimuth column
- **Solution**: Check for text, special characters, or formatting issues

### Objects not appearing on map
- **Problem**: Coordinates might be in wrong CRS or format
- **Solution**: Verify coordinates are decimal degrees in EPSG:4326 (WGS84)

## Example Complete Workflow

```csv
lat1,lon1,lat2,lon2,azimuth
45.1234,-73.5678,45.1240,-73.5680,45.5
45.1300,-73.5700,45.1305,-73.5705,46.2
45.1400,-73.5800,45.1405,-73.5805,47.8
45.1500,-73.5900,45.1505,-73.5905,
```

1. Save this as `objects.csv`
2. In QGIS: Click "A2i import from CSV"
3. Select `objects.csv`
4. Message: "Imported 4 object(s) from CSV"
5. Click "A2i run clustering"
6. Results calculated with stored azimuths (rows 1-3) and calculated azimuth (row 4)

## Support

For issues or questions about CSV import format, check:
- QGIS console for detailed error messages
- This README for format specifications
- Plugin documentation for general usage

