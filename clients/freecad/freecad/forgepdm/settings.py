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


def workspace_root():
    return _parameters().GetString("WorkspaceRoot", "")


def save_workspace(root):
    _parameters().SetString("WorkspaceRoot", str(root))
