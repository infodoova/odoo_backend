"""
Common utility functions
"""

from django.conf import settings
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def encrypt_api_key(api_key: str) -> bytes:
    """
    Encrypt API key using Fernet encryption
    
    Args:
        api_key: Plain text API key
        
    Returns:
        Encrypted API key as bytes
    """
    if not api_key:
        return b''
    
    try:
        from cryptography.fernet import Fernet
        
        encryption_key = getattr(settings, 'ENCRYPTION_KEY', None)
        if encryption_key:
            f = Fernet(encryption_key)
            return f.encrypt(api_key.encode())
        else:
            logger.warning("ENCRYPTION_KEY not set, storing API key as plain bytes")
            return api_key.encode()
    except ImportError:
        logger.warning("cryptography not installed, storing API key as plain bytes")
        return api_key.encode()
    except Exception as e:
        logger.error(f"Error encrypting API key: {str(e)}")
        return api_key.encode()


def decrypt_api_key(encrypted) -> str:
    logger.info("decrypt_api_key called")

    if encrypted is None:
        logger.info("Encrypted value is None")
        return ""

    try:
        logger.info(f"Incoming type: {type(encrypted)}")

        # ==============================
        # Convert everything to bytes
        # ==============================
        if isinstance(encrypted, memoryview):
            logger.info("Detected memoryview, converting using tobytes()")
            data = encrypted.tobytes()
            logger.info(f"Raw data: {data}")

        elif isinstance(encrypted, bytes):
            logger.info("Detected bytes, using directly")
            data = encrypted

        elif isinstance(encrypted, str):
            logger.warning("Encrypted value is already string, returning as-is")
            return encrypted

        else:
            logger.warning("Unknown type, attempting bytes() conversion")
            try:
                data = bytes(encrypted)
                logger.info("bytes() conversion successful")
            except Exception as conv_error:
                logger.error(f"bytes() conversion failed: {conv_error}")
                return ""

        logger.info(f"Data length after normalization: {len(data)}")

        if not data:
            logger.warning("Data is empty after conversion")
            return ""

        # ==============================
        # Decryption attempt
        # ==============================
        encryption_key = getattr(settings, 'ENCRYPTION_KEY', None)

        if encryption_key:
            logger.info("ENCRYPTION_KEY found, attempting Fernet decryption")
            try:
                from cryptography.fernet import Fernet
                f = Fernet(encryption_key)

                decrypted = f.decrypt(data)
                logger.info("Fernet decryption successful")

                result = decrypted.decode("utf-8")
                logger.info(f"Decrypted result length: {len(result)}")

                return result

            except Exception as decrypt_error:
                logger.error(f"Fernet decryption failed: {decrypt_error}")
                logger.warning("Falling back to plain decode")

        else:
            logger.warning("ENCRYPTION_KEY not set, skipping decryption")

        # ==============================
        # Plain decode fallback
        # ==============================
        try:
            result = data.decode("utf-8", errors="ignore")
            logger.info(f"Plain decode successful, result length: {len(result)}")
            return result
        except Exception as decode_error:
            logger.error(f"Plain decode failed: {decode_error}")
            return ""

    except Exception as e:
        logger.exception(f"Unexpected error in decrypt_api_key: {e}")
        return ""
