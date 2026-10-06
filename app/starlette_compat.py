"""Legacy import entry. Templates now use the explicit app.templating adapter."""
from .templating import Jinja2Templates


def install_template_response_compat():
    """Compatibility no-op; importing a module no longer patches Starlette."""
    return None
