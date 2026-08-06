import uvicorn


import os
import sys

# Agregar la raíz del backend al path de python
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from dotenv import load_dotenv
load_dotenv()

def main():
    print("=================================================")
    print("   Iniciando Backend del Bot de Trading (8080)   ")
    print("=================================================")

    # Iniciar FastAPI usando Uvicorn
    uvicorn.run("src.api.app:app", host="0.0.0.0", port=8080, log_level="info")


if __name__ == "__main__":
    main()
