import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from src.server.tools.sql_tool import execute_read_only_sql
from src.server.tools.weather_tool import fetch_city_weather
from src.server.tools.math_tool import evaluate_safe_math


@pytest.mark.asyncio
async def test_1_sql_read_accuracy():
    raw = await execute_read_only_sql(
        "SELECT o.order_id, o.sku, o.quantity, o.order_total, i.quantity_available "
        "FROM orders o JOIN inventory i ON o.sku = i.sku "
        "WHERE o.order_id = 4492 AND i.warehouse_city = 'Seattle'"
    )
    data = json.loads(raw)
    assert data["status"] == "OK"
    assert data["row_count"] == 1
    row = data["rows"][0]
    assert row["sku"] == "SKU-90210"
    assert row["quantity"] == 12
    assert row["quantity_available"] == 42
    assert row["order_total"] == 15000.00


@pytest.mark.asyncio
async def test_2_weather_api_integration_mocked():
    geo_payload = {
        "results": [
            {
                "name": "Seattle",
                "admin1": "Washington",
                "country_code": "US",
                "latitude": 47.6062,
                "longitude": -122.3321,
            }
        ]
    }
    forecast_payload = {
        "current": {
            "temperature_2m": 52.4,
            "precipitation": 0.12,
            "rain": 0.12,
            "weather_code": 61,
            "wind_speed_10m": 11.5,
        }
    }

    mock_geo_resp = MagicMock(status_code=200)
    mock_geo_resp.json.return_value = geo_payload
    mock_geo_resp.raise_for_status = MagicMock()

    mock_weather_resp = MagicMock(status_code=200)
    mock_weather_resp.json.return_value = forecast_payload
    mock_weather_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.side_effect = [mock_geo_resp, mock_weather_resp]
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("httpx.AsyncClient", return_value=mock_client):
        raw = await fetch_city_weather("Seattle")

    data = json.loads(raw)
    assert data["status"] == "OK"
    assert "Seattle" in data["location"]
    assert data["condition"] == "Slight rain"
    assert data["logistics_advisory"] == "MODERATE_WET_ROAD_CAUTION"


def test_3_math_evaluator_precision():
    raw = evaluate_safe_math("2 + 3 * (4 - 1) ** 2")
    data = json.loads(raw)
    assert data["status"] == "OK"
    assert data["result"] == 29

    ins_raw = evaluate_safe_math("15000 * 0.035")
    assert json.loads(ins_raw)["result"] == 525.0
