"""Image decoding and validation (no model needed)."""
import base64
import io
import os

import numpy as np
import pytest
from PIL import Image

from recognition import config, images
from recognition.errors import ApiError


def png_bytes(img, **kw):
    b = io.BytesIO()
    img.save(b, format=kw.pop('format', 'PNG'), **kw)
    return b.getvalue()


def ink_image(mode='RGB', size=(120, 40)):
    img = Image.new('RGB', size, 'white')
    a = np.array(img)
    a[15:25, 10:110] = 0
    return Image.fromarray(a).convert(mode)


def code_of(fn, *args):
    with pytest.raises(ApiError) as e:
        fn(*args)
    return e.value.status, e.value.code


def test_valid_png_jpeg_webp_decode():
    for fmt in ('PNG', 'JPEG', 'WEBP'):
        img = images.load_image(png_bytes(ink_image(), format=fmt))
        assert img.mode == 'RGB' and images.has_visible_content(img)


def test_base64_errors():
    assert code_of(images.decode_base64, '') == (400, 'BAD_REQUEST')
    assert code_of(images.decode_base64, None) == (400, 'BAD_REQUEST')
    assert code_of(images.decode_base64, 'data:image/png;base64,AAAA') == (400, 'BAD_REQUEST')
    assert code_of(images.decode_base64, '!!!notbase64!!!') == (400, 'BAD_REQUEST')


def test_oversized_bytes_rejected_before_decoding():
    big = base64.b64encode(os.urandom(config.MAX_IMAGE_BYTES + 1)).decode()
    assert code_of(images.decode_base64, big) == (413, 'IMAGE_TOO_LARGE')


def test_exactly_at_byte_limit_is_accepted_by_decoder():
    data = os.urandom(config.MAX_IMAGE_BYTES)
    assert images.decode_base64(base64.b64encode(data).decode()) == data


def test_corrupt_and_truncated_and_non_image():
    good = png_bytes(ink_image())
    assert code_of(images.load_image, b'not an image at all')[0] == 422
    assert code_of(images.load_image, good[: len(good) // 2]) == (422, 'INVALID_IMAGE')
    assert code_of(images.load_image, b'\x89PNG\r\n\x1a\n' + b'\x00' * 50)[0] == 422


def test_extension_does_not_matter_actual_format_does():
    bmp = png_bytes(ink_image(), format='BMP')   # a BMP whatever its filename says
    gif = png_bytes(ink_image(), format='GIF')
    tif = png_bytes(ink_image(), format='TIFF')
    for data in (bmp, gif, tif):
        assert code_of(images.load_image, data)[0] == 422


def test_pixel_limit():
    huge = Image.new('1', (5000, 4000), 1)     # 20M pixels, small file
    data = png_bytes(huge)
    assert len(data) < config.MAX_IMAGE_BYTES
    assert code_of(images.load_image, data) == (413, 'IMAGE_TOO_LARGE')


def test_multiframe_rejected():
    frames = [ink_image(), Image.new('RGB', (120, 40), 'black')]  # different frames (Pillow merges identical ones)
    apng = png_bytes(frames[0], save_all=True, append_images=frames[1:])
    webp = png_bytes(frames[0], format='WEBP', save_all=True, append_images=frames[1:])
    assert code_of(images.load_image, apng) == (422, 'UNSUPPORTED_IMAGE')
    assert code_of(images.load_image, webp) == (422, 'UNSUPPORTED_IMAGE')


def test_transparent_png_keeps_alpha_for_pix2tex():
    g = ink_image('L')
    rgba = Image.new('RGBA', g.size, (0, 0, 0, 0))
    rgba.putalpha(g.point(lambda v: 255 - v))
    img = images.load_image(png_bytes(rgba))
    assert img.mode == 'RGBA' and images.has_visible_content(img)


def test_sixteen_bit_and_cmyk_and_palette():
    a = (np.array(ink_image('L')).astype(np.uint16) * 257)
    i16 = Image.fromarray(a.astype(np.uint16))
    assert images.load_image(png_bytes(i16)).mode == 'RGB'
    assert images.load_image(png_bytes(ink_image('CMYK'), format='JPEG')).mode == 'RGB'
    assert images.load_image(png_bytes(ink_image('P'))).mode == 'RGB'


def test_blank_image_has_no_content():
    for color in ('white', 'black'):
        img = images.load_image(png_bytes(Image.new('RGB', (100, 40), color)))
        assert not images.has_visible_content(img)


def test_tiny_image_accepted():
    img = images.load_image(png_bytes(ink_image(size=(4, 4))))
    assert img.size == (4, 4)
