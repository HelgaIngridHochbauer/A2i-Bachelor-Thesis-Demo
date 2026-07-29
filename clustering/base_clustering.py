"""
Base class for clustering methods.

All clustering methods must inherit from this class and implement the cluster() method.
"""


class BaseClusteringMethod:
    """
    Base class for all clustering methods.
    
    All clustering methods must:
    1. Inherit from this class
    2. Implement the cluster() method
    3. Have a name attribute
    4. Have a description attribute
    """
    
    def __init__(self):
        self.name = "Base Method"
        self.description = "Base clustering method (not implemented)"
    
    def cluster(self, object_centroids, distance_threshold=100.0, **kwargs):
        """
        Cluster objects based on their centroids.
        
        Args:
            object_centroids: List of tuples, each containing:
                - lat (float): Latitude of object centroid
                - lon (float): Longitude of object centroid
                - obj_points: Original map points (QgsPointXY objects)
                - obj_transformed: Transformed points (QgsPointXY objects in EPSG:4326)
            distance_threshold: Distance threshold in meters (default: 100m)
        
        Returns:
            labels: List of integers, one per object, indicating cluster membership.
                   Objects in the same cluster have the same label.
                   Labels should start from 0 and be consecutive.
        
        Example:
            If you have 5 objects that form 2 clusters:
            - Objects 0, 1, 2 are in cluster 0
            - Objects 3, 4 are in cluster 1
            Then return: [0, 0, 0, 1, 1]
        """
        raise NotImplementedError("Subclasses must implement cluster() method")
    
    def __str__(self):
        return f"{self.name}: {self.description}"

