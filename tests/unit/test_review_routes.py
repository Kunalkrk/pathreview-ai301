"""Tests for the /reviews HTTP routes (api/routes/reviews.py)."""

from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.middleware.auth import get_current_user
from core.database import get_db
from core.models.user import User


@pytest.mark.unit
class TestReviewRoutes:
    """Test suite for POST /reviews."""

    @pytest.fixture
    def fake_user(self):
        return User(id=str(uuid4()), email="test@example.com", hashed_password="x")

    @pytest.fixture
    def client(self, fake_user):
        async def _override_get_current_user():
            return fake_user

        async def _override_get_db():
            session = AsyncMock()
            yield session

        app.dependency_overrides[get_current_user] = _override_get_current_user
        app.dependency_overrides[get_db] = _override_get_db
        try:
            yield TestClient(app, raise_server_exceptions=False)
        finally:
            app.dependency_overrides.clear()

    @pytest.fixture
    def mock_review_class(self):
        """Patch review_service.Review so db.refresh() doesn't need a real DB
        round trip to populate id/created_at/updated_at."""
        with patch("core.services.review_service.Review") as MockReview:
            review = Mock()
            review.id = uuid4()
            review.profile_id = uuid4()
            review.status = "pending"
            review.sections = None
            review.overall_score = None
            review.error_message = None
            review.created_at = datetime.utcnow()
            review.updated_at = datetime.utcnow()
            MockReview.return_value = review
            yield MockReview

    @pytest.fixture
    def mock_profile_no_content(self):
        """Patch get_profile (as imported into api.routes.reviews) to return
        a profile with none of the three content fields set."""
        with patch(
            "api.routes.reviews.get_profile", new_callable=AsyncMock
        ) as mock_get_profile:
            profile = Mock()
            profile.id = uuid4()
            profile.github_username = None
            profile.portfolio_url = None
            profile.resume_text = None
            mock_get_profile.return_value = profile
            yield mock_get_profile

    @pytest.fixture
    def mock_profile_with_content(self):
        """Patch get_profile to return a profile that has content to review."""
        with patch(
            "api.routes.reviews.get_profile", new_callable=AsyncMock
        ) as mock_get_profile:
            profile = Mock()
            profile.id = uuid4()
            profile.github_username = "octocat"
            profile.portfolio_url = None
            profile.resume_text = None
            mock_get_profile.return_value = profile
            yield mock_get_profile

    @pytest.fixture
    def mock_profile_not_found(self):
        """Patch get_profile to simulate a missing/not-owned profile."""
        with patch(
            "api.routes.reviews.get_profile", new_callable=AsyncMock
        ) as mock_get_profile:
            mock_get_profile.return_value = None
            yield mock_get_profile

    def test_create_review_for_profile_with_no_ingested_documents_returns_error(
        self, client, mock_profile_no_content
    ):
        """POST /reviews for a profile with no ingested documents should
        return a client error, not silently accept the review."""
        profile_id = str(uuid4())

        resp = client.post("/reviews", json={"profile_id": profile_id})

        assert resp.status_code == 422, (
            f"expected a 422 for a profile with no ingested documents, "
            f"got {resp.status_code}: {resp.text}"
        )

    def test_create_review_for_profile_with_content_returns_200(
        self, client, mock_profile_with_content, mock_review_class
    ):
        """Control case: a profile that has content to review should still
        succeed, exactly as before this fix."""
        profile_id = str(uuid4())

        resp = client.post("/reviews", json={"profile_id": profile_id})

        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

    def test_create_review_for_nonexistent_profile_returns_404(
        self, client, mock_profile_not_found
    ):
        """A profile_id that doesn't exist (or isn't owned by the caller)
        should 404 rather than be silently accepted. Not explicitly called
        for in the original plan; added because fetching the profile to
        check its content made this path easy to cover at the same time —
        noted in plan.md's Deviations."""
        profile_id = str(uuid4())

        resp = client.post("/reviews", json={"profile_id": profile_id})

        assert resp.status_code == 404
