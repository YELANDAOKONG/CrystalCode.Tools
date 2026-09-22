#!/usr/bin/env python3
"""Crystal Code external web search and page fetch tools.

The process receives one JSON object on stdin and writes only the tool result
to stdout. The first command-line argument selects the tool.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


EXA_MCP_URL = "https://mcp.exa.ai/mcp"
PARALLEL_MCP_URL = "https://search.parallel.ai/mcp"
DEFAULT_SEARCH_TIMEOUT = 25
DEFAULT_FETCH_TIMEOUT = 30
MAX_FETCH_TIMEOUT = 120
MAX_SEARCH_RESPONSE_BYTES = 512 * 1024
MAX_FETCH_RESPONSE_BYTES = 5 * 1024 * 1024
DEFAULT_RESULT_COUNT = 8
MAX_RESULT_COUNT = 20
DEFAULT_CONTEXT_CHARACTERS = 10_000
MAX_CONTEXT_CHARACTERS = 50_000
SKIPPED_HTML_TAGS = {"script", "style", "noscript", "iframe", "object", "embed"}
BLOCK_HTML_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "div",
    "dl",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tr",
    "ul",
}


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if self.skip_depth:
            self.skip_depth += 1
            return
        if tag in SKIPPED_HTML_TAGS:
            self.skip_depth = 1

    def handle_endtag(self, tag: str) -> None:
        del tag
        if self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


class MarkdownExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.pre_depth = 0
        self.link_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skip_depth:
            self.skip_depth += 1
            return
        if tag in SKIPPED_HTML_TAGS:
            self.skip_depth = 1
            return

        attributes = dict(attrs)
        if tag in BLOCK_HTML_TAGS:
            self._block()
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("#" * int(tag[1]) + " ")
        elif tag == "li":
            self.parts.append("- ")
        elif tag == "a":
            self.parts.append("[")
            self.link_stack.append(attributes.get("href") or "")
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag == "code" and not self.pre_depth:
            self.parts.append("`")
        elif tag == "pre":
            self.pre_depth += 1
            self.parts.append("```\n")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "hr":
            self.parts.append("\n---\n")

    def handle_endtag(self, tag: str) -> None:
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if tag == "a" and self.link_stack:
            href = self.link_stack.pop()
            self.parts.append(f"]({href})" if href else "]")
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag == "code" and not self.pre_depth:
            self.parts.append("`")
        elif tag == "pre" and self.pre_depth:
            self.pre_depth -= 1
            self.parts.append("\n```")
        if tag in BLOCK_HTML_TAGS:
            self._block()

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        self.parts.append(data if self.pre_depth else re.sub(r"\s+", " ", data))

    def _block(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n\n"):
            self.parts.append("\n\n")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def extract_text_from_html(content: str) -> str:
    parser = TextExtractor()
    parser.feed(content)
    parser.close()
    return normalize_text("".join(parser.parts))


def convert_html_to_markdown(content: str) -> str:
    parser = MarkdownExtractor()
    parser.feed(content)
    parser.close()
    result = html.unescape("".join(parser.parts))
    result = re.sub(r"[ \t]+\n", "\n", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def read_json_input() -> dict[str, Any]:
    raw = sys.stdin.buffer.read().decode("utf-8-sig")
    if not raw.strip():
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Tool arguments must be a JSON object")
    return value


def require_string(arguments: dict[str, Any], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Argument '{name}' must be a non-empty string")
    return value.strip()


def bounded_int(arguments: dict[str, Any], name: str, default: int, maximum: int) -> int:
    value = arguments.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Argument '{name}' must be a number")
    result = int(value)
    if result < 1 or result > maximum:
        raise ValueError(f"Argument '{name}' must be between 1 and {maximum}")
    return result


def mcp_url(provider: str) -> str:
    if provider == "exa":
        return os.environ.get("CRYSTAL_EXA_MCP_URL", EXA_MCP_URL)
    if provider == "parallel":
        return os.environ.get("CRYSTAL_PARALLEL_MCP_URL", PARALLEL_MCP_URL)
    raise ValueError("Provider must be 'exa' or 'parallel'")


def read_response(response: Any, maximum: int) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > maximum:
        raise ValueError(f"Response too large (exceeds {maximum} bytes)")

    content = bytearray()
    while True:
        chunk = response.read(min(64 * 1024, maximum + 1 - len(content)))
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > maximum:
            raise ValueError(f"Response too large (exceeds {maximum} bytes)")
    return bytes(content)


def open_response(
    request: Request,
    timeout: int,
    retry_cloudflare: bool = False,
    operation: str = "Request",
) -> Any:
    try:
        return urlopen(request, timeout=timeout)
    except HTTPError as error:
        challenge = error.code == 403 and error.headers.get("cf-mitigated") == "challenge"
        if not retry_cloudflare or not challenge:
            error.close()
            raise RuntimeError(f"{operation} failed with HTTP status {error.code}") from None
        error.close()
        retry_headers = dict(request.header_items())
        retry_headers["User-agent"] = "opencode"
        return urlopen(Request(request.full_url, headers=retry_headers, method=request.method), timeout=timeout)
    except (TimeoutError, URLError):
        raise RuntimeError("Network request failed or timed out") from None


def call_mcp(provider: str, arguments: dict[str, Any]) -> str:
    query = require_string(arguments, "query")
    result_count = bounded_int(arguments, "numResults", DEFAULT_RESULT_COUNT, MAX_RESULT_COUNT)
    context_max = bounded_int(
        arguments,
        "contextMaxCharacters",
        DEFAULT_CONTEXT_CHARACTERS,
        MAX_CONTEXT_CHARACTERS,
    )
    search_type = arguments.get("type", "auto")
    livecrawl = arguments.get("livecrawl", "fallback")
    if search_type not in {"auto", "fast", "deep"}:
        raise ValueError("Argument 'type' must be 'auto', 'fast', or 'deep'")
    if livecrawl not in {"fallback", "preferred"}:
        raise ValueError("Argument 'livecrawl' must be 'fallback' or 'preferred'")

    if provider == "exa":
        tool_name = "web_search_exa"
        tool_arguments: dict[str, Any] = {
            "query": query,
            "type": search_type,
            "numResults": result_count,
            "livecrawl": livecrawl,
            "contextMaxCharacters": context_max,
        }
        headers = {"Accept": "application/json, text/event-stream"}
        api_key = os.environ.get("EXA_API_KEY")
        if api_key:
            headers["x-api-key"] = api_key
    else:
        tool_name = "web_search"
        tool_arguments = {
            "objective": query,
            "search_queries": [query],
        }
        for key in ("session_id", "model_name"):
            if isinstance(arguments.get(key), str) and arguments[key].strip():
                tool_arguments[key] = arguments[key].strip()
        headers = {
            "Accept": "application/json, text/event-stream",
            "User-Agent": "crystal-code-web-tools/1",
        }
        api_key = os.environ.get("PARALLEL_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": tool_arguments},
    }
    request = Request(
        mcp_url(provider),
        data=json.dumps(payload).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    with open_response(request, DEFAULT_SEARCH_TIMEOUT, operation=f"{provider.title()} search") as response:
        body = read_response(response, MAX_SEARCH_RESPONSE_BYTES).decode("utf-8", "replace")
    result = parse_mcp_response(body)
    return result or "No search results found. Please try a different query."


def parse_mcp_response(body: str) -> str | None:
    candidates = [body.strip()]
    candidates.extend(
        line[6:].strip() for line in body.splitlines() if line.startswith("data: ")
    )
    for candidate in candidates:
        if not candidate.startswith("{"):
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        content = value.get("result", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"]:
                return item["text"]
    return None


def fetch_page(arguments: dict[str, Any]) -> str:
    url = require_string(arguments, "url")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL must use http:// or https://")
    if parsed.username or parsed.password:
        raise ValueError("URL credentials are not allowed")

    format_name = arguments.get("format", "markdown")
    if format_name not in {"text", "markdown", "html"}:
        raise ValueError("Argument 'format' must be 'text', 'markdown', or 'html'")
    timeout = arguments.get("timeout", DEFAULT_FETCH_TIMEOUT)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ValueError("Argument 'timeout' must be a number")
    timeout = min(max(int(timeout), 1), MAX_FETCH_TIMEOUT)

    accept = {
        "markdown": "text/markdown;q=1.0, text/plain;q=0.8, text/html;q=0.7, */*;q=0.1",
        "text": "text/plain;q=1.0, text/markdown;q=0.9, text/html;q=0.8, */*;q=0.1",
        "html": "text/html;q=1.0, application/xhtml+xml;q=0.9, text/plain;q=0.8, */*;q=0.1",
    }[format_name]
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
            ),
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
        },
        method="GET",
    )
    with open_response(request, timeout, retry_cloudflare=True, operation="Page fetch") as response:
        content_type = response.headers.get("Content-Type", "")
        mime = content_type.split(";", 1)[0].strip().lower()
        if mime.startswith("image/") and mime != "image/svg+xml":
            raise ValueError(f"Unsupported fetched image content type: {mime}")
        if mime and not is_textual_mime(mime):
            raise ValueError(f"Unsupported fetched file content type: {mime}")
        body = read_response(response, MAX_FETCH_RESPONSE_BYTES).decode("utf-8", "replace")

    if format_name == "html" or "html" not in mime:
        return body
    if format_name == "text":
        return extract_text_from_html(body)
    return convert_html_to_markdown(body)


def is_textual_mime(mime: str) -> bool:
    return (
        mime.startswith("text/")
        or mime in {"application/json", "application/xml", "application/javascript", "application/x-javascript"}
        or mime.endswith("+json")
        or mime.endswith("+xml")
    )


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("tool", choices=("websearch", "webfetch"))
    options = parser.parse_args()
    try:
        arguments = read_json_input()
        if options.tool == "websearch":
            provider = os.environ.get("CRYSTAL_WEBSEARCH_PROVIDER", "parallel").lower()
            print(call_mcp(provider, arguments))
        else:
            print(fetch_page(arguments))
        return 0
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
