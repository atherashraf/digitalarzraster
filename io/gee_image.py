import json
import os
import shutil
import traceback
from datetime import datetime

import ee
import requests
from tqdm import tqdm

from digitalarzraster.io.gee_region import GEERegion
from digitalarzraster.processing.rio_process import RioProcess


class GEEImage:
    image: ee.Image

    def __init__(self, img: ee.Image):
        self.image = img
        self.bands = None

    @staticmethod
    def get_image_bands(img):
        try:
            return img.bandNames().getInfo()
        except ee.EEException as e:
            print(f"An error occurred while getting band names: {e}")
            return []

    @staticmethod
    def get_image_date(img) -> datetime:
        """
        return system time stamp
        """
        # Get the date of the latest image.
        latest_date = ee.Date(img.get('system:time_start')).getInfo()

        # Convert the timestamp to a readable format.
        formatted_date = datetime.utcfromtimestamp(latest_date['value'] / 1000)

        print('Latest acquisition date:', formatted_date.strftime('%Y-%m-%d'))
        return formatted_date

    def get_scale(self, b_name=None):
        # Get scale (in meters) information from band 1.
        if b_name is None:
            band_names = self.image.bandNames().getInfo()
            res = {}
            for b_name in band_names:
                b1_scale = self.image.select(b_name).projection().nominalScale()
                # print('{} scale:'.format(b_name), b1_scale.getInfo())  # ee.Number
                res[b_name] = b1_scale.getInfo()
            return res
        else:
            b1_scale = self.image.select(b_name).projection().nominalScale()
            return b1_scale.getInfo()

    def get_image_metadata(self) -> dict:
        return self.image.getInfo()

    def get_download_url(self, img_name, aoi: ee.Geometry.Polygon, scale=None):
        try:
            # Check if bands are already set, otherwise get them from the image.
            if not self.bands:
                self.bands = self.get_image_bands(self.image)

            # Generate download URL if required bands are present.
            url = self.image.getDownloadURL({
                'image': self.image.serialize(),
                'region': aoi,
                'bands': self.bands,
                'name': img_name,
                'scale': scale,
                'format': 'GEO_TIFF'
            })
            return url

        except ee.ee_exception.EEException as e:
            print(f"An Earth Engine error occurred: {e}")
            return None
        except ValueError as e:
            print(f"ValueError: {e}")
            return None
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            return None

    @staticmethod
    def download_url(url, file_path: str, allow_redirects=True):
        downloaded_obj = requests.get(url, allow_redirects=allow_redirects)
        if downloaded_obj.status_code == 200:
            with open(file_path, "wb") as file:
                file.write(downloaded_obj.content)
            return True
        else:
            error = json.loads(downloaded_obj.text)
            return False

    def download_image(self, file_path, img_region: GEERegion, scale=-1,
                       bit_depth=32, no_of_bands=None, delete_folder=True, within_aoi_only=True, save_metadata=True):
        if scale == -1:
            scale = self.get_scale()
            scale = min(scale.values())
        if no_of_bands is None:
            self.bands = self.get_image_bands(self.image)
            no_of_bands = len(self.bands)
        meta_data = self.get_image_metadata()
        if save_metadata:
            print("saving meta data...")
            meta_data_fp = f"{file_path[:-4]}_meta_data.json"
            os.makedirs(meta_data_fp, exist_ok=True)
            with open(meta_data_fp, "w") as f:
                # Serialize the dictionary to a JSON string and write it to the file
                json.dump(meta_data, f)
        # Extract band IDs
        band_ids = [band["id"] for band in meta_data["bands"]]
        print("downloading images...")
        dir_name = os.path.dirname(file_path)
        img_name, img_ext = os.path.splitext(os.path.basename(file_path))
        download_dir_name = str(os.path.join(dir_name, img_name))
        # dirname = FileIO.mkdirs(download_dir_name)
        os.makedirs(download_dir_name, exist_ok=True)
        required_tiles = []

        for region, index in img_region.get_tiles(no_of_bands, scale, bit_depth=bit_depth,
                                                  within_aoi_only=within_aoi_only):
            required_tiles.append((region, index))
            # print(region, index)
        # df = pd.DataFrame(required_tiles)
        # Create a tqdm progress bar for the loop
        progress_bar = tqdm(desc="Processing Tiles", unit="tile", total=len(required_tiles))
        for i, (region, index) in enumerate(required_tiles):
            temp_file_path = os.path.join(download_dir_name, f"r{index[0]}c{index[1]}.tif")
            if not os.path.exists(temp_file_path):
                aoi = region.get_aoi()
                url = self.get_download_url(img_name, aoi=aoi, scale=scale)
                if url is not None:
                    res = self.download_url(url, temp_file_path)
            # Simulate some processing time
            # time.sleep(0.1)

            # Update the tqdm progress bar
            progress_bar.update(1)
        # Close the tqdm progress bar
        progress_bar.close()

        try:
            raster = RioProcess.mosaic_images(download_dir_name)

            raster.save_to_file(file_path, band_names=band_ids)
            if delete_folder:
                if os.path.exists(download_dir_name):
                    shutil.rmtree(download_dir_name)
            print('Image downloaded as ', file_path)

            res = True
        except:
            traceback.print_exc()
            res = False
        return res
