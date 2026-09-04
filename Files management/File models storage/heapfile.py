import os
import struct 
from record import (Alumno, RECORD_SIZE, 
                    serializar_alumno, deserializar_alumno)


# imagine this is a define in C++
MOVE_THE_LAST = True
FREE_LIST = False

# formats
FILE_HEADER_FORMAT = '=ii?'
PAGE_HEADER_FORMAT = '=iii'
FREE_PTR_FORMAT = '=i'
FREE_SLOT_FORMAT = '=ii'

# default value for free slot in free list strategie
FREE_SLOT_MARKER = -1

# size in bytes of each format
FILE_HEADER_SIZE = struct.calcsize(FILE_HEADER_FORMAT)
PAGE_HEADER_SIZE = struct.calcsize(PAGE_HEADER_FORMAT)
FREE_PTR_SIZE = struct.calcsize(FREE_PTR_FORMAT)
FREE_SLOT_SIZE = struct.calcsize(FREE_SLOT_FORMAT)

PAGE_SIZE = 512

class FileHeader:
    def __init__(self, page_size: int, num_pages: int, delete_mode: bool):
        self.page_size = page_size
        self.num_pages = num_pages
        self.delete_mode = delete_mode


class PageHeader:
    def __init__(self, registros: int, registros_activos: int, free_list: int):
        self.registros = registros
        self.registros_activos = registros_activos
        self.free_list = free_list


