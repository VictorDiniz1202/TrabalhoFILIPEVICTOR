import subprocess
import time
import sys
import os

#Mesmo caminho/bibliotecas
python_path = sys.executable

backend = subprocess.Popen([python_path, "main.py"])


time.sleep(3)

frontend = subprocess.Popen([python_path, "-m", "streamlit", "run", "interface_video.py"])
try:

    backend.wait()
    frontend.wait()
except KeyboardInterrupt:
    backend.terminate()
    frontend.terminate()