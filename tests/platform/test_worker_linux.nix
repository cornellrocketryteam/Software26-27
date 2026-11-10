# Exercise real Linux flock/process/signal/prctl behavior without station hardware.
{ pkgs }:
pkgs.runCommand "ground-worker-admission-tests" {
  nativeBuildInputs = [ pkgs.python3 ];
} ''
  mkdir -p worker-tests/tools/platform worker-tests/tests/platform
  cp ${../../tools/platform/worker.py} worker-tests/tools/platform/worker.py
  cp ${../../tools/platform/runtime.py} worker-tests/tools/platform/runtime.py
  cp ${./test_worker.py} worker-tests/tests/platform/test_worker.py
  touch worker-tests/tools/__init__.py worker-tests/tools/platform/__init__.py
  cd worker-tests
  export PYTHONDONTWRITEBYTECODE=1
  python -m unittest discover -s tests/platform -p test_worker.py -v
  touch "$out"
''
