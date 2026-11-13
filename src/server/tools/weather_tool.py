import json
import httpx

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


async def fetch_city_weather(city: str) -> str:
    """Geocodes a city name and fetches live weather conditions from Open-Meteo."""
    clean_city = city.strip()
    if not clean_city or len(clean_city) > 100:
        return json.dumps({"status": "ERROR", "error": "Invalid city parameter."})

    timeout = httpx.Timeout(10.0, connect=5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            geo_resp = await client.get(
                GEOCODE_URL,
                params={"name": clean_city, "count": 1, "language": "en", "format": "json"},
            )
            if geo_resp.status_code == 429:
                return json.dumps({"status": "RATE_LIMITED", "error": "Geocoding rate limit exceeded."})
            geo_resp.raise_for_status()
            results = geo_resp.json().get("results")

            if not results:
                return json.dumps({"status": "NOT_FOUND", "error": f"Could not geocode city: '{clean_city}'."})

            loc = results[0]
            lat, lon = loc["latitude"], loc["longitude"]
            resolved_name = f"{loc.get('name')}, {loc.get('admin1', '')}, {loc.get('country_code', '')}".strip(", ")

            weather_resp = await client.get(
                FORECAST_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,precipitation,rain,weather_code,wind_speed_10m",
                    "temperature_unit": "fahrenheit",
                    "wind_speed_unit": "mph",
                    "precipitation_unit": "inch",
                },
            )
            if weather_resp.status_code == 429:
                return json.dumps({"status": "RATE_LIMITED", "error": "Forecast rate limit exceeded."})
            weather_resp.raise_for_status()
            w_data = weather_resp.json().get("current", {})

            code = w_data.get("weather_code", -1)
            precip = w_data.get("precipitation", 0.0)
            wind = w_data.get("wind_speed_10m", 0.0)

            advisory = "NORMAL_DISPATCH"
            if code in {65, 75, 82, 95, 96, 99} or precip >= 0.25 or wind >= 35.0:
                advisory = "HIGH_DELAY_RISK"
            elif code in {51, 53, 55, 61, 63, 71, 73, 80, 81} or precip > 0.0:
                advisory = "MODERATE_WET_ROAD_CAUTION"

            return json.dumps(
                {
                    "status": "OK",
                    "location": resolved_name,
                    "coordinates": {"latitude": lat, "longitude": lon},
                    "temperature_f": w_data.get("temperature_2m"),
                    "condition": WMO_CODES.get(code, f"WMO Code {code}"),
                    "precipitation_in": precip,
                    "rain_in": w_data.get("rain", 0.0),
                    "wind_speed_mph": wind,
                    "logistics_advisory": advisory,
                },
                indent=2,
            )

    except httpx.TimeoutException:
        return json.dumps({"status": "TIMEOUT", "error": "Upstream weather API timed out."})
    except httpx.HTTPError:
        return json.dumps({"status": "HTTP_ERROR", "error": "Upstream weather service request failed."})
