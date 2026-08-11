import io
from PIL import Image, ImageOps
import pillow_heif

pillow_heif.register_heif_opener()

MAX_WIDTH_CM = 16.0
MAX_HEIGHT_CM = 22.0

def process_and_scale_image(file_path: str) -> tuple[io.BytesIO, float, float]:
    """Loads, transposes EXIF orientation, and calculates scaled width in cm.

    Returns:
        (BytesIO png stream, scaled_width_cm, scaled_height_cm)
    Raises:
        Exception if image is corrupted or unsupported format.
    """
    with Image.open(file_path) as img:
        img = ImageOps.exif_transpose(img)
        orig_w, orig_h = img.size
        aspect = orig_w / orig_h
        max_aspect = MAX_WIDTH_CM / MAX_HEIGHT_CM

        if aspect > max_aspect:
            new_w = MAX_WIDTH_CM
            new_h = MAX_WIDTH_CM / aspect
        else:
            new_h = MAX_HEIGHT_CM
            new_w = MAX_HEIGHT_CM * aspect

        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        buf.seek(0)
        return buf, new_w, new_h
