import struct


FORMAT = '=5s11s20s15sif'
RECORD_SIZE = struct.calcsize(FORMAT)

class Alumno:
    def __init__(self, codigo: str, nombre: str, apellido: str,
                 carrera: str, ciclo: int, mensualidad: float):
        self.codigo = codigo
        self.nombre = nombre
        self.apellido = apellido
        self.carrera = carrera
        self.ciclo = ciclo
        self.mensualidad = mensualidad

    def __repr__(self):
        return (
            f"Alumno({self.codigo!r}, {self.nombre!r}, {self.apellido!r}, "
            f"{self.carrera!r}, {self.ciclo}, {self.mensualidad})"
        )

def serializar_alumno(alumno: Alumno) -> bytes:
    return struct.pack(
        FORMAT,
        alumno.codigo.encode(),
        alumno.nombre.encode(),
        alumno.apellido.encode(),
        alumno.carrera.encode(),
        alumno.ciclo,
        alumno.mensualidad
    )


def deserializar_alumno(data: bytes) -> Alumno:
    codigo, nombre, apellido, carrera, ciclo, mensualidad = struct.unpack(
        FORMAT, data
    )

    return Alumno(
        codigo.decode().rstrip('\x00'),
        nombre.decode().rstrip('\x00'),
        apellido.decode().rstrip('\x00'),
        carrera.decode().rstrip('\x00'),
        ciclo,
        mensualidad
    )