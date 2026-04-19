# Models Reference — ClaudeClaw OS

---

## Models currently in use

| Model | Used by |
|---|---|
| `claude-sonnet-4-6` | All agents — Main, Comms, Content, Ops, Research, Finance, CI/CD |
| `claude-opus-4-6` | Optional Main Agent override via `MAIN_AGENT_MODEL` env var |
| `gemini-2.0-flash-lite` | Hive Mind — memory ingest, consolidation, memory controller |
| `gemini-embedding-001` | Hive Mind — semantic embeddings for memory search |

---

## Available Claude models for agents

| Model ID | Tier | Best for |
|---|---|---|
| `claude-haiku-4-5-20251001` | Fast / cheap | Simple tasks, high-volume routing, low-latency responses |
| `claude-sonnet-4-6` | Balanced | Default for all agents — good quality/cost ratio |
| `claude-opus-4-7` | Most capable | Complex multi-hop reasoning, nuanced judgment calls |

---

## How to change an agent's model

### Option A — Edit the agent YAML

Update the `model:` field in `agents/{id}/agent.yaml`:

```yaml
model: claude-opus-4-7
```

The dashboard and versioning system read this field — the change is reflected
immediately on next agent invocation.

### Option B — Edit the agent Python module

Change the `MODEL` constant at the top of `agents/{id}_agent.py`:

```python
MODEL = "claude-opus-4-7"
```

### Option C — Environment variable (Main Agent only)

Override the Main Agent model without touching any file:

```
# .env
MAIN_AGENT_MODEL=claude-opus-4-7
```

---

## Recommendations

| Scenario | Recommended model |
|---|---|
| Default / everyday use | `claude-sonnet-4-6` |
| Main Agent on complex projects | `claude-opus-4-7` |
| High message volume / cost reduction | `claude-haiku-4-5-20251001` |
| Hive Mind memory operations | `gemini-2.0-flash-lite` (already configured) |

---

## Using Ollama local models

Ollama runs a local inference server with an OpenAI-compatible API at
`http://localhost:11434/v1`. Agents can use it by replacing the Anthropic client
with the OpenAI client pointed at Ollama — no cloud API key required.

### Install the OpenAI SDK

```bash
pip install openai
```

### Swap the client in an agent

Replace the Anthropic client block at the top of `agents/{id}_agent.py`:

```python
# Before (Anthropic)
import anthropic
self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# After (Ollama via OpenAI-compatible API)
from openai import OpenAI
self.client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
MODEL = "llama3.2"   # any model you have pulled in Ollama
```

Then update each `client.messages.create()` call to use the OpenAI chat format:

```python
response = self.client.chat.completions.create(
    model=MODEL,
    messages=[{"role": "system", "content": SYSTEM_PROMPT},
              {"role": "user",   "content": instruction}],
)
raw = response.choices[0].message.content
```

### Tool use compatibility

Not all Ollama models support function calling. Only use tool-enabled agents
(CI/CD, Research, Comms) with models that declare tool support:

| Ollama model | Tool use | Notes |
|---|---|---|
| `llama3.1` | Yes | Good general tool caller |
| `llama3.2` | Yes | Faster, smaller footprint |
| `qwen2.5` | Yes | Strong at structured output |
| `mistral-nemo` | Yes | Good for European languages |
| `mistral` | Partial | Basic tool support only |
| `phi3` | No | Use for tool-less agents only |
| `gemma2` | No | Use for tool-less agents only |
| `deepseek-r1` | No | Reasoning model, no tools |

**Tool-less agents** (Content, Finance) work with any Ollama model.
**Tool-using agents** (CI/CD, Research, Comms) require a model from the "Yes" row above.

### Check what you have installed

```bash
ollama list
```

### Pull a new model

```bash
ollama pull llama3.2
ollama pull qwen2.5
```

### Recommended Ollama models per agent

| Agent | Recommended Ollama model | Reason |
|---|---|---|
| Main | `llama3.1` or `qwen2.5` | Needs strong routing/classification |
| Comms | `llama3.2` | Tool use + good writing quality |
| Content | `llama3.2` or `gemma2` | No tools needed, good at prose |
| Finance | `qwen2.5` | Strong at structured numeric output |
| Ops | `llama3.2` | Light operations, no tools needed |
| Research | `llama3.1` | Tool use + strong reasoning |
| CI/CD | `qwen2.5` or `llama3.1` | Tool use required |

### Limitations vs Claude

- **Context window** — most Ollama models have shorter context than Claude Sonnet/Opus
- **Tool reliability** — local models call tools less reliably; complex multi-tool chains may fail
- **JSON output** — may require adding `format: json` or stricter prompting
- **Hive Mind** — the Hive Mind always uses Gemini regardless of agent model setting; this cannot be changed via Ollama

### Zero-cost setup for testing

Run Content and Finance agents on Ollama (`gemma2` or `phi3`) and keep the
Main Agent on `claude-sonnet-4-6` for reliable routing. This reduces API costs
while keeping delegation accuracy high.

---

## Tool/skill compatibility across models

Agent skills (browser, bbc_briefing, remotion, git tools, GitHub API) are
model-agnostic — they are plain JSON schemas. Any model that supports function
calling can use them without modification to the skill files themselves.

### Which models support tool/function calling

| Provider | Models | Tool support |
|---|---|---|
| **Anthropic** | All Claude models (Haiku, Sonnet, Opus) | Full |
| **Ollama** | llama3.1, llama3.2, qwen2.5, mistral-nemo | Full |
| **Ollama** | mistral | Partial |
| **Ollama** | phi3, gemma2, deepseek-r1 | None |
| **OpenAI** | gpt-4o, gpt-4-turbo, gpt-3.5-turbo | Full |
| **Google** | gemini-1.5-pro, gemini-2.0-flash | Full |

### What changes when switching models

The skill schemas transfer without changes. Only the **agent client wrapper**
needs updating — the call format differs slightly between providers:

```python
# Anthropic SDK (current default)
response = self.client.messages.create(
    tools=MY_TOOLS, tool_choice={"type": "auto"}, ...
)
for block in response.content:
    if block.type == "tool_use":
        result = execute_tool(block.name, block.input)

# OpenAI SDK (also used for Ollama)
response = self.client.chat.completions.create(
    tools=MY_TOOLS, tool_choice="auto", ...
)
for call in response.choices[0].message.tool_calls or []:
    result = execute_tool(call.function.name, json.loads(call.function.arguments))
```

### Agents that require tool support

Only switch these agents to a tool-capable model:

| Agent | Tools used | Requires tool support |
|---|---|---|
| CI/CD | git_*, github_* | Yes |
| Research | browser, bbc_briefing | Yes |
| Comms | browser | Yes |
| Content | remotion_* | Yes |
| Main | route_to_agent (internal) | Yes |
| Ops | scaffold (Python, not a tool call) | No |
| Finance | None | No |

---

## Related

- [AGENT_SKILLS.md](AGENT_SKILLS.md) — Skills and tools available per agent
- [CREATE_AGENT.md](CREATE_AGENT.md) — Creating a new agent (includes model selection)
- `agents/{id}/agent.yaml` — Per-agent model configuration
- `sdk_bridge/main_agent.py` — Main Agent model setting (`MAIN_AGENT_MODEL`)
