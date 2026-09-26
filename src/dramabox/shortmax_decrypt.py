# -*- coding: utf-8 -*-
"""
ShortMax TS Segment Decryption Module.
Implements the custom AES-128-CBC decryption algorithm used by ShortMax (ShortTV).
Reverse-engineered from Sansekai/SekaiDrama (src/app/api/shortmax/hls/route.ts).
"""

import logging
from typing import Optional

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False

_log = logging.getLogger("shortmax.decrypt")

AES_IV = b"shortmax00000000"


def decrypt_shortmax_segment(buf: bytes) -> bytes:
    """
    Decrypts a ShortMax TS segment.
    If the segment is already standard TS (starts with 0x47 sync byte), returns it untouched.
    If it has the 'shortmax' header, extracts the embedded key, decrypts the first 1024 bytes
    using AES-128-CBC with IV 'shortmax00000000', and combines it with the remaining payload.
    """
    if not buf:
        return b""

    # Already a standard TS segment
    if buf[0] == 0x47:
        return buf

    # Minimum size to contain the 1040-byte header
    if len(buf) < 1040:
        return buf

    # Check for 'shortmax' magic header
    if not buf.startswith(b"shortmax"):
        return buf

    if not _HAS_CRYPTO:
        _log.warning("cryptography module not available, stripping ShortMax header")
        return buf[1040:]

    try:
        # 1. Parse header: extract key position (ASCII decimal at bytes 16..20)
        key_pos_str = buf[16:20].decode("ascii", errors="ignore").strip()
        key_pos = int(key_pos_str)
        key_offset = key_pos - 24

        # 2. Extract 16-byte AES key
        aes_key = buf[24 + key_offset : 24 + key_offset + 16]
        if len(aes_key) != 16:
            _log.warning("Invalid ShortMax AES key length: %d", len(aes_key))
            return buf[1040:]

        # 3. Assemble ciphertext: tail16 (bytes 1024..1040) + first 1024 bytes of payload (bytes 1040..2064)
        tail16 = buf[1024:1040]
        payload = buf[1040:]
        ciphertext = tail16 + payload[:1024]

        # 4. Decrypt with AES-128-CBC
        cipher = Cipher(algorithms.AES(aes_key), modes.CBC(AES_IV), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(ciphertext) + decryptor.finalize()

        # 5. Verify TS sync byte (0x47)
        if decrypted and decrypted[0] == 0x47:
            # 6. Combine: decrypted first 1024 bytes + plaintext remainder
            return decrypted[:1024] + payload[1024:]
        else:
            _log.warning("ShortMax decrypted header missing 0x47 sync byte; using stripped payload")
            return payload

    except Exception as exc:
        _log.warning("ShortMax decrypt failed: %s; falling back to raw payload", exc)
        return buf[1040:]
