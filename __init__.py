import sys
from os import path

sys.path.insert(0, path.dirname(__file__))
from folder_paths import get_save_image_path, get_output_directory
from PIL import Image
import numpy as np

class DepthViewer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "reference_image": ("IMAGE",),
                "depth_map": ("IMAGE",),
            }
        }

    
    def __init__(self):
        self.saved_reference = []
        self.saved_depth = []
        self.full_output_folder, self.filename, self.counter, self.subfolder, self.filename_prefix = get_save_image_path("imagesave", get_output_directory())

    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "process_images"
    CATEGORY = "DepthViewer"
    def process_images(self, reference_image, depth_map):
        image = reference_image[0].detach().cpu().numpy()
        depth = depth_map[0].detach().cpu().numpy()

        image = Image.fromarray(np.clip(255. * image, 0, 255).astype(np.uint8)).convert('RGB')
        depth = Image.fromarray(np.clip(255. * depth, 0, 255).astype(np.uint8))

        return self.display([image], [depth])

    def display(self, reference_image, depth_map):
        for (batch_number, (single_image, single_depth)) in enumerate(zip(reference_image, depth_map)):
            filename_with_batch_num = self.filename.replace("%batch_num%", str(batch_number))

            image_file = f"{filename_with_batch_num}_{self.counter:05}_reference.png"
            single_image.save(path.join(self.full_output_folder, image_file))

            depth_file = f"{filename_with_batch_num}_{self.counter:05}_depth.png"
            single_depth.save(path.join(self.full_output_folder, depth_file))

            self.saved_reference.append({
                "filename": image_file,
                "subfolder": self.subfolder,
                "type": "output"
            })

            self.saved_depth.append({
                "filename": depth_file,
                "subfolder": self.subfolder,
                "type": "output"
            })

        return {"ui": {"reference_image": self.saved_reference, "depth_map": self.saved_depth}}
    
NODE_CLASS_MAPPINGS = {
    "DepthViewer": DepthViewer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DepthViewer": "DepthViewer",
}

WEB_DIRECTORY = "./web"

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']
