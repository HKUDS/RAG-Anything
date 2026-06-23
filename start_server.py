"""Quick start script for the RAG-Anything server with UTF-8 output."""
import subprocess, sys, io, os

# Set env
env = os.environ.copy()
env['PYTHONIOENCODING'] = 'utf-8'
env['PYTHONUTF8'] = '1'

os.chdir(r'c:\Users\98014\RAG-Anything')

proc = subprocess.Popen(
    [sys.executable, 'server.py'],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    env=env,
    text=True,
    encoding='utf-8',
    errors='replace',
    bufsize=1,
)

# Print output in real-time
for line in proc.stdout:
    print(line, end='', flush=True)
