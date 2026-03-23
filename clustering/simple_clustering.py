"""
Simple distance-based clustering using union-find data structure.

This is a fallback method that doesn't require any external dependencies.
Uses an optimized union-find algorithm for efficient clustering.
"""

from .base_clustering import BaseClusteringMethod


class SimpleClustering(BaseClusteringMethod):
    """Simple distance-based clustering using union-find (no external dependencies)"""
    
    def __init__(self):
        super().__init__()
        self.name = "Simple"
        self.description = "Distance-based clustering with union-find (no dependencies)"
    
    def cluster(self, object_centroids, distance_threshold=100.0):
        """
        Cluster objects using simple distance-based clustering with union-find.
        
        Optimized with union-find data structure for O(n²) worst case but much faster average case.
        
        Args:
            object_centroids: List of (lat, lon, obj_points, obj_transformed) tuples
            distance_threshold: Distance threshold in meters (default 100m)
        
        Returns:
            List of cluster labels (integers)
        """
        # Convert meters to approximate degrees
        # 1 degree ≈ 111,000 meters at equator
        eps_degrees = distance_threshold / 111000.0
        eps_squared = eps_degrees * eps_degrees  # Use squared distance to avoid sqrt
        
        n = len(object_centroids)
        if n == 0:
            return []
        if n == 1:
            return [0]
        
        print(f"Simple: Clustering {n} objects with threshold: {eps_degrees:.6f} degrees (~{distance_threshold} meters)")
        
        # Union-Find data structure for efficient clustering
        parent = list(range(n))
        
        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])  # Path compression
            return parent[x]
        
        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py
        
        # Only check pairs that might be close (early termination optimization)
        # Pre-sort by latitude for potential spatial optimization
        sorted_indices = sorted(range(n), key=lambda i: object_centroids[i][0])
        
        # Compare points - use squared distance to avoid sqrt
        for i_idx, i in enumerate(sorted_indices):
            obj1 = object_centroids[i]
            lat1, lon1 = obj1[0], obj1[1]
            
            # Only check nearby points (within latitude range)
            for j_idx in range(i_idx + 1, n):
                j = sorted_indices[j_idx]
                obj2 = object_centroids[j]
                lat2, lon2 = obj2[0], obj2[1]
                
                # Early termination: if latitude difference is too large, skip rest
                lat_diff = lat2 - lat1
                if lat_diff > eps_degrees:
                    break  # No more points can be within threshold
                
                # Calculate squared distance (avoid sqrt for performance)
                lon_diff = lon2 - lon1
                dist_squared = lat_diff * lat_diff + lon_diff * lon_diff
                
                if dist_squared <= eps_squared:
                    union(i, j)
        
        # Assign cluster labels
        cluster_map = {}
        labels = []
        current_label = 0
        
        for i in range(n):
            root = find(i)
            if root not in cluster_map:
                cluster_map[root] = current_label
                current_label += 1
            labels.append(cluster_map[root])
        
        # Debug: count clusters
        unique_labels = len(set(labels))
        print(f"Simple clustering found {unique_labels} cluster(s)")
        
        return labels

