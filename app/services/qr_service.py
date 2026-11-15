"""QR code rendering for short links."""

from __future__ import annotations

from io import BytesIO

import qrcode
from qrcode.constants import ERROR_CORRECT_M

#: Colour of the modules; readable in both light and dark UIs.
QR_FOREGROUND = "#173b2c"
QR_BACKGROUND = "#ffffff"


def make_qr_png(data: str, box_size: int = 10) -> bytes:
    """Render ``data`` as a PNG QR code and return the bytes."""
    code = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=max(2, min(40, int(box_size))),
        border=2,
    )
    code.add_data(data)
    code.make(fit=True)
    image = code.make_image(fill_color=QR_FOREGROUND, back_color=QR_BACKGROUND).convert("RGB")
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
