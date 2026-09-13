from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtGui import QImage


def qimage_from_pillow(image: Image.Image) -> QImage:
    return ImageQt(image).copy()