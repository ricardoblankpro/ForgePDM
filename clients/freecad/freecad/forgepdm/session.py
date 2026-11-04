"""In-memory Workbench session. Tokens are not persisted to disk."""

import sys


def _notify_status():
    module = sys.modules.get(__package__ + ".tree_status")
    if module is not None:
        module.session_changed()


class Session:
    client = None
    user = None
    busy = False

    @classmethod
    def set_client(cls, client, user):
        cls.client = client
        cls.user = user
        _notify_status()

    @classmethod
    def clear(cls):
        """Detach locally; HTTP logout must be scheduled in a worker."""
        client = cls.client
        cls.client = None
        cls.user = None
        _notify_status()
        return client

    @classmethod
    def require_client(cls):
        if cls.client is None or not cls.client.token:
            raise RuntimeError("Log in to ForgePDM from the Workbench first")
        if getattr(cls.client, "is_expired", lambda: False)():
            cls.invalidate()
            raise RuntimeError("Your session expired. Log in again to continue.")
        return cls.client

    @classmethod
    def invalidate(cls):
        if cls.client is not None:
            cls.client.token = None
            cls.client.expires_at = None
        cls.clear()
