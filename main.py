import uvicorn


def main():
    uvicorn.run("api.main:app", host="localhost", port=8000, reload=False)


if __name__ == "__main__":
    main()
