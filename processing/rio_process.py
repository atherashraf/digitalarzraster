import glob
import os
from pathlib import Path

from rasterio import DatasetReader, Env
from rasterio.merge import merge

from digitalarzraster.io.file_io import FileIO
from digitalarzraster.io.rio_raster import RioRaster


class RioProcess:

    @staticmethod
    def read_raster_ds(img_folder: str):
        ds_files: [DatasetReader] = []
        path = Path(img_folder)
        issues_folder = os.path.join(img_folder, "issue_in_files")
        os.makedirs(issues_folder,exist_ok=True)
        # count = FileIO.get_file_count(img_folder)
        # test = [str(p) for p in path.iterdir() if p.suffix == ".tif"]
        # ds_files = []
        for p in path.iterdir():
            if p.suffix == ".tif":
                try:
                    ds_files.append(RioRaster(str(p)).get_dataset())
                except Exception as e:
                    print(str(e))
                    FileIO.mvFile(str(p), issues_folder)
        return ds_files

    @classmethod
    def mosaic_images(cls, img_folder: str = None, ds_files: [DatasetReader] = (),  ext="tif") -> RioRaster:
        is_limit_changed = False
        if img_folder is not None:
            # count = FileIO.get_file_count(img_folder)
            count = FileIO.get_file_count(img_folder)
            # get file reading limits
            soft, hard = FileIO.get_file_reading_limit()
            # print("soft", soft, "hard", hard)
            if count > soft:
                if count * 2 < hard:
                    """
                    default limit is  soft: 12544 hard:9223372036854775807
                    """
                    FileIO.set_file_reading_limit(count * 2)

                    is_limit_changed = True
                else:
                    raise IOError(f"you are trying to read {count} files. Cannot read more than {hard} files.")
            ds_files = cls.read_raster_ds(img_folder)
            # problem_files.append(str(p))
        if len(ds_files) > 0:
            with Env(CHECK_DISK_FREE_SPACE=False):
                mosaic, out_trans = merge(ds_files)
                crs = ds_files[0].crs
                raster = RioRaster.raster_from_array(mosaic, crs=crs, g_transform=out_trans)
            if is_limit_changed:
                FileIO.set_file_reading_limit(soft)
            return raster

