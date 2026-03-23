# Step-by-Step Guide: Using Clustering Feature

## Step 1: Enable Batch Mode
1. In QGIS, click the **"A2i toggle batch mode"** button (usually in the toolbar)
2. Check the message bar at the bottom - it should say "Batch mode enabled"
3. Check the console/log - it should print "Batch mode enabled"

## Step 2: Capture Objects
1. Click **twice** on the map to define one object:
   - **First click**: Defines the first point (you'll see it marked)
   - **Second click**: Defines the second point (line will be drawn between them)
2. You should see:
   - A line drawn between the two points
   - Red cross markers at both points
   - Console message: "Object captured. Total objects: X"
3. Repeat step 1 for each object you want to capture
4. **Important**: Objects should be within ~100 meters of each other to be clustered together

## Step 3: Run Clustering
1. After capturing all objects, click the **"A2i run clustering"** button
2. A progress dialog will appear showing progress
3. Wait for the process to complete - it will:
   - Group objects into clusters
   - Calculate results for each cluster
   - Create visualization layers

## Step 4: Check Results
1. **Check the Layers Panel** (left side):
   - You should see new layers named **"Cluster_0"**, **"Cluster_1"**, etc.
   - These should be checked (visible) and above the "line" layers
   
2. **Check the Map**:
   - You should see **green polygons** around each cluster
   - Each polygon should encompass all objects in that cluster
   - You should also see **green circle markers** at cluster centroids

3. **Check the Console/Log**:
   - Look for messages starting with "DEBUG:" or "SUCCESS:"
   - These will tell you if layers were created and added successfully
   - Look for: "SUCCESS: Created and added cluster polygon layer 'Cluster_X' to map"

## Troubleshooting

### No Cluster Layers Appearing?
- **Check console output**: Look for DEBUG messages showing what's happening
- **Check if pending_polygons has data**: Look for "DEBUG: Creating X cluster polygon visualizations..."
- **Check layer creation**: Look for "SUCCESS: Created and added cluster polygon layer..."
- **Verify layers in project**: Check if layers appear in the Layers panel even if not visible on map

### Layers in Panel but Not Visible on Map?
- **Check layer visibility**: Make sure the checkbox next to Cluster_X layers is checked
- **Zoom to extent**: Right-click on a Cluster layer → "Zoom to Layer"
- **Check layer order**: Cluster layers should be above base map layers
- **Check style**: Right-click layer → Properties → Symbology - should show green fill

### Still Not Working?
- **Reload plugin**: Close QGIS and reopen, or reload the plugin
- **Check for errors**: Look in the log/console for error messages
- **Try with fewer objects**: Start with just 2-3 objects to test
- **Check coordinate system**: Make sure your map is in a projected coordinate system (not lat/lon if possible)

## Expected Console Output
When working correctly, you should see:
```
DEBUG: Stored cluster 0 in pending_polygons (total pending: 1)
DEBUG: createPendingPolygons called. Has pending_polygons: True
DEBUG: Creating 1 cluster polygon visualizations...
DEBUG: Creating polygon for cluster 0 with 3 objects
DEBUG: addClusterPolygon called for cluster 0
DEBUG: Processing 3 objects for cluster 0
SUCCESS: Created and added cluster polygon layer 'Cluster_0' to map (extent: XXX x XXX)
DEBUG: Successfully created layer Cluster_0, valid: True
Successfully created 1 cluster visualization layers
```

