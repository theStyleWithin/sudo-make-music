#!/usr/bin/env python3
"""Print input/output tensor names, shapes and dtypes of .tflite files, to write smm-litert.json.

  python tools/inspect_tflite.py conditioners.tflite dit_model.tflite autoencoder_model.tflite
Needs: pip install ai-edge-litert   (not run in CI)
"""
import sys

try:
    from ai_edge_litert.interpreter import Interpreter
except ImportError:
    from tensorflow.lite.python.interpreter import Interpreter

for path in sys.argv[1:]:
    it = Interpreter(model_path=path)
    print(f"\n== {path}")
    for kind, details in (("input", it.get_input_details()), ("output", it.get_output_details())):
        for d in details:
            print(f"  {kind:6} {d['name']!r:50} shape={list(d['shape'])} dtype={d['dtype'].__name__}")
