from datetime import datetime, timezone
import hashlib


def main() -> None:
    payload = "INFO7500 blockchain explorer demo"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    print("INFO7500 Docker demo")
    print(f"UTC time: {datetime.now(timezone.utc).isoformat()}")
    print(f"SHA256({payload!r}) = {digest}")


if __name__ == "__main__":
    main()
