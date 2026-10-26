"""Structured API errors (API_CONTRACT.md error envelope)."""


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def envelope(self):
        return {'error': {'code': self.code, 'message': self.message}}


def bad_request(message='The request was not understood.'):
    return ApiError(400, 'BAD_REQUEST', message)


def invalid_image(message='Choose one PNG, JPG or WebP equation image.'):
    return ApiError(422, 'INVALID_IMAGE', message)


def unsupported_image(message='Choose one PNG, JPG or WebP equation image. Animated or multi-page images are not supported.'):
    return ApiError(422, 'UNSUPPORTED_IMAGE', message)


def too_large(message='The image is too large. Use an image under 8 MB and 16 million pixels.'):
    return ApiError(413, 'IMAGE_TOO_LARGE', message)


def busy():
    return ApiError(409, 'BUSY', 'The reader is still working on another image. Try again when it finishes.')


def not_ready(message):
    return ApiError(503, 'NOT_READY', message)


def recognition_failed():
    return ApiError(500, 'RECOGNITION_FAILED', 'The local model could not read this image. Try a tighter crop or a clearer image.')


def math_failed(message='The reading could not be converted to MathML and speech. Try another image or an alternative reading.'):
    return ApiError(422, 'MATH_CONVERSION_FAILED', message)


def internal():
    return ApiError(500, 'INTERNAL_ERROR', 'Something went wrong in the local reader.')