class Heapfile:
    def __init__(self, filename: str, delete_mode: bool):
        self.filename = filename

        if not os.path.exists(filename) or os.path.getsize(filename) == 0:
            self.file_header = FileHeader(PAGE_SIZE, 0, delete_mode)
            self.escribir_file_header(self.filename, self.file_header)
        else:
            self.file_header = self.leer_file_header(self.filename)

        self.max_records_per_page = (
            (self.file_header.page_size - PAGE_HEADER_SIZE) // RECORD_SIZE
        )

    def escribir_file_header(filename: str, file_header: FileHeader):
        with open(filename, 'wb') as file:
            file.write(struct.pack(
                FILE_HEADER_FORMAT,
                file_header.page_size,
                file_header.num_pages,
                file_header.delete_mode
            ))


    def leer_file_header(filename: str) -> FileHeader:
        with open(filename, 'rb') as file:
            data = file.read(FILE_HEADER_SIZE)

        if len(data) != FILE_HEADER_SIZE:
            raise ValueError('El archivo no contiene un File Header válido')

        page_size, num_pages, delete_mode = struct.unpack(FILE_HEADER_FORMAT, data)
        return FileHeader(page_size, num_pages, delete_mode)


    def _page_offset(self, page_id: int) -> int:
        return FILE_HEADER_SIZE + page_id * self.file_header.page_size

    def _record_offset(self, page_id: int, slot_id: int) -> int:
        return (
            self._page_offset(page_id)
            + PAGE_HEADER_SIZE
            + slot_id * RECORD_SIZE
        )

    def _leer_page_header(self, file, page_id: int) -> PageHeader:
        file.seek(self._page_offset(page_id))
        data = file.read(PAGE_HEADER_SIZE)

        if len(data) != PAGE_HEADER_SIZE:
            raise ValueError(f'Page Header inválido en la página {page_id}')

        registros, registros_activos, free_list = struct.unpack(
            PAGE_HEADER_FORMAT, data
        )
        return PageHeader(registros, registros_activos, free_list)

    def _escribir_page_header(self, file, page_id: int, header: PageHeader):
        file.seek(self._page_offset(page_id))
        file.write(struct.pack(
            PAGE_HEADER_FORMAT,
            header.registros,
            header.registros_activos,
            header.free_list
        ))

    def _actualizar_file_header(self, file):
        file.seek(0)
        file.write(struct.pack(
            FILE_HEADER_FORMAT,
            self.file_header.page_size,
            self.file_header.num_pages,
            self.file_header.delete_mode
        ))

    def _crear_pagina_con_registro(self, file, record_data: bytes):
        page_id = self.file_header.num_pages
        slot_id = 0

        nueva_pagina = bytearray(self.file_header.page_size)

        struct.pack_into(
            PAGE_HEADER_FORMAT,
            nueva_pagina,
            0,
            1,      # registros
            1,      # registros_activos
            -1      # free_list vacía
        )

        nueva_pagina[
            PAGE_HEADER_SIZE:PAGE_HEADER_SIZE + RECORD_SIZE
        ] = record_data

        file.seek(self._page_offset(page_id))
        file.write(nueva_pagina)

        self.file_header.num_pages += 1
        self._actualizar_file_header(file)

        return (page_id, slot_id)

    # ------------------------------------------------------
    # ADD
    # ------------------------------------------------------

    def add_move_the_last(self, record: Alumno):
        record_data = serializar_alumno(record)

        with open(self.filename, 'r+b') as file:
            for page_id in range(self.file_header.num_pages):
                header = self._leer_page_header(file, page_id)

                if header.registros < self.max_records_per_page:
                    slot_id = header.registros

                    file.seek(self._record_offset(page_id, slot_id))
                    file.write(record_data)

                    header.registros += 1
                    header.registros_activos += 1
                    self._escribir_page_header(file, page_id, header)

                    return (page_id, slot_id)

            return self._crear_pagina_con_registro(file, record_data)

    def add_free_list(self, record: Alumno):
        record_data = serializar_alumno(record)

        with open(self.filename, 'r+b') as file:
            # Primero: reutilizar un slot eliminado en cualquier página.
            for page_id in range(self.file_header.num_pages):
                header = self._leer_page_header(file, page_id)

                if header.free_list != -1:
                    slot_id = header.free_list
                    record_offset = self._record_offset(page_id, slot_id)

                    file.seek(record_offset)
                    free_slot_data = file.read(FREE_SLOT_SIZE)
                    marker, next_free = struct.unpack(
                        FREE_SLOT_FORMAT, free_slot_data
                    )
                    if marker != FREE_SLOT_MARKER:
                        raise ValueError(
                            f'FREE LIST corrupta en ({page_id}, {slot_id})'
                        )

                    file.seek(record_offset)
                    file.write(record_data)

                    header.free_list = next_free
                    header.registros_activos += 1
                    self._escribir_page_header(file, page_id, header)

                    return (page_id, slot_id)

            # Segundo: usar un slot nuevo dentro de una página existente.
            for page_id in range(self.file_header.num_pages):
                header = self._leer_page_header(file, page_id)

                if header.registros < self.max_records_per_page:
                    slot_id = header.registros

                    file.seek(self._record_offset(page_id, slot_id))
                    file.write(record_data)

                    header.registros += 1
                    header.registros_activos += 1
                    self._escribir_page_header(file, page_id, header)

                    return (page_id, slot_id)

            # Tercero: no queda espacio; crear una página.
            return self._crear_pagina_con_registro(file, record_data)

    def add(self, record: Alumno):
        if self.file_header.delete_mode == MOVE_THE_LAST:
            return self.add_move_the_last(record)
        return self.add_free_list(record)

    # ------------------------------------------------------
    # DELETE
    # ------------------------------------------------------

    def delete_move_the_last(self, rid):
        page_id, slot_id = rid

        if page_id < 0 or page_id >= self.file_header.num_pages:
            return False

        with open(self.filename, 'r+b') as file:
            target_header = self._leer_page_header(file, page_id)

            if slot_id < 0 or slot_id >= target_header.registros:
                return False

            last_page_id = self.file_header.num_pages - 1
            last_header = self._leer_page_header(file, last_page_id)

            if last_header.registros <= 0:
                return False

            last_slot_id = last_header.registros - 1

            if (page_id, slot_id) != (last_page_id, last_slot_id):
                file.seek(self._record_offset(last_page_id, last_slot_id))
                last_record = file.read(RECORD_SIZE)

                file.seek(self._record_offset(page_id, slot_id))
                file.write(last_record)

            last_header.registros -= 1
            last_header.registros_activos -= 1
            self._escribir_page_header(file, last_page_id, last_header)

            if last_header.registros == 0:
                self.file_header.num_pages -= 1
                nuevo_tamano = (
                    FILE_HEADER_SIZE
                    + self.file_header.num_pages * self.file_header.page_size
                )
                file.truncate(nuevo_tamano)
                self._actualizar_file_header(file)

        return True

    def delete_free_list(self, rid):
        page_id, slot_id = rid

        if page_id < 0 or page_id >= self.file_header.num_pages:
            return False

        with open(self.filename, 'r+b') as file:
            header = self._leer_page_header(file, page_id)

            if slot_id < 0 or slot_id >= header.registros:
                return False

            record_offset = self._record_offset(page_id, slot_id)
            file.seek(record_offset)
            marker_data = file.read(FREE_PTR_SIZE)
            marker = struct.unpack(FREE_PTR_FORMAT, marker_data)[0]

            if marker == FREE_SLOT_MARKER:
                return False

            file.seek(record_offset)
            file.write(struct.pack(
                FREE_SLOT_FORMAT, FREE_SLOT_MARKER, header.free_list
            ))

            header.free_list = slot_id
            header.registros_activos -= 1
            self._escribir_page_header(file, page_id, header)

        return True

    def delete(self, rid):
        if self.file_header.delete_mode == MOVE_THE_LAST:
            return self.delete_move_the_last(rid)
        return self.delete_free_list(rid)

    # ------------------------------------------------------
    # READ RECORD
    # ------------------------------------------------------

    def readRecord(self, rid):
        page_id, slot_id = rid

        if page_id < 0 or page_id >= self.file_header.num_pages:
            return None

        with open(self.filename, 'rb') as file:
            header = self._leer_page_header(file, page_id)

            if slot_id < 0 or slot_id >= header.registros:
                return None

            file.seek(self._record_offset(page_id, slot_id))
            data = file.read(RECORD_SIZE)

        if len(data) != RECORD_SIZE:
            return None

        if self.file_header.delete_mode == FREE_LIST:
            marker = struct.unpack_from(FREE_PTR_FORMAT, data, 0)[0]
            if marker == FREE_SLOT_MARKER:
                return None

        return deserializar_alumno(data)

    # ------------------------------------------------------
    # LOAD
    # ------------------------------------------------------

    def load(self):
        with open(self.filename, 'rb') as file:
            for page_id in range(self.file_header.num_pages):
                header = self._leer_page_header(file, page_id)

                if self.file_header.delete_mode == MOVE_THE_LAST:
                    for slot_id in range(header.registros):
                        file.seek(self._record_offset(page_id, slot_id))
                        data = file.read(RECORD_SIZE)
                        yield deserializar_alumno(data)

                else:
                    slots_eliminados = set()
                    current_free = header.free_list

                    while current_free != -1:
                        if current_free in slots_eliminados:
                            raise ValueError(
                                f'Ciclo detectado en FREE LIST de página {page_id}'
                            )
                        if current_free < 0 or current_free >= header.registros:
                            raise ValueError(
                                f'Slot inválido en FREE LIST de página {page_id}'
                            )
                        slots_eliminados.add(current_free)
                        file.seek(self._record_offset(page_id, current_free))
                        free_slot_data = file.read(FREE_SLOT_SIZE)
                        marker, current_free = struct.unpack(
                            FREE_SLOT_FORMAT, free_slot_data
                        )
                        if marker != FREE_SLOT_MARKER:
                            raise ValueError(
                                f'FREE LIST corrupta en página {page_id}'
                            )

                    for slot_id in range(header.registros):
                        if slot_id in slots_eliminados:
                            continue

                        file.seek(self._record_offset(page_id, slot_id))
                        data = file.read(RECORD_SIZE)
                        yield deserializar_alumno(data)
