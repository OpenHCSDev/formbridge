# formbridge

Toolkit-neutral reactive forms and UI bridge contracts, shared by
[pyqt-reactive](https://github.com/OpenHCSDev/PyQT-reactive) and headless servers.

Importing any formbridge module loads no GUI toolkit, so a headless process (an
MCP server, a hosted HTTP service) can use the same declarations as the desktop
UI it talks to.

## What is here

- **Forms** (`formbridge.forms`): the parameter model behind generated forms:
  parameter info, type analysis, value contracts and the form service.
  `formbridge.forms.declared_fields` is what every backend reads a field
  through: `DeclaredField` (label, help, default, bounds, search text,
  validation and edit), `FieldPath`, the `Multiline` and `Placeholder` kinds,
  `FormPage` (which tab a top-level group is shown on) and `DeclaredViews`,
  the registry a backend's widget family uses to pick a widget per kind.
- **Services** (`formbridge.services`): help documents and parameter help,
  function-pattern code documents, scope tokens, the pattern data manager,
  path cache, log discovery and streaming, system metrics, ZMQ server scanning,
  window snapshot requests and their observation receipts, and
  `main_thread_dispatch`, which owns work dispatched to one owner thread
  (`QueuedMainThreadDispatcher` for a headless process; pyqt-reactive delivers
  through the Qt event loop).
- **Protocols** (`formbridge.protocols`): registries an application fills:
  form configuration, code generation, component and function selection, log
  discovery, preview formatters.
- **Running-UI bridge** (`formbridge.bridge`): the DTOs, the
  `UiBridgeOperation` family, the client service, descriptor discovery, the ZMQ
  transport and server, the provider registry and the in-process bridge. An
  application declares itself once by subclassing `UiBridgeApplication`;
  pyqt-reactive supplies the Qt window and widget introspection.

Package initializers export nothing; import each name from the module that
defines it.

## Install

```bash
pip install formbridge
```

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src tests
```
