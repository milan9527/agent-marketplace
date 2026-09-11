"""Real, bounded tools. Code runs in AgentCore, never in the API/Runtime process."""

import hashlib
from html.parser import HTMLParser
import ipaddress
import json
import re
import socket
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config
import httpx

from app.config import get_settings
from app.models import now

TOOLS_BY_CATEGORY = {
    "Research": ["web_search", "read_page", "write_artifact"],
    "Finance": ["web_search", "read_page", "run_code", "write_artifact"],
    "Development": ["web_search", "read_page", "run_code", "write_artifact"],
    "Content": ["web_search", "read_page", "write_artifact"],
    "Data": ["web_search", "read_page", "run_code", "write_artifact"],
    "Automation": ["web_search", "read_page", "run_code", "write_artifact"],
}
TOOL_LABELS = {
    "web_search": "AgentCore Web Search",
    "read_page": "Read public webpages",
    "run_code": "AgentCore code execution",
    "write_artifact": "Create downloadable files",
}


def capabilities(category):
    return TOOLS_BY_CATEGORY.get(category, [])


def gateway_call(method, params):
    settings = get_settings()
    if not settings.web_search_gateway_url:
        raise ValueError("AgentCore Web Search is not configured.")
    url = settings.web_search_gateway_url.rstrip("/")
    if not url.endswith("/mcp"):
        url += "/mcp"
    body = json.dumps(
        {"jsonrpc": "2.0", "id": str(uuid4()), "method": method, "params": params}
    )
    session = boto3.Session(region_name=settings.aws_region)
    request = AWSRequest(
        method="POST",
        url=url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    SigV4Auth(
        session.get_credentials().get_frozen_credentials(),
        "bedrock-agentcore",
        settings.aws_region,
    ).add_auth(request)
    response = httpx.post(url, content=body, headers=dict(request.headers), timeout=45)
    response.raise_for_status()
    if "text/event-stream" in response.headers.get("content-type", ""):
        messages = [
            json.loads(line[5:].strip())
            for line in response.text.splitlines()
            if line.startswith("data:")
        ]
        result = next(v for v in messages if v.get("id") == json.loads(body)["id"])
    else:
        result = response.json()
    if result.get("error") or result.get("result", {}).get("isError"):
        raise ValueError("AgentCore Web Search returned an error.")
    return result["result"]


def web_search(query, max_results=5):
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200:
        raise ValueError("Search queries must contain 1–200 characters.")
    discovered = gateway_call("tools/list", {})
    tool = next(
        (v for v in discovered["tools"] if v["name"].endswith("___WebSearch")),
        None,
    )
    if not tool:
        raise ValueError("The gateway has no managed WebSearch tool.")
    result = gateway_call(
        "tools/call",
        {
            "name": tool["name"],
            "arguments": {"query": query, "maxResults": min(8, max(1, max_results))},
        },
    )
    body = result.get("structuredContent")
    if not body or "results" not in body:
        body = next(
            (
                json.loads(v["text"])
                for v in result.get("content", [])
                if v.get("type") == "text"
                and v.get("text", "").lstrip().startswith("{")
            ),
            {},
        )
    sources = []
    for item in body.get("results", [])[:8]:
        url = item.get("url", "")
        if urlsplit(url).scheme not in {"https", "http"}:
            continue
        sources.append(
            {
                "url": url,
                "title": str(item.get("title") or url)[:500],
                "published_at": item.get("publishedDate"),
                "snippet": str(item.get("text", ""))[:5000],
                "retrieved_at": now(),
                "read": False,
            }
        )
    if not sources:
        raise ValueError(
            "Search returned no usable sources. No research was completed."
        )
    return {"provider": "AgentCore Web Search", "query": query, "sources": sources}


def public_address(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 80, 443}
    ):
        raise ValueError("Only public HTTP(S) pages on standard ports are supported.")
    addresses = {
        row[4][0]
        for row in socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    }
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError("Private, local, and metadata addresses are not accessible.")
    return parsed, sorted(addresses, key=lambda a: (":" in a, a))[0]


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []
        self.title_parts = []
        self.in_title = False
        self.published_at = None

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden += 1
        if tag == "title":
            self.in_title = True
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("property", attrs.get("name", "")).lower() in {
            "article:published_time",
            "datepublished",
            "pubdate",
            "date",
        }:
            self.published_at = attrs.get("content")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())
            if self.in_title:
                self.title_parts.append(data.strip())


