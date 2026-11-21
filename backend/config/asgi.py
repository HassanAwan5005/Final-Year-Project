"""
ASGI entry point — routes HTTP *and* WebSocket traffic.

HTTP  →  the normal Django/DRF stack
WS    →  JWT-authenticated Channels consumers (chat, notifications, presence)
"""

import os
import threading

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

# The HTTP application must be created before importing anything that touches
# the app registry (consumers import models).
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from apps.core.ws_auth import JWTAuthMiddlewareStack  # noqa: E402
from config.ws_urls import websocket_urlpatterns  # noqa: E402


def _warm_recommender():
    from apps.recommendations import engine

    engine.warm_up()


# Off the startup path: the server accepts connections immediately, and the
# models are usually loaded before the first Home-feed request arrives.
threading.Thread(target=_warm_recommender, daemon=True).start()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            JWTAuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
