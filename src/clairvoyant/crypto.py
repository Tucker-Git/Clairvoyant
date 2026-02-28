import os
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends import default_backend

def _derive_key(password: str, salt: bytes, iterations: int = 200_000) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
        backend=default_backend(),
    )
    return kdf.derive(password.encode("utf-8"))


def encrypt(message: bytes, password: str) -> bytes:
    # encrypt message with password using AES-GCM. returns salt||nonce||ciphertext.
    salt = os.urandom(16)
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, message, None)
    return salt + nonce + ct


def decrypt(encrypted: bytes, password: str) -> bytes:

    # decrypt expecting first 16 bytes salt, next 12 bytes nonce.
    
    if len(encrypted) < 16 + 12:
        raise ValueError("Invalid encrypted payload")
    salt = encrypted[:16]
    nonce = encrypted[16:28]
    ct = encrypted[28:]
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None)
