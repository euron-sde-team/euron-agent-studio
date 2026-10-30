# ADR 0010: Flows compute with a closed expression language, never with user code

## Status

Accepted.

## Context

Flows need small computations everywhere: put a ticket's subject into a prompt, branch on a
classification, total an invoice, reshape an API response. Many workflow tools offer a code
node for this. In a multi-tenant service, user code running on the workers means sandboxing
(containers, gVisor, resource limits) on the hottest path, a large attack surface next to
every workspace's secrets, and flows that the Python exporter cannot translate safely.

## Decision

There is no code node. Computation goes through four small, closed languages, all in
`engine/runtime.py`:

- **Templates**: `{{ path | filter(args) }}` with paths into inputs, earlier nodes, loop
  items and secrets, and a fixed set of filters (`json`, `upper`, `lower`, `trim`, `length`,
  `first`, `last`, `join`, `default`, `round`). No attribute access on Python objects, no
  calls.
- **Conditions**: named routes, each a set of rules joined by all or any, plus an `else`
  branch, with a closed list of operators (`equals`, `contains`, `starts_with`,
  `greater_than`, `is_empty`, `in_list`, `matches` and their counterparts). `matches` runs on
  RE2, which guarantees linear time.
- **The calculator**: arithmetic parsed with Python's `ast` and evaluated by a walker that
  allows numbers, `+ - * / // % **`, parentheses, `pi`, `e` and seven functions (`round`,
  `min`, `max`, `abs`, `sqrt`, `floor`, `ceil`), with limits on powers and magnitudes.
- **JSON transforms**: JMESPath, a query language with no side effects.

Validation checks every reference (and every expression that can be checked without run
data) before a flow can be published, and the same module is embedded in exported scripts
([ADR 0007](0007-python-export-embeds-the-runtime.md)).

## Consequences

Positive:

- Nothing a builder writes can execute code, read files or open sockets on a worker; the
  only network access a flow has is the HTTP node, behind the outbound guard.
- Expressions are statically checkable, so the editor shows broken references inline.
- Exported scripts reproduce every computation exactly, because they run the same module.

Trade-offs:

- Some logic needs several nodes, or an HTTP call to a service the builder controls,
  where a code node would be one block.
- New filters, operators or functions are product changes, made in one place and covered
  by the runtime's unit tests.

## Alternatives considered

- **A sandboxed Python or JavaScript node** (containers, WebAssembly, a restricted
  interpreter). Flexible, but every sandbox has a history of escapes, and the cost (cold
  starts, resource limits, a second runtime to secure) lands on every run.
- **Jinja2 templates.** Familiar, but its sandbox has also been escaped, and its power (loops,
  macros, attribute access) is more than prompts need.
