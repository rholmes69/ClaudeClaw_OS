"""PIN Hash Generator — run from the ClaudeClaw_OS root directory.

    python security/generate_pin.py

Copy the output into your .env:
    SECURITY_PIN_HASH=<output>
"""

import getpass
import hashlib
import secrets


def generate_pin_hash(pin: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + pin).encode()).hexdigest()
    return f"{salt}:{h}"


def main():
    print("POLAR — PIN Hash Generator")
    print("-" * 30)
    pin = getpass.getpass("Enter PIN (input hidden): ")
    confirm = getpass.getpass("Confirm PIN: ")

    if pin != confirm:
        print("PINs do not match. Aborted.")
        return
    if not pin.strip():
        print("PIN cannot be empty. Aborted.")
        return

    result = generate_pin_hash(pin)
    print(f"\nAdd this to your .env:\n\nSECURITY_PIN_HASH={result}\n")


if __name__ == "__main__":
    main()
