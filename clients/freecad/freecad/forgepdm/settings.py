"""Only non-secret connection preferences live in FreeCAD's parameter store."""


def _parameters():
    import FreeCAD

    return FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/ForgePDM")


def load():
    parameters = _parameters()
    return {
        "url": parameters.GetString("ServerURL", "http://127.0.0.1:8000"),
        "username": parameters.GetString("Username", ""),
        "timeout": max(1, min(300, parameters.GetInt("TimeoutSeconds", 30))),
    }


def save(url, username, timeout):
    parameters = _parameters()
    parameters.SetString("ServerURL", url)
    parameters.SetString("Username", username)
    parameters.SetInt("TimeoutSeconds", int(timeout))


def _workspace_parameters(server_url=None, actor_id=None):
    parameters = _parameters()
    if server_url and actor_id:
        import hashlib

        key = hashlib.sha256((server_url.rstrip("/") + "\n" + actor_id).encode()).hexdigest()
        return parameters.GetGroup("Workspaces").GetGroup(key)
    return parameters


def workspace_root(server_url=None, actor_id=None):
    return _workspace_parameters(server_url, actor_id).GetString("WorkspaceRoot", "")


def save_workspace(root, server_url=None, actor_id=None):
    _workspace_parameters(server_url, actor_id).SetString("WorkspaceRoot", str(root))
