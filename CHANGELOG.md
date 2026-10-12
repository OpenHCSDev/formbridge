# Changelog

## 0.1.5

Requires `python-introspect>=0.3.0,<0.4` (was `<0.3`), `objectstate>=4.0.1,<5`
and `zmqruntime>=0.6.5,<0.7`.

Wire and stored form: unchanged. python-introspect 0.3 stores a field whose
declared type admits several classes (a union of dataclasses, an abstract
dataclass, a registered family) as `{tag: fields}`. No bridge request, result,
envelope or descriptor file has such a field, so a 0.1.4 and a 0.1.5 bridge
peer exchange the same JSON and descriptor files written by 0.1.4 still read.
Fields declared `type[Family]` (`field_filter`, `status`) keep the registry
key spelling.

A field declared as one concrete class carries that class only; a subclass
with more fields is refused when decoded (as before). The identity, address
and connection fields of the bridge results are of this kind
(`UiActionIdentity`, `UiCodeDocumentIdentity`, `UiStateSurfaceIdentity`,
`UiWindowIdentity`, `UiSemanticAddress`, `EndpointConnectionSpec`); the
requests that inherit from them are narrowed before they are stored there.

Fixed:

- A refused, busy or accepted `mutate_object_state_field` result put the whole
  request in its `address` field, so the client could not decode it
  (`UiSemanticAddress received undeclared field(s)`) and the caller saw a
  decoding error instead of the refusal. The result now carries
  `request.as_address()`. `UiSemanticAddress.as_address()` is new.

## 0.1.4

Requires ObjectState 4 (`objectstate>=4.0.0,<5`). No code change: formbridge
calls none of the names ObjectState 4 removed (the global config setters and
`get_current_global_config`).

## 0.1.3

Requires `metaclass-registry>=0.4.0`, `objectstate>=3.0.1,<4` and
`zmqruntime>=0.6.4,<0.7`.

Changed:

- A type has one inline-widget factory and one preview formatter.
  `PreviewFormatterRegistry.register` and the inline-widget factory
  registration raise `ValueError` when a different registrant is given for a
  type that already has one, instead of replacing it. Registering the same
  one again does nothing.

## 0.1.2

Requires ObjectState 3 (`objectstate>=3.0,<4`).

- `strategies.preview_formatting` reads a config group's abbreviation with
  `objectstate.lazy_factory.get_group_abbreviation`, the one owner of that
  lookup in ObjectState 3 (`GROUP_ABBREVIATIONS_REGISTRY` is removed there).
  The module's own copy of the lookup is deleted; the name
  `formbridge.strategies.preview_formatting.get_group_abbreviation` is now
  ObjectState's function.

## 0.1.1

Added:

- `forms.raw_display_value.RawDisplayValue`: a form's edited value kept with
  the value it shows.

## 0.1.0

First release.

- The Qt-free tier of pyqt-reactive 0.5.0 moved here with its module paths
  under `formbridge` (forms model, help documents, parameter help, the
  function-pattern code document, scope tokens, the pattern data manager,
  provider registries, preview formatters and strategies, path cache, logs,
  system metrics, ZMQ server scanning). The Qt-free manager hooks are
  `formbridge.managers`; the scope colour strategy is `formbridge.theming`.
- `services.main_thread_dispatch`: `MainThreadDispatcher` and
  `QueuedMainThreadDispatcher`.
- `services.window_snapshot`: window snapshot requests, frame conditions and
  observation receipts; the toolkit implements each `FrameObservation` kind.
- `bridge`: the running-UI bridge from OpenHCS, generic over the application
  (`UiBridgeApplication`), with `contracts` (result envelopes and errors),
  `connection` (`EndpointConnectionSpec`), `selection` and `runtime_platform`.
  Window identities declare their window-manager scope alias; system
  ObjectState scopes are a registered `HiddenObjectStateScope` family.
