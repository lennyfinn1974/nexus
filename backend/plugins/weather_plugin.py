"""Weather plugin — current conditions and forecasts via wttr.in."""

import logging

import aiohttp

from plugins.base import NexusPlugin

logger = logging.getLogger("nexus.plugins.weather")


class WeatherPlugin(NexusPlugin):
    name = "weather"
    description = "Weather lookup — current conditions and forecasts for any city"
    version = "1.0.0"

    async def setup(self):
        self._session = aiohttp.ClientSession()
        logger.info("Weather plugin ready")
        return True

    async def shutdown(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def register_tools(self):
        self.add_tool(
            "weather_current",
            "Get current weather conditions for a location",
            {"location": "City name or location"},
            self._current,
        )
        self.add_tool(
            "weather_forecast",
            "Get 3-day weather forecast for a location",
            {"location": "City name or location"},
            self._forecast,
        )

    def register_commands(self):
        self.add_command("weather", "Get weather: /weather <location>", self._handle_command)

    async def _fetch(self, location: str) -> dict:
        url = f"https://wttr.in/{location}?format=j1"
        async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    async def _current(self, params: dict) -> str:
        location = params.get("location", "").strip()
        if not location:
            return "Error: location is required"

        try:
            data = await self._fetch(location)
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

    async def _forecast(self, params: dict) -> str:
        location = params.get("location", "").strip()
        if not location:
            return "Error: location is required"

        try:
            data = await self._fetch(location)
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
                hourly = day.get("hourly", [])
                desc = "?"
                if hourly:
                    mid = hourly[len(hourly) // 2]
                    desc = mid.get("weatherDesc", [{}])[0].get("value", "?")
                lines.append(f"- **{date}**: {desc}, {min_c}C — {max_c}C")

            return "\n".join(lines)
        except Exception as e:
            return f"Error fetching forecast: {e}"

    async def _handle_command(self, args: str) -> str:
        location = args.strip()
        if not location:
            return "Usage: `/weather <city>` — e.g. `/weather Dublin`"
        return await self._current({"location": location})
