"""Terminal helpers for provider selection and interactive setup."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from .model_registry import ModelRegistry

from .auth import ApiKeyStore
from .config import ProviderConfig, ProvidersConfig
from .models import MODEL_REGISTRY

type ModelAccessChecker = Callable[[ProviderConfig], tuple[bool, str | None]]


@dataclass(frozen=True)
class _WizardContext:
    """Shared callback/context for interactive wizard functions."""

    model_registry: ModelRegistry
    input_fn: Callable[[str], str]
    output_fn: Callable[[str], None]
    model_access_checker: ModelAccessChecker | None


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


def configure_providers_interactive(
    provider_names: Sequence[str],
    *,
    model_registry: ModelRegistry = MODEL_REGISTRY,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    model_access_checker: ModelAccessChecker | None = None,
) -> ProvidersConfig:
    """Interactively build provider configuration entries."""
    if not provider_names:
        msg = "At least one provider must be provided"
        raise ValueError(msg)

    provider_configs: list[ProviderConfig] = []
    context = _WizardContext(
        model_registry=model_registry,
        input_fn=input_fn,
        output_fn=output_fn,
        model_access_checker=model_access_checker,
    )
    while True:
        output_fn("")
        output_fn("Configure provider entry:")
        name = _prompt_unique_name(
            existing_names={item.name for item in provider_configs},
            input_fn=input_fn,
            output_fn=output_fn,
        )
        provider_config = _configure_provider_interactive(
            provider_names,
            name,
            context,
        )
        provider_configs.append(provider_config)
        if not _confirm(
            "Add another provider? [y/N]: ",
            input_fn=input_fn,
            output_fn=output_fn,
            default=False,
        ):
            break

    default_provider = _choose_default_provider(
        provider_configs,
        input_fn=input_fn,
        output_fn=output_fn,
    )
    return ProvidersConfig(
        providers=tuple(provider_configs),
        default_provider=default_provider,
    )


def _configure_provider_interactive(
    provider_names: Sequence[str],
    name: str,
    context: _WizardContext,
) -> ProviderConfig:
    provider = select_provider(
        provider_names,
        input_fn=context.input_fn,
        output_fn=context.output_fn,
    )
    model = _prompt_model_for_provider(
        provider,
        model_registry=context.model_registry,
        input_fn=context.input_fn,
        output_fn=context.output_fn,
    )
    base_url = _prompt_base_url(
        provider,
        input_fn=context.input_fn,
        output_fn=context.output_fn,
    )
    api_key_env = _prompt_api_key_env(
        provider,
        input_fn=context.input_fn,
        output_fn=context.output_fn,
    )
    _maybe_capture_api_key(
        api_key_env,
        input_fn=context.input_fn,
        output_fn=context.output_fn,
    )

    provider_config = ProviderConfig(
        name=name,
        provider=provider,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
    )
    _run_accessibility_check(
        provider_config,
        input_fn=context.input_fn,
        output_fn=context.output_fn,
        model_access_checker=context.model_access_checker,
    )
    return provider_config


def _prompt_unique_name(
    *,
    existing_names: set[str],
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> str:
    name = _prompt_non_empty(
        "Configuration name (e.g. work-openai): ",
        input_fn=input_fn,
        output_fn=output_fn,
    )
    while name in existing_names:
        output_fn(f"Configuration '{name}' already exists.")
        name = _prompt_non_empty(
            "Configuration name (e.g. work-openai): ",
            input_fn=input_fn,
            output_fn=output_fn,
        )
    return name


def _prompt_model_for_provider(
    provider: str,
    *,
    model_registry: ModelRegistry,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> str:
    known_models = [item.name for item in model_registry.list_models(provider)]
    if not known_models:
        return _prompt_non_empty(
            f"Model for {provider}: ",
            input_fn=input_fn,
            output_fn=output_fn,
        )
    output_fn(f"Known models for {provider}:")
    for index, model_name in enumerate(known_models, start=1):
        output_fn(f"{index}. {model_name}")
    output_fn("0. Enter custom model")
    while True:
        raw_value = input_fn("Select model number [1]: ").strip()
        if not raw_value:
            return known_models[0]
        if not raw_value.isdigit():
            output_fn("Invalid choice. Enter a number.")
            continue
        selected_index = int(raw_value)
        if selected_index == 0:
            return _prompt_non_empty(
                f"Custom model for {provider}: ",
                input_fn=input_fn,
                output_fn=output_fn,
            )
        if 1 <= selected_index <= len(known_models):
            return known_models[selected_index - 1]
        output_fn("Choice out of range. Try again.")


def _prompt_base_url(
    provider: str,
    *,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> str | None:
    prompt = "Base URL"
    if provider == "openai-compatible":
        prompt += " (required)"
    prompt += " [empty for default]: "
    while True:
        base_url = input_fn(prompt).strip()
        if base_url:
            return base_url.rstrip("/")
        if provider == "openai-compatible":
            output_fn("Base URL is required for openai-compatible providers.")
            continue
        return None


def _prompt_api_key_env(
    provider: str,
    *,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> str:
    default_env = ApiKeyStore.env_var_name(provider)
    env_name = input_fn(f"API key environment variable [{default_env}]: ").strip()
    if not env_name:
        return default_env
    if "=" in env_name or " " in env_name:
        output_fn("Invalid env var name. Using default.")
        return default_env
    return env_name


def _maybe_capture_api_key(
    api_key_env: str,
    *,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> None:
    if not _confirm(
        f"Set API key value in current process env ({api_key_env}) now? [y/N]: ",
        input_fn=input_fn,
        output_fn=output_fn,
        default=False,
    ):
        return
    api_key = _prompt_non_empty(
        "API key value: ",
        input_fn=input_fn,
        output_fn=output_fn,
    )
    os.environ[api_key_env] = api_key
    output_fn(f"Stored API key in process environment variable {api_key_env}.")


def _run_accessibility_check(
    provider_config: ProviderConfig,
    *,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
    model_access_checker: ModelAccessChecker | None,
) -> None:
    if model_access_checker is None:
        return
    should_check = _confirm(
        "Check model accessibility now? [y/N]: ",
        input_fn=input_fn,
        output_fn=output_fn,
        default=False,
    )
    if not should_check:
        return
    ok, detail = model_access_checker(provider_config)
    if ok:
        output_fn("Model access check passed.")
        if detail:
            output_fn(detail)
        return
    output_fn("Model access check failed.")
    if detail:
        output_fn(detail)
    proceed = _confirm(
        "Continue with this configuration anyway? [y/N]: ",
        input_fn=input_fn,
        output_fn=output_fn,
        default=False,
    )
    if not proceed:
        msg = "Model accessibility check failed and user aborted configuration"
        raise ValueError(msg)


def _choose_default_provider(
    provider_configs: list[ProviderConfig],
    *,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> str:
    if len(provider_configs) == 1:
        return provider_configs[0].name
    names = [item.name for item in provider_configs]
    output_fn("")
    output_fn("Select default provider configuration:")
    return select_provider(names, input_fn=input_fn, output_fn=output_fn)


def _prompt_non_empty(
    prompt: str,
    *,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> str:
    while True:
        value = input_fn(prompt).strip()
        if value:
            return value
        output_fn("Value cannot be empty.")


def _confirm(
    prompt: str,
    *,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
    default: bool,
) -> bool:
    yes_values = {"y", "yes"}
    no_values = {"n", "no"}
    while True:
        raw_value = input_fn(prompt).strip().lower()
        if not raw_value:
            return default
        if raw_value in yes_values:
            return True
        if raw_value in no_values:
            return False
        output_fn("Please answer with y/yes or n/no.")
