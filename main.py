import uvicorn


def main():
    print("=================================================")
    print("   Iniciando Backend del Bot de Trading (8080)   ")
    print("=================================================")

    # Iniciar FastAPI usando Uvicorn
    uvicorn.run("src.api:app", host="0.0.0.0", port=8080, log_level="info")


if __name__ == "__main__":
    main()
