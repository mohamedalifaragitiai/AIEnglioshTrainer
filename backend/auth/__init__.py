"""Authentication: password hashing, credential storage, bearer tokens.

Deliberately dependency-free — ``hashlib.scrypt`` and ``secrets`` from the standard
library cover both halves, so nothing new enters the offline install.
"""
