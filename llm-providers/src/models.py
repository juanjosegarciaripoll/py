"""Model registry."""

models: dict[str, dict[str, dict[str, int]]] = {
    "anthropic": {
        "claude-3-5-sonnet-20241022": {"context_window": 200000, "max_tokens": 8192},
        "claude-3-5-haiku-20241022": {"context_window": 200000, "max_tokens": 8192},
    },
    "openai": {
        "gpt-4o": {"context_window": 128000, "max_tokens": 4096},
        "gpt-4o-mini": {"context_window": 128000, "max_tokens": 16384},
    },
}
