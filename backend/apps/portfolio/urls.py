"""Portfolio routes — mounted at /api/v1/portfolio/"""

from rest_framework.routers import DefaultRouter

from apps.portfolio.views import (
    MyPortfolioViewSet,
    PhotographerPortfolioViewSet,
    PortfolioAlbumViewSet,
    PortfolioImageViewSet,
)

app_name = "portfolio"

router = DefaultRouter()
# Studio: the signed-in photographer manages their own portfolio.
router.register("me", MyPortfolioViewSet, basename="my-portfolio")
# Public: anyone browses a photographer's portfolio.
router.register("photographers", PhotographerPortfolioViewSet, basename="portfolio")
# Read-only browse used by PortfolioScreen.
router.register("albums", PortfolioAlbumViewSet, basename="album")
router.register("images", PortfolioImageViewSet, basename="image")

urlpatterns = router.urls
