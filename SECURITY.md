# Security Policy

## Scope of the v0.3 primitive (read this first)

refcast v0.3 ships a content-hashed research envelope (`EvidencePack`) and a
pure-offline integrity verifier (`research.verify`). Its scope is deliberately
narrow:

- **Integrity** — we prove the envelope has not been mutated since emission.
- **NOT authenticity** — there is no signature, no signer identity, no PKI.
  Any party can produce a well-formed `EvidencePack` with any content.
  `integrity_valid=True` does **not** prove refcast produced the pack.
- **NOT citation binding** — `source_cids` are hashes of `(url, text)` computed
  at build time, but the original `(url, text)` pairs are not retained in the
  envelope. If you receive an answer's `citations[]` alongside an
  `evidence_pack`, `research.verify` does **not** confirm the citations
  correspond to the pack. To check correspondence, a consumer must re-hash each
  citation independently and compare against `source_cids`.
- **NOT factual correctness** — refcast does not validate whether a citation
  supports the claim it is attached to.

If you need cryptographic authenticity (signed research output), use C2PA 2.2
or IETF SCITT; see AGA MCP Server v2.1.0 for an MCP-native Ed25519-signed
governance-proxy pattern that composes with any research MCP.

## Supported versions

| Version | Security updates |
|:--------|:-----------------|
| 0.3.x   | Yes              |
| 0.2.x   | Critical only    |
| 0.1.x   | No               |

## Reporting a vulnerability

Please report security issues privately by opening a draft **GitHub Security
Advisory** at <https://github.com/sznix/refcast/security/advisories/new>.

If you cannot use GitHub Security Advisories, email the maintainer via the
address listed on <https://github.com/sznix>. Please include:

- A clear description of the issue and its impact
- Steps to reproduce (minimal repro preferred)
- Affected versions
- Your disclosure timeline preference

We aim to acknowledge within 72 hours and issue a fix or mitigation for
**high-severity** issues within 14 days.

## Disclosure policy

- We practice **coordinated disclosure**. We prefer to fix issues before public
  disclosure.
- Credit is given in the `CHANGELOG.md` entry unless the reporter prefers
  otherwise.
- CVEs will be requested for severe issues affecting confidentiality,
  integrity, or availability of user systems.

## Known scope limits (not vulnerabilities, but worth knowing)

The following are documented limitations of the v0.3 primitive. Reporting them
as vulnerabilities is not necessary:

- A third party can produce a well-formed `EvidencePack` with fabricated
  contents; `research.verify` will return `integrity_valid=True` for any
  self-consistent pack (there is no signer check).
- `canonical_json` in refcast is **not RFC 8785 JCS-compliant**. A verifier
  written in a different language (Rust, Go, JavaScript) must replicate
  refcast's exact encoding choices (`sort_keys=True`, `ensure_ascii=True`,
  compact separators, Python's native float serialization) or its hashes
  will diverge on edge-case inputs.
- `source_cids = sha256(url + "\n" + text)` bind the retrieved text at query
  time. If the source URL later changes content, the citation cannot be
  re-verified against the live web; the pack proves only that refcast
  captured those bytes at the timestamp in the pack.
- `env_fingerprint` captures refcast version, Python version, and platform —
  no hostname, no paths, no PII.

## Third-party dependencies

refcast pins major versions of its runtime dependencies (see `pyproject.toml`).
Security advisories on upstream libraries (`fastmcp`, `google-genai`,
`exa-py`, `httpx`, `pydantic`, `keyring`, `typer`) are tracked; we update
pins in a patch release when a high-severity advisory affects the import
surface refcast actually uses.
