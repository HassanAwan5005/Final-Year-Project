"""
OpenAPI description of the custom JWT authenticator.

drf-spectacular only recognises the stock simplejwt class out of the box, so
without this every protected endpoint is documented as unauthenticated.
"""

from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme


class SnapSphereJWTScheme(SimpleJWTScheme):
    target_class = "apps.accounts.authentication.SnapSphereJWTAuthentication"
    name = "jwtAuth"
