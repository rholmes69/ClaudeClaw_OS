"""LLM Client Factory — unified interface for Anthropic and Ollama

Agents call get_llm_client(model) to get back a client whose .create()
method works identically regardless of provider.

Model prefix rules:
  "claude-*"       → Anthropic API
  "ollama/<name>"  → Ollama local API (OpenAI-compatible, localhost:11434)

Response objects are normalised so agents can use the same loop:

    response = self.client.create(messages, system=..., tools=...)
    response.stop_reason   # "tool_use" or "end_turn"
    for block in response.content:
        block.type          # "text" or "tool_use"
        block.text          # str  (text blocks only)
        block.id            # str  (tool_use blocks only)
        block.name          # str  (tool_use blocks only)
        block.input         # dict (tool_use blocks only)
"""

import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


# ── Normalised response types ─────────────────────────────────────────────────

@dataclass
class TextBlock:
    type: str = "text"
    text: str = ""


@dataclass
class ToolUseBlock:
    type: str = "tool_use"
    id: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)


@dataclass
class NormalizedResponse:
    content: list        # list of TextBlock | ToolUseBlock
    stop_reason: str     # "end_turn" | "tool_use"


# ── Anthropic client wrapper ──────────────────────────────────────────────────

class AnthropicClient:
    """Thin wrapper around the Anthropic SDK that returns NormalizedResponse."""

    def __init__(self, model: str):
        import anthropic as _anthropic
        self.model = model
        self._client = _anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def create(
        self,
        messages: list,
        system: Optional[str] = None,
        tools: Optional[list] = None,
        max_tokens: int = 2048,
        tool_choice: Optional[dict] = None,
    ) -> NormalizedResponse:
        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=max_tokens,
            messages=messages,
        )
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

        response = self._client.messages.create(**kwargs)
        # Return native Anthropic blocks unchanged — they already expose .type,
        # .text, .name, .input, .id and are serialisable by the SDK on the next round.
        return NormalizedResponse(content=response.content, stop_reason=response.stop_reason)


# ── Ollama client wrapper ─────────────────────────────────────────────────────

class OllamaClient:
    """OpenAI-compatible client pointed at the local Ollama server."""

    OLLAMA_BASE_URL = "http://localhost:11434/v1"

    def __init__(self, model: str):
        from openai import OpenAI
        self.model = model
        self._client = OpenAI(base_url=self.OLLAMA_BASE_URL, api_key="ollama")

    def create(
        self,
        messages: list,
        system: Optional[str] = None,
        tools: Optional[list] = None,
        max_tokens: int = 2048,
        tool_choice: Optional[dict] = None,
    ) -> NormalizedResponse:
        oai_messages = self._convert_messages(messages, system)

        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=max_tokens,
            messages=oai_messages,
        )
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {}),
                    },
                }
                for t in tools
            ]
        if tool_choice:
            kwargs["tool_choice"] = self._convert_tool_choice(tool_choice)

        response = self._client.chat.completions.create(**kwargs)
        return self._normalize(response)

    # ── conversion helpers ────────────────────────────────────────────────────

    def _convert_messages(self, messages: list, system: Optional[str]) -> list:
        oai: list = []
        if system:
            oai.append({"role": "system", "content": system})

        for msg in messages:
            role    = msg["role"]
            content = msg["content"]

            if isinstance(content, str):
                oai.append({"role": role, "content": content})
                continue

            if isinstance(content, list):
                # ── tool results (user turn after tool_use) ───────────────
                tool_results = [
                    b for b in content
                    if isinstance(b, dict) and b.get("type") == "tool_result"
                ]
                if tool_results:
                    for tr in tool_results:
                        oai.append({
                            "role": "tool",
                            "tool_call_id": tr["tool_use_id"],
                            "content": str(tr.get("content", "")),
                        })
                    continue

                # ── assistant turn (may contain tool_use blocks) ───────────
                if role == "assistant":
                    text       = ""
                    tool_calls = []
                    for block in content:
                        btype = getattr(block, "type", None)
                        if btype == "text":
                            text = getattr(block, "text", "")
                        elif btype == "tool_use":
                            tool_calls.append({
                                "id":   getattr(block, "id", str(uuid.uuid4())),
                                "type": "function",
                                "function": {
                                    "name":      getattr(block, "name", ""),
                                    "arguments": json.dumps(getattr(block, "input", {})),
                                },
                            })
                    entry: dict = {"role": "assistant", "content": text}
                    if tool_calls:
                        entry["tool_calls"] = tool_calls
                    oai.append(entry)
                    continue

                # ── plain user content blocks ──────────────────────────────
                parts = []
                for b in content:
                    if isinstance(b, dict):
                        parts.append(b.get("text", ""))
                    else:
                        parts.append(getattr(b, "text", str(b)))
                oai.append({"role": role, "content": " ".join(parts)})

        return oai

    def _convert_tool_choice(self, tool_choice: dict) -> Any:
        tc_type = tool_choice.get("type", "auto")
        if tc_type == "tool":
            return {"type": "function", "function": {"name": tool_choice["name"]}}
        if tc_type == "any":
            return "required"
        return "auto"

    def _normalize(self, response) -> NormalizedResponse:
        choice      = response.choices[0]
        message     = choice.message
        finish      = choice.finish_reason or "stop"
        stop_reason = "end_turn"

        blocks: list = []
        if message.content:
            blocks.append(TextBlock(text=message.content))

        if message.tool_calls:
            stop_reason = "tool_use"
            for call in message.tool_calls:
                try:
                    input_dict = json.loads(call.function.arguments)
                except Exception:
                    input_dict = {}
                blocks.append(ToolUseBlock(
                    id=call.id,
                    name=call.function.name,
                    input=input_dict,
                ))
        elif finish in ("stop", "length"):
            stop_reason = "end_turn"

        return NormalizedResponse(content=blocks, stop_reason=stop_reason)


# ── Factory ───────────────────────────────────────────────────────────────────

def get_llm_client(model: str) -> "AnthropicClient | OllamaClient":
    """
    Return the correct LLM client for the given model string.

    Examples:
        get_llm_client("claude-sonnet-4-6")   → AnthropicClient
        get_llm_client("ollama/llama3.2")      → OllamaClient (model="llama3.2")
        get_llm_client("ollama/qwen2.5")       → OllamaClient (model="qwen2.5")
    """
    if model.startswith("ollama/"):
        return OllamaClient(model=model[len("ollama/"):])
    return AnthropicClient(model=model)


# ── Ollama model catalogue ────────────────────────────────────────────────────

# Models confirmed to support function/tool calling via Ollama.
OLLAMA_TOOL_CAPABLE = {
    "llama3.1",
    "llama3.2",
    "qwen2.5",
    "mistral-nemo",
}

def ollama_model_supports_tools(model: str) -> bool:
    """Return True if the ollama model is known to support tool/function calling."""
    if model.startswith("ollama/"):
        model = model[len("ollama/"):]
    base = model.split(":")[0]  # strip tag (e.g. "llama3.2:latest" → "llama3.2")
    return base in OLLAMA_TOOL_CAPABLE
