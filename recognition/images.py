"""Decode and validate one uploaded equation image entirely in memory."""
import base64
import binascii
import io
import warnings

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from . import config, errors

ALLOWED_FORMATS = {'PNG': 'png', 'JPEG': 'jpeg', 'WEBP': 'webp'}
# Decompression bombs are rejected by our own pixel cap; make Pillow raise rather than warn above it.
Image.MAX_IMAGE_PIXELS = config.MAX_PIXELS


def decode_base64(value) -> bytes:
    if not isinstance(value, str) or not value:
        raise errors.bad_request('image_base64 must be a non-empty base64 string.')
    if value.startswith('data:'):
        raise errors.bad_request('Send raw base64 without a data: URL prefix.')
    # Upper bound on decoded size before decoding anything.
    if len(value) > (config.MAX_IMAGE_BYTES * 4) // 3 + 8:
        raise errors.too_large()
    compact = ''.join(value.split())
    try:
        data = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError):
        raise errors.bad_request('image_base64 is not valid base64.')
    if not data:
        raise errors.invalid_image('The image is empty.')
    if len(data) > config.MAX_IMAGE_BYTES:
        raise errors.too_large()
    return data


def load_image(data: bytes) -> Image.Image:
    """Return a fully decoded RGB or RGBA image, or raise ApiError."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data), formats=list(ALLOWED_FORMATS))
    except Image.DecompressionBombError:
        raise errors.too_large()
    except Image.DecompressionBombWarning:
        raise errors.too_large()
    except UnidentifiedImageError:
        raise errors.invalid_image('This file is not a PNG, JPG or WebP image, or it is damaged.')
    except Exception:
        raise errors.invalid_image('This file is not a PNG, JPG or WebP image, or it is damaged.')
    if img.format not in ALLOWED_FORMATS:
        raise errors.unsupported_image()
    w, h = img.size
    if w < 1 or h < 1:
        raise errors.invalid_image('The image has no pixels.')
    if w * h > config.MAX_PIXELS:
        raise errors.too_large()
    if getattr(img, 'n_frames', 1) != 1 or getattr(img, 'is_animated', False):
        raise errors.unsupported_image('Animated or multi-frame images are not supported. Use one still image of one equation.')
    try:
        img.load()
    except Exception:
        raise errors.invalid_image('The image data is damaged or incomplete.')
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    return to_model_mode(img)


def to_model_mode(img: Image.Image) -> Image.Image:
    """RGB for opaque images; RGBA when transparency exists, so pix2tex can read ink from alpha."""
    mode = img.mode
    if mode in ('I;16', 'I;16B', 'I;16L', 'I', 'F'):
        a = np.asarray(img, dtype=np.float64)
        lo, hi = float(a.min()), float(a.max())
        a = np.zeros_like(a) if hi <= lo else (a - lo) / (hi - lo) * 255.0
        return Image.fromarray(a.astype(np.uint8), 'L').convert('RGB')
    has_alpha = mode in ('RGBA', 'LA', 'PA') or (mode == 'P' and 'transparency' in img.info) or \
        (mode in ('RGB', 'L') and 'transparency' in img.info)
    if has_alpha:
        rgba = img.convert('RGBA')
        alpha = np.asarray(rgba)[..., 3]
        if alpha.min() < 255:
            return rgba
        return rgba.convert('RGB')
    return img.convert('RGB')


def has_visible_content(img: Image.Image) -> bool:
    """pix2tex needs at least two distinct ink levels; a uniform image has nothing to read."""
    if img.mode == 'RGBA':
        a = np.asarray(img)[..., 3]
        if a.max() != a.min():
            return True
    g = np.asarray(img.convert('L'))
    return int(g.max()) - int(g.min()) >= 16
