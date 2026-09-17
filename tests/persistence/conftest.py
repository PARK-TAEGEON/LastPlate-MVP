import pytest
from lastplate_db import Repository


@pytest.fixture
def repo(tmp_path):
    with Repository(tmp_path / "test.db") as repository:
        repository.create_site(site_id="s", site_name="Test")
        yield repository


@pytest.fixture
def prediction(repo):
    return repo.save_prediction(site_id="s", target_date="2026-01-01", predicted_diners=100,
                                created_at="2026-01-01T01:00:00Z")
