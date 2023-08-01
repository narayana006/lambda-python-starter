# lambda-python-starter

A clean starting point for Python AWS Lambda functions: structure, typed handlers, tests, local invoke and CI.

> **Project status: planning. There is no working code in this repository yet.**
> This README describes what the project will do. Nothing below can be installed or run today.
> Features are ticked off in the checklist as they are built.

## What it is

A project template.

**The problem it solves:** Every new Lambda project repeats the same setup for packaging, testing and local runs.

## Who it is for

Developers starting a new Python Lambda service.

## How it will work

1. You create a repository from the template.
2. You replace the example handler with your own.
3. You test locally and deploy with the included template.

## Planned features

Unticked items are not built yet.

- [ ] Project layout with shared code and several handlers
- [ ] Typed event models
- [ ] Unit tests with sample events
- [ ] Local invoke script
- [ ] Structured JSON logging
- [ ] CI workflow and a SAM template

## Planned usage

This is the intended interface, shown so you can judge the design. **It does not work yet**, and names may change before the first release.

```bash
make test && make invoke EVENT=events/api.json
```

## Contributing

Feedback on the design is the most useful contribution right now. Open an issue to suggest a feature, question an approach or describe your use case. Code contributions are welcome once the first version lands.

## Author

Built and maintained by [Narayana Vemburaj](https://github.com/narayana006).

## License

[MIT](LICENSE)
