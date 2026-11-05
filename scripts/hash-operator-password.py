"""Interactively generate the server-side Argon2id hash for RUTEA."""
from getpass import getpass
from argon2 import PasswordHasher


def main() -> None:
    first = getpass("Nueva contraseña de operador: ")
    second = getpass("Repite la contraseña: ")
    if len(first) < 12:
        raise SystemExit("Usa una contraseña de al menos 12 caracteres.")
    if first != second:
        raise SystemExit("Las contraseñas no coinciden.")
    print("Copia este hash Argon2id a HECTOR_OPERATOR_PASSWORD_HASH en el entorno privado:")
    print(PasswordHasher().hash(first))


if __name__ == "__main__":
    main()
