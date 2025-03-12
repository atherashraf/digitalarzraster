import os
import traceback
import geopandas as gpd

import numpy as np
import rasterio as rio
from typing import Union, List

import shapely
from affine import Affine
from rasterio import CRS, windows
from rasterio.mask import mask
from shapely import box


class RioRaster:
    dataset: rio.DatasetReader = None

    def __init__(self, src: Union[str, rio.DatasetReader, None], prj_path: str = None):
        if src is not None:
            self.set_dataset(src)
            if prj_path is not None and os.path.exists(prj_path):
                self.add_crs_from_prj(prj_path)

    def set_dataset(self, src: Union[str, rio.DatasetReader]):
        """
        Set the raster dataset from a source.

        :param src: The source path or DatasetReader object.
        """
        try:
            if isinstance(src, rio.DatasetReader):
                if '/vsipythonfilelike/' in src.name:
                    self.dataset = self.rio_dataset_from_array(src.read(), src.meta)
                else:
                    self.dataset = src
            elif isinstance(src, str):
                if "/vsimem/" in src:
                    with rio.MemoryFile(src) as memfile:
                        self.dataset = memfile.open()
                else:
                    if os.path.exists(src):
                        self.dataset = rio.open(src, mode='r+', ignore_cog_layout_break='YES')
                    else:
                        raise FileNotFoundError(f"Raster file not available at {src}")

            if self.dataset is None:
                raise ValueError("Dataset could not be set. It is None.")
        except Exception as e:
            traceback.print_exc()

    @staticmethod
    def rio_dataset_from_array(data: np.ndarray, meta, descriptions: list = None) -> rio.DatasetReader:
        """
        Create a RioDataset from an array.

        :param data: The data array.
        :param meta: The metadata.
        :param descriptions: The band descriptions.
        :return: The resulting DatasetReader object.
        """
        bands = 1 if len(data.shape) == 2 else data.shape[0]
        memfile = rio.MemoryFile()
        dst = memfile.open(**meta,
                           compress='lzw',
                           BIGTIFF='YES')
        for i in range(bands):
            d = data if len(data.shape) == 2 else data[i, :, :]
            dst.write(d, i + 1)
        if descriptions is not None:
            dst.descriptions = descriptions
        dst.close()
        return memfile.open()

    def add_crs_from_prj(self, prj_file):
        """
        Add CRS from a .prj file.

        :param prj_file: The path to the .prj file.
        """
        ame, ext = os.path.splitext(prj_file)
        if ext == "prj":
            with open(prj_file) as f:
                wkt = f.read()
                self.dataset.crs = CRS.from_wkt(wkt)

    def get_meta(self):
        """Get the metadata of the current dataset."""
        return self.dataset.meta

    @property
    def empty(self):
        return self.dataset is None

    @staticmethod
    def write_to_file(img_des: str, data: np.ndarray, crs: CRS, affine_transform: Affine, nodata_value,
                       band_names: List[str] = ()):
        """Write raster data to a file (GeoTIFF or COG) with optional S3 support.

        Args:
            img_des (str): The destination file path (local or S3 URI).
            data (np.ndarray): The raster data array.
            crs (CRS): The Coordinate Reference System.
            affine_transform (Affine): The affine transformation.
            nodata_value: The no-data value.
            band_names: list of band names to write with file as description
        """
        try:

            os.makedirs(img_des, exist_ok=True)

            # Determine driver and BigTIFF
            driver = 'COG' if img_des.lower().endswith('.cog') else 'GTiff'
            bigtiff = 'YES' if data.nbytes > 4 * 1024 * 1024 * 1024 else 'NO'

            # Get dimensions and bands
            if len(data.shape) == 2:
                # bands, rows, cols = 1, *data.shape
                bands = 1
                rows, cols = data.shape
            else:
                bands, rows, cols = data.shape

            # Write raster data with optional S3 environment

            with rio.open(img_des, 'w', driver=driver, height=rows, width=cols,
                               count=bands, dtype=str(data.dtype), crs=crs,
                               transform=affine_transform, compress='deflate',
                               predictor=1, zlevel=9,  # Predictor and compression level for Deflate
                               nodata=nodata_value, BIGTIFF=bigtiff) as dst:

                for i in range(bands):
                    d = data if bands == 1 else data[i, :, :]
                    dst.write(d, indexes=i + 1) if bands > 1 else dst.write(d)
                    # Assign band names (Check if band names list is correct)
                    if i < len(band_names):
                        dst.set_band_description(i + 1, band_names[i])

                # Add overviews for COGs (if applicable)
                if driver == 'COG':
                    dst.build_overviews([2, 4, 8, 16, 32])

        except rio.RasterioIOError as e:
            print(f"Error writing raster to file {img_des}: {e}")
            traceback.print_exc()

    def save_to_file(self, img_des: str, data: np.ndarray = None, crs: CRS = None,
                     affine_transform: Affine = None, nodata_value=None, band_names: List[str] = ()):
        """
        Save the dataset to a file.

        :param img_des: The destination file path.
        :param data: The data array to save.
        :param crs: The CRS to use.
        :param affine_transform: The affine transform to use.
        :param nodata_value: The no-data value to use.
        :param band_names: The list of band name to write in the file as description
        """
        data = self.get_data_array() if data is None else data
        crs = crs if crs else self.dataset.crs
        affine_transform = affine_transform if affine_transform else self.dataset.transform
        nodata_value = nodata_value if nodata_value else self.get_nodata_value()
        self.write_to_file(img_des, data, crs, affine_transform, nodata_value, band_names=band_names)


    def get_data_array(self, band=None, convert_no_data_2_nan=False) -> np.ndarray:
        """
        Get the data array from the dataset.

        :param band: The band number to read.
        :param convert_no_data_2_nan: Whether to convert no-data values to NaN.
        :param envelop_gdf: An optional envelope to restrict the data.
        :return: The data array.
        """
        if self.dataset is not None:
            dataset = self.dataset
            if band:
                data_arr = dataset.read(band)
            else:
                data_arr = dataset.read()
            if convert_no_data_2_nan:
                if not np.issubdtype(data_arr.dtype, np.floating):
                    data_arr = data_arr.astype(np.float32)

                data_arr[data_arr == self.dataset.nodata] = np.nan
                # data_arr = np.clip(data_arr, np.finfo(np.float32).min, np.finfo(np.float32).max)  # Clip extreme values
                # data_arr = data_arr.astype(np.float32)  # Finally, cast to float32

            return data_arr
        else:
            raise ValueError("raster dataset is empty")

    def get_data_shape(self):
        """
        Get the shape of the data array.

        :return: Tuple of (band, row, column).
        """
        data = self.get_data_array()
        if len(data.shape) == 2:
            band = 1
            row, column = data.shape
        elif len(data.shape) == 3:
            band, row, column = data.shape
        return band, row, column

    def get_crs(self) -> CRS:
        """Get the CRS of the dataset."""
        return self.dataset.crs

    def get_geo_transform(self) -> Affine:
        """
        Get the affine transform of the dataset.

        :return: The affine transform.
            the sequence is [a,b,c,d,e,f]
        """
        return self.dataset.profile.data['transform']

    def get_nodata_value(self):
        """Get the no-data value of the dataset."""
        return self.dataset.meta['nodata']

    def set_nodata(self, nodata_value=None):
        """Set NoData value for the raster."""
        print(f"Opening mode: {self.dataset.mode}")  # Debug: Check if r+
        if nodata_value is None:
            # Convert rasterio dtype string to NumPy dtype
            raster_dtype = np.dtype(self.dataset.dtypes[0])
            nodata_value = np.finfo(raster_dtype).max
        self.dataset.nodata = nodata_value  # Set NoData value
        self.dataset.update_tags(nodata=nodata_value)

    def rio_raster_from_array(self, img_arr: np.ndarray) -> 'RioRaster':
        """
        Create a RioRaster object from an array.

        :param img_arr: The image array.
        :return: A new RioRaster object.
        """
        meta_data = self.get_meta().copy()
        raster = self.raster_from_array(img_arr, crs=self.get_crs(),
                                        g_transform=self.get_geo_transform(),
                                        nodata_value=self.get_nodata_value())
        return raster

    @staticmethod
    def raster_from_array(img_arr: np.ndarray, crs: Union[str, CRS],
                          g_transform: Affine, nodata_value=None) -> 'RioRaster':
        """
        Create a RioRaster object from an array.

        :param img_arr: The image array.
        :param crs: The CRS to use.
        :param g_transform: The affine transform to use.
        :param nodata_value: The no-data value to use.
        :return: A new RioRaster object.
        """
        try:
            memfile = rio.MemoryFile()
            if len(img_arr.shape) == 2:
                bands = 1
                rows, cols = img_arr.shape
            else:
                bands, rows, cols = img_arr.shape

            with memfile.open(driver='GTiff',
                              height=rows,
                              width=cols,
                              count=bands,
                              dtype=str(img_arr.dtype),
                              crs=crs,
                              transform=g_transform,
                              nodata=nodata_value,
                              compress='lzw',
                              BIGTIFF='YES') as dataset:
                for i in range(bands):
                    d = img_arr if len(img_arr.shape) == 2 else img_arr[i, :, :]
                    dataset.write(d, i + 1)
                dataset.close()

            dataset = memfile.open()  # Reopen as DatasetReader
            new_raster = RioRaster(dataset)
            return new_raster

        except Exception as e:
            print(f"Error creating raster from array: {e}")
            traceback.print_exc()
            return None

    def clip_raster(self, aoi: Union[gpd.GeoDataFrame, shapely.geometry.Polygon, shapely.geometry.MultiPolygon],
                    in_place=True, crs=0) -> 'RioRaster':
        """
        Clip the raster to an area of interest (AOI), setting nodata to the maximum value of the raster data type.

        :param aoi: The area of interest.
        :param in_place: Whether to perform the operation in place.
        :param crs: The CRS of the AOI.
        :return: The clipped RioRaster object.
        """
        if isinstance(aoi, (shapely.geometry.Polygon, shapely.geometry.MultiPolygon)):
            aoi = gpd.GeoDataFrame(geometry=[aoi], crs=crs)

        if str(aoi.crs).lower() != str(self.get_crs()).lower():
            geo = aoi.to_crs(self.get_crs())
        else:
            geo = aoi

        # Convert raster bounds to a tuple
        raster_bounds = self.get_bounds()  # Expected format: (minx, miny, maxx, maxy)

        # Convert raster bounds to a Shapely polygon (bounding box)
        raster_box = box(*raster_bounds)

        # Ensure AOI bounds are extracted properly
        aoi_bounds_list = geo.bounds.values.tolist()  # Extract [minx, miny, maxx, maxy] for each AOI

        # Check if raster does NOT intersect with any AOI bounding box
        does_not_intersect = all(not raster_box.intersects(box(*aoi_bounds)) for aoi_bounds in aoi_bounds_list)

        if does_not_intersect:
            print("❌ Raster doesn't intersects with AOI returning an empty raster.")
            if in_place:
                self.dataset = None

            return RioRaster(None)

        geom_col = geo.geometry.name
        geometries = [feature[geom_col] for _, feature in geo.iterrows()]

        # Get raster data type and determine max value
        raster_dtype = self.dataset.dtypes[0]  # Get data type as string (e.g., 'uint8', 'int16')
        # dtype_info = np.iinfo(raster_dtype) if 'int' in raster_dtype else np.finfo(raster_dtype)
        # nodata_value = dtype_info.max  # Maximum value for that data type
        nodata_value = 0
        out_img, out_transform = mask(self.dataset, geometries, crop=True, nodata=nodata_value)

        out_meta = self.dataset.meta.copy()
        out_meta.update({
            "driver": "GTiff",
            "height": out_img.shape[1],
            "width": out_img.shape[2],
            "transform": out_transform,
            "nodata": nodata_value,
            "crs": self.dataset.crs
        })

        descriptions = self.dataset.descriptions
        if in_place:
            self.dataset = self.rio_dataset_from_array(out_img, out_meta, descriptions)
        else:
            return RioRaster(self.rio_dataset_from_array(out_img, out_meta, descriptions))

        return self

    def pad_raster(self, des_raster):
        """
        Clip or pad the raster to align with the bounds of another raster.

        :param des_raster: The target RioRaster object.
        """
        aff: Affine = self.get_geo_transform()
        des_bounds = des_raster.get_bounds()
        rows, cols = rio.transform.rowcol(aff, xs=[des_bounds[0], des_bounds[2]],
                                               ys=[des_bounds[3], des_bounds[1]])

        height = rows[1] - rows[0]
        width = cols[1] - cols[0]
        window = windows.Window(col_off=cols[0], row_off=rows[0],
                                width=width, height=height)
        window_transform = windows.transform(window, self.get_geo_transform())

        kwargs = self.dataset.meta.copy()
        kwargs.update({
            'crs': self.get_crs(),
            'transform': window_transform,
            'width': width,
            'height': height
        })
        memfile = rio.MemoryFile()
        dst = memfile.open(**kwargs)
        data = self.dataset.read(window=window, boundless=False, fill_value=self.dataset.nodata)
        dst.write(data)
        dst.close()
        self.dataset = memfile.open()

    def reclassify_raster(self, thresholds, band=None, nodata=0) -> 'RioRaster':
        """
        Reclassify the raster based on thresholds.

        :param thresholds: The thresholds for reclassification.
            example:  {
                    "water": (('lt', 0.015), 4),
                    "built-up": ((0.015, 0.02), 1),
                    "barren": ((0.07, 0.27), 2),
                    "vegetation": (('gt', 0.27), 3)
                }
        :param band: The band number to reclassify.
        :param nodata: The no-data value.
        :return: The reclassified data array.
        """
        nodata = self.get_nodata_value() if self.get_nodata_value() is not None and self.get_nodata_value() != nodata else nodata
        no_of_bands = self.get_spectral_resolution()
        res = []
        for band_no in range(no_of_bands):
            img_arr = self.get_data_array(band_no + 1)
            img_arr = np.squeeze(img_arr)
            classified_data = BandProcess.reclassify_band(img_arr, thresholds, nodata)
            res.append(classified_data)
        if no_of_bands > 0:
            res = np.stack(res, axis=0)

        binary_raster = self.rio_raster_from_array(res.astype(np.uint8))
        return binary_raster
