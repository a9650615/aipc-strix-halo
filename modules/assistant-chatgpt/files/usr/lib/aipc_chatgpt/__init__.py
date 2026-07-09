"""Multi-site web engine + site packs (ChatGPT is the first pack)."""

__version__ = "0.2.0"


def get_backend(site_id: str | None = None):
    from aipc_chatgpt.backend import get_backend as _gb

    return _gb(site_id)
