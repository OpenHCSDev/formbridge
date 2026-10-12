# Changelog

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
