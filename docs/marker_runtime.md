# Marker Runtime Boundary

Marker PDF requires `Pillow<11`; the default MinerU runtime requires
`Pillow>=11`. They cannot be installed into one RAG-Anything Python environment
without violating one of the published dependency constraints.

Accordingly, `marker`, `marker_full`, and `marker-pdf` are not RAG-Anything
extras and are deliberately excluded from `all`. The release CI installs Marker
only in an empty, separate virtual environment to detect changes in its own
package installation. It does not claim that this is an integrated RAG-Anything
parser worker.

Reintroducing Marker requires a separately specified isolated worker or
container protocol, including file exchange, parser identity, timeout/resource
handling, coverage rules, security scanning, and release evidence. Do not solve
the conflict by pinning or downgrading Pillow, or by installing Marker with
`--no-deps`.
