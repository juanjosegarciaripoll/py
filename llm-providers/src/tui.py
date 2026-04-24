"""Optional terminal provider selector."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


def select_provider(
    provider_names: Sequence[str],
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> str:
    """Return selected provider from a simple terminal selector."""
    if not provider_names:
        msg = "At least one provider must be provided"
        raise ValueError(msg)
    if len(provider_names) == 1:
        return provider_names[0]

    output_fn("Select a provider:")
    for index, provider_name in enumerate(provider_names, start=1):
        output_fn(f"{index}. {provider_name}")

    while True:
        raw_value = input_fn("Enter choice number: ").strip()
        if not raw_value.isdigit():
            output_fn("Invalid choice. Enter a number.")
            continue
        selected_index = int(raw_value)
        if selected_index < 1 or selected_index > len(provider_names):
            output_fn("Choice out of range. Try again.")
            continue
        return provider_names[selected_index - 1]
