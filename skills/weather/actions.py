import requests
from typing import Dict


def get_weather(params: Dict) -> str:
    """Get current weather for a location."""
    location = params.get("location", "").strip()
    if not location:
        return "Error: location is required"

    try:
        url = f"https://wttr.in/{location}?format=j1"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Nexus/1.0"})
        resp.raise_for_status()
        data = resp.json()

        current = data.get("current_condition", [{}])[0]
        area = data.get("nearest_area", [{}])[0]
        city = area.get("areaName", [{}])[0].get("value", location)
        country = area.get("country", [{}])[0].get("value", "")

        temp_c = current.get("temp_C", "?")
        temp_f = current.get("temp_F", "?")
        desc = current.get("weatherDesc", [{}])[0].get("value", "Unknown")
        humidity = current.get("humidity", "?")
        wind_kph = current.get("windspeedKmph", "?")
        feels_c = current.get("FeelsLikeC", "?")

        return (
            f"**{city}, {country}** — {desc}\n"
            f"Temperature: {temp_c}C / {temp_f}F (feels like {feels_c}C)\n"
            f"Humidity: {humidity}% | Wind: {wind_kph} km/h"
        )
    except Exception as e:
        return f"Error fetching weather: {e}"


def get_forecast(params: Dict) -> str:
    """Get 3-day weather forecast for a location."""
    location = params.get("location", "").strip()
    if not location:
        return "Error: location is required"

    try:
        url = f"https://wttr.in/{location}?format=j1"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Nexus/1.0"})
        resp.raise_for_status()
        data = resp.json()

        area = data.get("nearest_area", [{}])[0]
        city = area.get("areaName", [{}])[0].get("value", location)
        forecasts = data.get("weather", [])

        if not forecasts:
            return "No forecast data available."

        lines = [f"**3-Day Forecast for {city}:**"]
        for day in forecasts[:3]:
            date = day.get("date", "?")
            max_c = day.get("maxtempC", "?")
            min_c = day.get("mintempC", "?")
            hourly = day.get("hourly", [{}])
            desc = hourly[len(hourly) // 2].get("weatherDesc", [{}])[0].get("value", "?") if hourly else "?"
            lines.append(f"- **{date}**: {desc}, {min_c}C — {max_c}C")

        return "\n".join(lines)
    except Exception as e:
        return f"Error fetching forecast: {e}"
