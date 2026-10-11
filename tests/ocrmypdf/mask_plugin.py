"""Test plugin: blanks the top of every OCR image, where the test page's first line sits."""

from ocrmypdf import hookimpl
from PIL import ImageDraw


@hookimpl
def filter_ocr_image(page, image):
    masked = image.copy()
    # The first line ends 97 pt below the top of the 792 pt page; the second starts at 135 pt.
    ImageDraw.Draw(masked).rectangle((0, 0, masked.width, masked.height * 116 // 792), fill="white")
    return masked
