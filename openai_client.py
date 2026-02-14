import requests

OPENAI_URL = "https://api.openai.com/v1/chat/completions"


def translate_text(api_key, text, system_prompt, model):
    api_key = api_key.strip()

    if not api_key:
        raise RuntimeError("Brak API Key")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": text
            }
        ],
        "temperature": 0.2
    }

    response = requests.post(
        OPENAI_URL,
        headers=headers,
        json=payload,
        timeout=120
    )

    response.raise_for_status()

    data = response.json()

    if "choices" in data and len(data["choices"]) > 0:
        return data["choices"][0]["message"]["content"].strip()
    else:
        raise RuntimeError("Brak odpowiedzi w polu 'choices'")
