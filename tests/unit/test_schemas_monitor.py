from pydantic import ValidationError
import pytest

from src.schemas.monitor import MonitorCreate, MonitorUpdate

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMonitorCreateSchema:

    def test_valid_data_creates_schema_successfully(self):
        valid_data = {
            "url": "https://example.com/blablashka",
            "name": "GoodMonitor",
            "interval": 120,
            "method": "PATCH",
        }

        schema = MonitorCreate(**valid_data)

        assert str(schema.url).rstrip("/") == "https://example.com/blablashka"
        assert schema.name == "GoodMonitor"
        assert schema.interval == 120
        assert schema.method == "PATCH"

    def test_invalid_url_raises_validation_error(self):
        invalid_data = {
            "url": "blebleshaka-baaad",
            "name": "BaaaaadMonitor",
            "interval": 120,
            "method": "PATCH",
        }

        with pytest.raises(ValidationError) as exc_info:
            MonitorCreate(**invalid_data)

        assert "url" in str(exc_info.value)

    def test_interval_must_be_positive_integer(self):
        invalid_data = {
            "url": "https://example.com/blablashka",
            "name": "Monitorig",
            "interval": -300,
            "method": "PATCH",
        }

        with pytest.raises(ValidationError) as exc_info:
            MonitorCreate(**invalid_data)

        assert "interval" in str(exc_info.value)


@pytest.mark.unit
class TestMonitorUpdateSchema:

    def test_partial_update_is_allowed(self):
        valid_data = {
            "interval": 600
            # name, url, method are not passed — they are optional
        }

        schema = MonitorUpdate(**valid_data)

        assert schema.interval == 600
        assert schema.name is None
        assert schema.url is None

    def test_update_with_invalid_interval_raises_error(self):
        invalid_data = {"interval": 70}

        with pytest.raises(ValidationError) as exc_info:
            MonitorUpdate(**invalid_data)

        assert "multiple of 60" in str(exc_info.value)
