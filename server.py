import os

from dotenv import load_dotenv
from waitress import serve

from app import app


load_dotenv()


def env_int(name, default):
    value = os.getenv(name)
    if not value:
        return default

    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {value!r}") from exc


if __name__ == '__main__':
    host = os.getenv('PICUP_HOST', '127.0.0.1')
    port = env_int('PICUP_PORT', 36677)
    threads = env_int('PICUP_THREADS', 4)

    print(f'Starting PicUp on http://{host}:{port} with Waitress ({threads} threads)', flush=True)
    serve(app, host=host, port=port, threads=threads)
