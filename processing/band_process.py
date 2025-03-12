import numpy as np
import geopandas as gpd
from skimage import measure
from shapely.geometry.polygon import orient, Polygon
class BandProcess:

    @staticmethod
    def reclassify_band(img_arr: np.array, thresholds: dict, nodata=0) -> np.array:
        """
        img_arr: must be as row, col
        :param thresholds:
            example:  {
                    "water": (('lt', 0.015), 4),
                    "built-up": ((0.015, 0.02), 1),
                    "barren": ((0.07, 0.27), 2),
                    "vegetation": (('gt', 0.27), 3)
                }

        """
        if img_arr.ndim > 2:
            img_arr = np.squeeze(img_arr)
        res = np.empty(img_arr.shape)
        res[:] = nodata
        for key in thresholds:
            if thresholds[key][0][0] == 'lt':
                res = np.where(img_arr <= thresholds[key][0][1], thresholds[key][1], res)
            elif thresholds[key][0][0] == 'gt':
                res = np.where(img_arr >= thresholds[key][0][1], thresholds[key][1], res)
            else:
                con = np.logical_and(img_arr >= thresholds[key][0][0], img_arr <= thresholds[key][0][1])
                res = np.where(con, thresholds[key][1], res)
        return res.astype(np.uint8)

    @staticmethod
    def raster_2_polygon(band_data: np.ndarray, classes: list = [], crs=0, tolerance=0) -> gpd.GeoDataFrame:
        # gdf = gpd.GeoDataFrame(columns=['class', 'geometry'], crs = crs)
        if len(classes) == 0:
            classes = np.unique(band_data)
            print("Classes:", classes)
        final_polygons = []
        for class_value in classes:
            # Create a binary mask for the current class
            binary_mask = (band_data == class_value).astype(np.uint8)

            # Find contours
            contours = measure.find_contours(binary_mask, 0.5)

            # Convert contours to polygons
            polygons = [Polygon(contour[:, ::-1]) for contour in contours if
                        len(contour) > 2]  # Reverse to get (x, y) from (row, col)

            # Orient polygons correctly and remove duplicates
            polygons = [orient(polygon) for polygon in polygons]
            if tolerance != 0:
                polygons = [polygon.simplify(tolerance) for polygon in polygons]
            final_polygons = final_polygons + [{'class': class_value, 'geometry': polygon} for polygon in polygons]
            # for polygon in  polygons:
            #     gdf = gdf.append({'class': class_value, 'geometry': polygon}, ignore_index=True)
        gdf = gpd.GeoDataFrame(data=final_polygons, columns=['class', 'geometry'], crs=crs)
        return gdf
