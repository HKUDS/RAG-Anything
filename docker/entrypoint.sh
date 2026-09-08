#!/usr/bin/env bash
#
# Container entrypoint. Sub-commands:
#   shell     interactive shell (default)
#   check     report versions of the runtime dependencies
#   example   run examples/raganything_example.py with the given arguments
# Anything else is executed verbatim.

set -euo pipefail

EXAMPLES_DIR=/opt/raganything-examples

case "${1:-shell}" in
    shell)
        exec /bin/bash
        ;;
    check)
        echo "python:      $(python -V 2>&1)"
        echo "raganything: $(python -c 'import raganything; print(raganything.__version__)' 2>/dev/null || echo unknown)"
        echo "mineru:      $(mineru --version 2>/dev/null || echo 'not installed')"
        echo "torch:       $(python -c 'import torch; print(torch.__version__, "cuda", torch.cuda.is_available())')"
        echo "libreoffice: $(soffice --version 2>/dev/null || echo 'not installed')"
        echo "ffmpeg:      $(ffmpeg -version 2>/dev/null | head -1 || echo 'not installed')"
        python -c "from raganything import RAGAnything; print('import:      ok')"
        ;;
    example)
        shift
        exec python "${EXAMPLES_DIR}/raganything_example.py" "$@"
        ;;
    *)
        exec "$@"
        ;;
esac
