"""Control of the PremiumBlue PIPC-011 (OEM: Apexis APM-H803-MPC) via HTTP CGI."""

from .api import Camera, CameraError
from .parser import parse_js_vars

__all__ = ["Camera", "CameraError", "parse_js_vars"]
__version__ = "0.3.0"
