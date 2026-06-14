#!/usr/bin/env python3
"""Fix Wayland protocol header for C++ compatibility.

Renames the 'namespace' parameter (a C++ keyword) to 'layer_namespace'
in wayland-scanner generated headers.
"""
import sys

with open(sys.argv[1], 'r') as f:
    data = f.read()

data = data.replace('const char *namespace', 'const char *layer_namespace')
data = data.replace(', namespace)', ', layer_namespace)')

with open(sys.argv[2], 'w') as f:
    f.write(data)
