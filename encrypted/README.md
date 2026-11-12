# Encrypted archive

This folder holds an OpenPGP-encrypted archive (`*.tar.gz.gpg`). It is ciphertext only;
the key is not stored in this repository.

## Decrypt

Requires GnuPG 2.2 or newer and the matching private key (an ASCII-armored `.asc` file).

```sh
gpg --import <private-key.asc> && gpg -d plans-20261113.tar.gz.gpg | tar xz
```

The archive extracts into a `plans/` folder in the current directory.

Notes:

- This branch is temporary and may be rewritten or deleted when the key is rotated.
- Encryption uses standard OpenPGP (public-key encryption, integrity-protected data packet),
  so any OpenPGP implementation that supports RSA keys can decrypt it.
