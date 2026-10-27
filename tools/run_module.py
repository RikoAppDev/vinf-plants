"""Run a project module from anywhere: python tools/run_module.py extractor.run --site ncsu

The modules use paths relative to the project root (data/...), so this helper
switches to the root first; IDE run configurations and scripts can then call
any module from any working directory.
"""

import os
import runpy
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: run_module.py <module> [args...]")
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    module = sys.argv[1]
    sys.argv = [module] + sys.argv[2:]
    runpy.run_module(module, run_name="__main__", alter_sys=True)
