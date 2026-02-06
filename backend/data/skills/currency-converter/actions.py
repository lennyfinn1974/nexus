import requests
from typing import Dict

def convert_currency(params: Dict) -> str:
    amount = float(params['amount'])
    from_currency = params['from_currency'].upper()
    to_currency = params['to_currency'].upper()
    
    if from_currency == to_currency:
        return f"{amount} {from_currency} = {amount} {to_currency} (same currency)"
    
    try:
        url = f"https://api.exchangerate-api.com/v4/latest/{from_currency}"
        response = requests.get(url)
        data = response.json()
        
        if to_currency not in data['rates']:
            return f"Currency {to_currency} not supported"
        
        rate = data['rates'][to_currency] 
        converted = round(amount * rate, 2)
        
        return f"{amount} {from_currency} = {converted} {to_currency} (rate: {rate})"
        
    except Exception as e:
        return f"Error: {str(e)}"

def get_exchange_rate(params: Dict) -> str:
    from_currency = params['from_currency'].upper()
    to_currency = params['to_currency'].upper()
    
    if from_currency == to_currency:
        return f"1 {from_currency} = 1 {to_currency}"
    
    try:
        url = f"https://api.exchangerate-api.com/v4/latest/{from_currency}"
        response = requests.get(url)
        data = response.json()
        
        if to_currency not in data['rates']:
            return f"Currency {to_currency} not supported"
        
        rate = data['rates'][to_currency]
        return f"1 {from_currency} = {rate} {to_currency}"
        
    except Exception as e:
        return f"Error: {str(e)}"
"""
)
</tool_call>

Now let me check if the skill was created properly:

<tool_call>agent:list_dir(path="data/skills