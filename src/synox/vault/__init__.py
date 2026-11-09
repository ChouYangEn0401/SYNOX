"""保管箱：Vault（加解密 *.json.enc）＋ keyring（主金鑰怎麼保管）。"""

from synox.vault.keyring import KeyringError, load_or_create
from synox.vault.vault import Vault, VaultError


def open_vault(config) -> Vault:
    """照 config.vault.mode 拿（或第一次產生）主金鑰，回傳 data_dir 上的 Vault。"""
    key = load_or_create(config.data_dir, (config.vault or {}).get("mode", "dpapi"))
    return Vault(key, config.data_dir)


__all__ = ["KeyringError", "Vault", "VaultError", "open_vault"]
