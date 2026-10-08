# Common final evaluation

This directory consumes `shared-cyber-evals==0.1.0` from the sibling package's built wheel.
Its independent `uv.lock` records the wheel hash. It does not change training dependencies,
checkpoint selection, historical results, or the original benchmark harness.

```bash
./evaluation/run.sh --help
./evaluation/run.sh prepare
```

The study manifest supplies model identities and treatment labels. The package supplies common
benchmark profiles, native scorers, model provisioning, isolation policy, and attempt accounting.
Uplift's AuditBench selector is frozen test-only for every model. AuditBench-Agent measurements
remain training diagnostics rather than the common final benchmark.

Preparation does not allocate compute. Evaluation is fail-closed on missing data, native model
bindings, runtime capabilities, or isolation evidence. Do not interpret successful preparation
or offline fixtures as a completed benchmark. The shared package's execution and compatibility
reports record the actual supported/tested state.

Cloud credentials stay on the coordinator. This wrapper never sources or synchronizes the project's
`.env`, and no provider credential is copied into agent environments. Resource cleanup acts only
on resources owned and recorded by the shared pipeline.
