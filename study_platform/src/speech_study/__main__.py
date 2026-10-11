import argparse
from pathlib import Path
import uvicorn
from .app import create_app


def main():
    parser = argparse.ArgumentParser(description="Speech Study platform")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", type=Path, default=Path("data/platform"))
    args = parser.parse_args()
    uvicorn.run(create_app(args.data), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
