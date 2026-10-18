"""Crea una cuenta de usuario desde la terminal (sirve para el PRIMER administrador).

Uso (desde la carpeta shipment-service, con el entorno virtual activo):
    python -m app.crear_usuario --email admin@logitrack.co --nombre "Administrador" --rol administrador

La contraseña se pide por teclado (no se muestra ni se guarda en ningún archivo).
Para una cuenta de cliente indique además --codigo-cliente <número>.
"""
import argparse
import getpass
import sys

from .database import SessionLocal
from .models import Cliente, Usuario
from .seguridad import ROLES, hashear_password


def main() -> int:
    ap = argparse.ArgumentParser(description="Crea una cuenta de usuario de LogiTrack")
    ap.add_argument("--email", required=True)
    ap.add_argument("--nombre", required=True)
    ap.add_argument("--rol", required=True, choices=ROLES)
    ap.add_argument("--codigo-cliente", type=int, help="Obligatorio solo para el rol cliente")
    args = ap.parse_args()

    clave = getpass.getpass("Contraseña (mínimo 8 caracteres): ")
    if len(clave) < 8:
        print("La contraseña debe tener al menos 8 caracteres.")
        return 1
    if clave != getpass.getpass("Repita la contraseña: "):
        print("Las contraseñas no coinciden.")
        return 1

    db = SessionLocal()
    try:
        email = args.email.strip().lower()
        if db.query(Usuario).filter(Usuario.email == email).first():
            print(f"Ya existe una cuenta con el correo {email}.")
            return 1
        cliente_id = None
        if args.rol == "cliente":
            if args.codigo_cliente is None:
                print("El rol cliente requiere --codigo-cliente.")
                return 1
            cliente = db.query(Cliente).filter(Cliente.codigo_cliente == args.codigo_cliente).first()
            if cliente is None:
                print(f"No existe un cliente con código {args.codigo_cliente}.")
                return 1
            cliente_id = cliente.id
        elif args.codigo_cliente is not None:
            print("Solo el rol cliente se liga a un cliente.")
            return 1
        db.add(Usuario(email=email, nombre=args.nombre, password_hash=hashear_password(clave), rol=args.rol, cliente_id=cliente_id))
        db.commit()
        print(f"Cuenta creada: {email} ({args.rol}).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
