# py-agent-tools

Reusable tool executor primitives for agent runtimes:

- built-in tool executor (`read`, `write`, `edit`, `bash`, `find`, `grep`)
- sandbox policy objects and tool error types
- shell-subset AST and validation primitives for safe interpreter construction
- composable `shlex` tokenizer/parser stages that build the shell-subset AST
- serializable result models for tool outputs

## Bash Runtime Safety Limits

`BuiltinToolExecutor` enforces strict runtime limits for the `bash` tool through
`BashExecutionLimits`:

- `max_execution_seconds` (default `10.0`)
- `max_output_bytes` (default `262144`)
- `max_pipelines` (default `8`)
- `max_commands` (default `32`)

Behavior is strict and deterministic:

- timeout exits with code `124`
- runtime limit violations (output/pipeline/command bounds) exit with code `125`
