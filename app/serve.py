import uvicorn

from app.config import Settings
from app.main import create_app


def main():
    settings = Settings()
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0", port=8000, access_log=False, server_header=False,
        proxy_headers=bool(settings.trusted_proxy_ips),
        forwarded_allow_ips=",".join(settings.trusted_proxy_ips),
        timeout_graceful_shutdown=20,
        limit_concurrency=128,
    )


if __name__ == "__main__":
    main()
