"""In-memory Workbench session. Tokens are not persisted to disk."""


class Session:
    client = None
    user = None

    @classmethod
    def set_client(cls, client, user):
        cls.client = client
        cls.user = user

    @classmethod
    def clear(cls):
        if cls.client is not None:
            try:
                cls.client.logout()
            finally:
                cls.client = None
                cls.user = None

    @classmethod
    def require_client(cls):
        if cls.client is None or not cls.client.token:
            raise RuntimeError("Log in to ForgePDM from the Workbench first")
        return cls.client
