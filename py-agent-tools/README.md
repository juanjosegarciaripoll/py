# py-agent-tools

Reusable tool executor primitives for agent runtimes:

- built-in tool executor (`read`, `write`, `edit`, `bash`, `find`, `grep`)
- sandbox policy objects and tool error types
- shell-subset AST and validation primitives for safe interpreter construction
- composable `shlex` tokenizer/parser stages that build the shell-subset AST
- serializable result models for tool outputs
