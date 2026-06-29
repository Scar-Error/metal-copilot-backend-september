import os
import sys
import importlib

# Force reload of the business_central module
if 'rfq.business_central' in sys.modules:
    del sys.modules['rfq.business_central']
if 'rfq.tasks' in sys.modules:
    del sys.modules['rfq.tasks']

print("Modules cleared for reload")
