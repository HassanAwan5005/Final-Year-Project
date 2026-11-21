"""Recommendation routes — mounted at /api/v1/recommendations/"""

from django.urls import path

from apps.recommendations.views import (
    ConversationalMatchmakerView,
    RecommendationClickView,
    RecommendationStatusView,
    RecommendationView,
    VisualSearchRecommendationView,
)

app_name = "recommendations"

urlpatterns = [
    path("", RecommendationView.as_view(), name="recommendations"),
    path("matchmaker/", ConversationalMatchmakerView.as_view(), name="matchmaker"),
    path("visual-search/", VisualSearchRecommendationView.as_view(), name="visual-search"),
    path("click/", RecommendationClickView.as_view(), name="recommendation-click"),
    path("status/", RecommendationStatusView.as_view(), name="recommendation-status"),
]
