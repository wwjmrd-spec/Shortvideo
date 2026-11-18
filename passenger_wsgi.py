"""
WSGI entry point for Phusion Passenger (cPanel shared hosting).
Place this file in the app root directory on your hosting.
"""
import sys
import os

# Set the app directory
app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, app_dir)

# Activate virtual environment if it exists
venv_path = os.path.join(app_dir, 'venv', 'lib')
if os.path.exists(venv_path):
    # Find the python version directory
    for d in os.listdir(venv_path):
        if d.startswith('python'):
            site_packages = os.path.join(venv_path, d, 'site-packages')
            if os.path.exists(site_packages):
                sys.path.insert(0, site_packages)
                break

# Import the Flask app
from server import app as application
