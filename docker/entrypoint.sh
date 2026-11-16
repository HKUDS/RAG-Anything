#!/bin/sh
set -e

# Default to executing the passed arguments if provided
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

# If no arguments provided, run a python interactive shell or default banner
echo "=========================================================="
echo " RAG-Anything Container Environment"
echo "=========================================================="
echo "Python: $(python --version)"
echo "RAG-Anything is installed and ready in /app."
echo ""
echo "Usage examples:"
echo "  docker run -it --rm raganything python examples/raganything_example.py"
echo "  docker compose run --rm raganything python -c 'import raganything; print(raganything.__version__)'"
echo "=========================================================="

exec python
