from typing import List, Dict

import geopandas as gpd
from pyproj import CRS


class GPDVector:
    @staticmethod
    def from_geojson(features: List[Dict], crs=CRS.from_epsg(4326)) -> gpd.GeoDataFrame:
        if len(features) > 0:
            gdf = gpd.GeoDataFrame.from_features(features, crs)
        else:
            gdf = gpd.GeoDataFrame()
        return gdf

    @staticmethod
    def to_geojson(gdf: gpd.GeoDataFrame):
        return gdf.__geo_interface__
