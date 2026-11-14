"""NVIDIA backend for AI drafting (build.nvidia.com): same prompt and schema as the Claude call in llm.py.

Only the prompt is sent (table and column names, category values, the request). No patient rows.

Setup (no extra package needed; uses requests):
    export NVIDIA_API_KEY="nvapi-..."     # your own key, in .env only; never commit or paste it anywhere
    export NVIDIA_MODEL="..."             # optional; see the list command in the README or below

List the models your key can use:
    curl -s https://integrate.api.nvidia.com/v1/models -H "Authorization: Bearer $NVIDIA_API_KEY" \
      | python3 -m json.tool | grep '"id"'
"""
import json
import os
import time

BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"   # a hosted reasoning model with JSON-schema output


class NvidiaError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def available():
    return bool(os.environ.get("NVIDIA_API_KEY"))


def model_name():
    return os.environ.get("NVIDIA_MODEL", DEFAULT_MODEL)


def _post(payload, retries=4):
    import requests

    headers = {"Authorization": f"Bearer {os.environ['NVIDIA_API_KEY']}", "Accept": "application/json"}
    for attempt in range(retries + 1):
        try:
            response = requests.post(f"{BASE_URL}/chat/completions", headers=headers, json=payload, timeout=180)
        except requests.ConnectionError as err:
            raise NvidiaError(f"Connection problem: {err}") from None
        except requests.Timeout:
            raise NvidiaError("The request timed out after 3 minutes.") from None
        if response.status_code == 429 and attempt < retries:   # rate limited: wait, then try again
            wait = response.headers.get("Retry-After")
            time.sleep(float(wait) if wait and wait.replace(".", "", 1).isdigit() else 10 * (attempt + 1))
            continue
        if response.status_code >= 400:
            raise NvidiaError(response.text[:500], status_code=response.status_code)
        return response.json()


def _parse(content):
    text = (content or "").strip()
    if text.startswith("```"):                     # some models wrap JSON in a code fence
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    out = json.loads(text)                           # raises json.JSONDecodeError if it isn't JSON
    if not isinstance(out, dict) or not isinstance(out.get("steps"), list):
        raise NvidiaError("The model's answer didn't contain a list of steps.")
    out.setdefault("assumptions", [])
    out.setdefault("cannot_answer", None)
    return out


def complete_json(system_prompt, user_message, schema, name="cohort_draft"):
    """Send one request and return the parsed JSON object.

    Asks for JSON-schema output (OpenAI style). If the server rejects that (HTTP 400), retries once with
    NVIDIA's older guided_json option. The result is checked here too, because open models don't always
    follow a schema perfectly.
    """
    base = {
        "model": model_name(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0,
        "max_tokens": 8192,   # reasoning models think before answering; leave room for that
    }
    try:
        result = _post({**base, "response_format": {"type": "json_schema",
                                                    "json_schema": {"name": name, "schema": schema}}})
    except NvidiaError as err:
        if err.status_code != 400:
            raise
        result = _post({**base, "nvext": {"guided_json": schema}})
    return _parse(result["choices"][0]["message"].get("content"))