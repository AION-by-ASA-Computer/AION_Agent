# LiteLLM

URL: https://docs.haystack.deepset.ai/reference/integrations-litellm

---

On this page

Copy

Copy pageCopy page as Markdown for LLMs

View as MarkdownView this page as plain text

Export as PDFSave this page as a PDF file

Ask AI about this page

ChatGPTOpen this page in ChatGPT

ClaudeOpen this page in Claude

PerplexityOpen this page in Perplexity

# LiteLLM

## haystack\_integrations.components.generators.litellm.chat.chat\_generator

### LiteLLMChatGenerator

Completes chats using any of 100+ LLM providers via LiteLLM.

LiteLLM routes to OpenAI, Anthropic, Google, AWS Bedrock, Azure, Cohere, Mistral, Groq, and many more through a single unified interface.

Model names use LiteLLM format: `provider/model-name`, e.g. `anthropic/claude-sonnet-4-20250514`, `openai/gpt-4o`, `bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0`.

See [https://docs.litellm.ai/docs/providers](https://docs.litellm.ai/docs/providers) for the full list.

Usage example:

python

```
from haystack_integrations.components.generators.litellm import LiteLLMChatGeneratorfrom haystack.dataclasses import ChatMessagegenerator = LiteLLMChatGenerator(    model="anthropic/claude-sonnet-4-20250514",    generation_kwargs={"max_tokens": 1024, "temperature": 0.7},)messages = [    ChatMessage.from_system("You are a helpful assistant"),    ChatMessage.from_user("What's Natural Language Processing?"),]result = generator.run(messages=messages)print(result["replies"][0].text)
```

#### **init**

python

```
__init__(    *,    api_key: Secret | None = None,    model: str = "openai/gpt-4o",    streaming_callback: StreamingCallbackT | None = None,    api_base_url: str | None = None,    generation_kwargs: dict[str, Any] | None = None,    tools: ToolsType | None = None) -> None
```

Create a LiteLLMChatGenerator instance.

**Parameters:**

-   **api\_key** (`Secret | None`) – The API key for the provider. Optional: when not set, LiteLLM resolves credentials itself from the provider's standard environment variable (e.g. `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). Pass a `Secret` only when you want Haystack to manage and serialize the key explicitly.
-   **model** (`str`) – The model name in LiteLLM format (provider/model-name).
-   **streaming\_callback** (`StreamingCallbackT | None`) – A callback function invoked with each new StreamingChunk.
-   **api\_base\_url** (`str | None`) – Custom API base URL (e.g. for a self-hosted LiteLLM proxy).
-   **generation\_kwargs** (`dict[str, Any] | None`) – Additional parameters passed to litellm.completion(). See [https://docs.litellm.ai/docs/completion/input](https://docs.litellm.ai/docs/completion/input) for details.
-   **tools** (`ToolsType | None`) – A list of Tool / Toolset objects the model can prepare calls for.

#### run

python

```
run(    messages: list[ChatMessage] | str,    streaming_callback: StreamingCallbackT | None = None,    generation_kwargs: dict[str, Any] | None = None,    *,    tools: ToolsType | None = None) -> dict[str, list[ChatMessage]]
```

Invoke chat completion via LiteLLM.

**Parameters:**

-   **messages** (`list[ChatMessage] | str`) – Input messages as ChatMessage instances. If a string is provided, it is converted to a list containing a ChatMessage with user role.
-   **streaming\_callback** (`StreamingCallbackT | None`) – Override the streaming callback for this call.
-   **generation\_kwargs** (`dict[str, Any] | None`) – Override generation parameters for this call.
-   **tools** (`ToolsType | None`) – Override tools for this call.

**Returns:**

-   `dict[str, list[ChatMessage]]` – A dict with key `replies` containing ChatMessage instances.

#### run\_async

python

```
run_async(    messages: list[ChatMessage] | str,    streaming_callback: StreamingCallbackT | None = None,    generation_kwargs: dict[str, Any] | None = None,    *,    tools: ToolsType | None = None) -> dict[str, list[ChatMessage]]
```

Async version of run(). Invoke chat completion via LiteLLM.

**Parameters:**

-   **messages** (`list[ChatMessage] | str`) – Input messages as ChatMessage instances. If a string is provided, it is converted to a list containing a ChatMessage with user role.
-   **streaming\_callback** (`StreamingCallbackT | None`) – Override the streaming callback for this call.
-   **generation\_kwargs** (`dict[str, Any] | None`) – Override generation parameters for this call.
-   **tools** (`ToolsType | None`) – Override tools for this call.

**Returns:**

-   `dict[str, list[ChatMessage]]` – A dict with key `replies` containing ChatMessage instances.

#### to\_dict

python

```
to_dict() -> dict[str, Any]
```

Serialize this component to a dictionary.

#### from\_dict

python

```
from_dict(data: dict[str, Any]) -> LiteLLMChatGenerator
```

Deserialize a component from a dictionary.