def read_page(url):
    """Validate every redirect and pin the validated IP to prevent DNS rebinding."""
    original = url
    with httpx.Client(timeout=20, trust_env=False, follow_redirects=False) as client:
        for _ in range(5):
            parsed, address = public_address(url)
            pinned = httpx.URL(url).copy_with(host=address)
            with client.stream(
                "GET",
                pinned,
                headers={
                    "Host": parsed.netloc,
                    "User-Agent": "AgentMarketplaceResearch/1.0",
                },
                extensions={"sni_hostname": parsed.hostname},
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if not any(v in content_type for v in ["text/", "json", "xml"]):
                    raise ValueError("This source is not a readable text page.")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 1_500_000:
                        raise ValueError("The source exceeds the page-size limit.")
                text = body.decode("utf-8", errors="replace")
                parser = PageText()
                parser.feed(text)
                extracted = " ".join(parser.parts) if "html" in content_type else text
                if len(extracted.strip()) < 200:
                    raise ValueError(
                        "The page did not contain enough readable content."
                    )
                if any(
                    v in extracted[:2500].lower()
                    for v in [
                        "verify you are human",
                        "checking your browser",
                        "enable javascript and cookies to continue",
                    ]
                ):
                    raise ValueError("The publisher blocked access to the page.")
                return {
                    "url": original,
                    "final_url": url,
                    "title": " ".join(parser.title_parts)[:500] or parsed.hostname,
                    "published_at": parser.published_at,
                    "retrieved_at": now(),
                    "read": True,
                    "text": extracted[:12000],
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "bytes_received": len(body),
                }
    raise ValueError("The source redirected too many times.")


def run_code(code, language="python"):
    if (
        language not in {"python", "javascript", "typescript"}
        or not 1 <= len(code) <= 20000
    ):
        raise ValueError("Provide a bounded Python, JavaScript, or TypeScript program.")
    settings = get_settings()
    client = boto3.client(
        "bedrock-agentcore",
        region_name=settings.aws_region,
        config=Config(read_timeout=45, retries={"max_attempts": 0}),
    )
    identifier = settings.code_interpreter_id
    session = client.start_code_interpreter_session(
        codeInterpreterIdentifier=identifier,
        name="marketplace-task",
        sessionTimeoutSeconds=300,
    )["sessionId"]
    try:
        response = client.invoke_code_interpreter(
            codeInterpreterIdentifier=identifier,
            sessionId=session,
            name="executeCode",
            arguments={"language": language, "code": code},
        )
        result = None
        for event in response["stream"]:
            if "result" not in event:
                raise ValueError("The isolated code execution did not return a result.")
            result = event["result"]
        if result is None:
            raise ValueError("The isolated code execution returned an empty stream.")
        structured = result.get("structuredContent", {})
        return {
            "provider": "AgentCore Code Interpreter",
            "session_id": session,
            "language": language,
            "code": code,
            "stdout": structured.get(
                "stdout",
                "\n".join(v.get("text", "") for v in result.get("content", [])),
            )[:16000],
            "stderr": structured.get("stderr", "")[:5000],
            "exit_code": structured.get("exitCode", 1 if result.get("isError") else 0),
            "execution_seconds": structured.get("executionTime"),
            "is_error": bool(result.get("isError")),
        }
    finally:
        client.stop_code_interpreter_session(
            codeInterpreterIdentifier=identifier,
            sessionId=session,
        )


def artifact(name, content):
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", name)
        or ".." in name
        or name.rsplit(".", 1)[-1]
        not in {"md", "txt", "csv", "json", "py", "js", "ts", "sql"}
        or not isinstance(content, str)
        or not 1 <= len(content.encode()) <= 100000
    ):
        raise ValueError("Use a safe text filename and 1–100,000 bytes of content.")
    return {
        "name": name,
        "content": content,
        "bytes": len(content.encode()),
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
        "created_at": now(),
    }
