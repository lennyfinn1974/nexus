import requests
import json
from typing import Dict, List, Optional, Tuple

class CurrencyConverter:
    def __init__(self):
        self.base_url = \"https://api.exchangerate-api.com/v4/latest\"
        self._cache = {}
        
    def _get_rates(self, base_currency: str = \"USD\") -> Dict:
        \"\"\"Get exchange rates for a base currency with caching.\"\"\"
        cache_key = base_currency.upper()
        
        # Simple cache (in production, you'd want time-based expiration)
        if cache_key in self._cache:
            return self._cache[cache_key]
            
        try:
            response = requests.get(f\"{self.base_url}/{base_currency}\")
            response.raise_for_status()
            data = response.json()
            self._cache[cache_key] = data
            return data
        except requests.RequestException as e:
            raise Exception(f\"Failed to fetch exchange rates: {str(e)}\")
    
    def convert_currency(self, amount: float, from_currency: str, to_currency: str) -> Dict:
        \"\"\"Convert an amount from one currency to another.\"\"\"
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()
        
        if from_currency == to_currency:
            return {
                \"amount\": amount,
                \"from_currency\": from_currency,
                \"to_currency\": to_currency,
                \"converted_amount\": amount,
                \"exchange_rate\": 1.0,
                \"message\": f\"{amount} {from_currency} = {amount} {to_currency} (same currency)\"
            }
        
        try:
            # Get rates with from_currency as base
            data = self._get_rates(from_currency)
            rates = data.get(\"rates\", {})
            
            if to_currency not in rates:
                available = list(rates.keys())[:10]  # Show first 10
                raise ValueError(f\"Currency '{to_currency}' not supported. Available: {available}...\")
            
            exchange_rate = rates[to_currency]
            converted_amount = round(amount * exchange_rate, 2)
            
            return {
                \"amount\": amount,
                \"from_currency\": from_currency,
                \"to_currency\": to_currency,
                \"converted_amount\": converted_amount,
                \"exchange_rate\": exchange_rate,
                \"message\": f\"{amount} {from_currency} = {converted_amount} {to_currency}\"
            }
            
        except Exception as e:
            return {\"error\": str(e)}
    
    def get_exchange_rate(self, from_currency: str, to_currency: str) -> Dict:
        \"\"\"Get the exchange rate between two currencies.\"\"\"
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()
        
        if from_currency == to_currency:
            return {
                \"from_currency\": from_currency,
                \"to_currency\": to_currency,
                \"rate\": 1.0,
                \"message\": f\"1 {from_currency} = 1 {to_currency}\"
            }
        
        try:
            data = self._get_rates(from_currency)
            rates = data.get(\"rates\", {})
            
            if to_currency not in rates:
                available = list(rates.keys())[:10]
                raise ValueError(f\"Currency '{to_currency}' not supported. Available: {available}...\")
            
            rate = rates[to_currency]
            
            return {
                \"from_currency\": from_currency,
                \"to_currency\": to_currency,
                \"rate\": rate,
                \"message\": f\"1 {from_currency} = {rate} {to_currency}\"
            }
            
        except Exception as e:
            return {\"error\": str(e)}

# Global instance
converter = CurrencyConverter()

def convert_currency(amount: float, from_currency: str, to_currency: str) -> Dict:
    \"\"\"Convert an amount from one currency to another.
    
    Args:
        amount: Amount to convert
        from_currency: Source currency code (e.g., 'USD')
        to_currency: Target currency code (e.g., 'EUR')
    
    Returns:
        Dict with conversion result
    \"\"\"
    return converter.convert_currency(amount, from_currency, to_currency)

def get_exchange_rate(from_currency: str, to_currency: str) -> Dict:
    \"\"\"Get exchange rate between two currencies.
    
    Args:
        from_currency: Source currency code
        to_currency: Target currency code
    
    Returns:
        Dict with exchange rate
    \"\"\"
    return converter.get_exchange_rate(from_currency, to_currency)