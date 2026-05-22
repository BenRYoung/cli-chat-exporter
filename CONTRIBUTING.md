# Contributing

Thanks for considering a contribution.

## Development Setup

Requirements:

- Node.js 20 or newer.
- Python 3 available as `python3` or `python`.

Run tests:

```bash
npm test
```

Check package contents:

```bash
npm run pack:check
```

## Pull Requests

Please keep changes focused and include tests for behavior changes.

Useful checks before opening a pull request:

```bash
npm test
npm run pack:check
node bin/cce.js help
node bin/cce.js doctor
```

## Privacy

Do not commit real chat histories, export outputs, access tokens, local configuration files, logs, or screenshots containing private content.
