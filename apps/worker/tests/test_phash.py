from PIL import Image

from tests.conftest import FIXTURES
from yearbook_worker.stages.decode import load_rgb
from yearbook_worker.stages.hashes import hamming, phash_bits
from yearbook_worker.stages.variants import resize_long_edge, square_thumb


def _small(name: str) -> Image.Image:
    return resize_long_edge(load_rgb(str(FIXTURES / name)), 640)


def test_phash_shape() -> None:
    bits = phash_bits(_small("01_IMG_7421.jpg"))
    assert len(bits) == 64 and set(bits) <= {"0", "1"}


def test_near_duplicate_is_close_and_distinct_images_are_far() -> None:
    a = phash_bits(_small("05_IMG_7425.jpg"))
    b = phash_bits(_small("11_IMG_7425_copy_q50.jpg"))
    c = phash_bits(_small("04_IMG_7424.jpg"))
    assert hamming(a, b) <= 6
    assert hamming(a, c) > 6 and hamming(b, c) > 6


def test_phash_is_stable_across_scales() -> None:
    full = load_rgb(str(FIXTURES / "09_IMG_7429.jpg"))
    assert hamming(phash_bits(full), phash_bits(resize_long_edge(full, 640))) <= 2


def test_resize_never_upscales_and_thumb_is_square() -> None:
    im = Image.new("RGB", (300, 200))
    assert resize_long_edge(im, 2048).size == (300, 200)
    assert resize_long_edge(im, 150).size == (150, 100)
    assert square_thumb(im).size == (200, 200)
    assert square_thumb(Image.new("RGB", (1600, 900))).size == (256, 256)


def test_alpha_flattens_onto_white() -> None:
    im = load_rgb(str(FIXTURES / "14_logo_alpha.png"))
    assert im.mode == "RGB"
    assert im.getpixel((2, 2)) == (255, 255, 255)  # the transparent corner


def test_heic_and_orientation_decode() -> None:
    assert load_rgb(str(FIXTURES / "15_IMG_0199.heic")).size == (1440, 1080)
    assert load_rgb(str(FIXTURES / "03_IMG_7423_portrait.jpg")).size == (1200, 1600)
