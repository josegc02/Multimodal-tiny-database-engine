"""Manejo de transacciones (BEGIN / COMMIT / ROLLBACK)."""

from enum import Enum
from datetime import datetime

class TransactionState(Enum):
    """Estados posibles de una transacción."""
    ACTIVE = "ACTIVE"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


class Transaction:
    """Representa una transacción en curso.

    Guarda su identificador, estado actual, marca de tiempo de inicio,
    los locks que tiene adquiridos y el log de operaciones para rollback.
    """

    def __init__(self, tx_id: int):
        self.tx_id = tx_id
        self.state = TransactionState.ACTIVE
        self.start_time = datetime.now()
        self.end_time = None
        self.locks_held = set()      # {(resource, mode), ...}
        self.undo_log = []           # operaciones para rollback

    # --- Transiciones de estado ---

    def mark_committed(self):
        """Marca la transacción como confirmada."""
        if self.state != TransactionState.ACTIVE:
            raise RuntimeError(f"No se puede commit en estado {self.state.value}")
        self.state = TransactionState.COMMITTED
        self.end_time = datetime.now()

    def mark_aborted(self):
        """Marca la transacción como abortada."""
        if self.state != TransactionState.ACTIVE:
            raise RuntimeError(f"No se puede abort en estado {self.state.value}")
        self.state = TransactionState.ABORTED
        self.end_time = datetime.now()

    # --- Consultas de estado ---

    @property
    def is_active(self) -> bool:
        return self.state == TransactionState.ACTIVE

    @property
    def is_finished(self) -> bool:
        return self.state in (
            TransactionState.COMMITTED,
            TransactionState.ABORTED,
            TransactionState.FAILED,
        )

    @property
    def duration(self) -> float:
        """Duración de la transacción en segundos."""
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds()

    # --- Undo log ---

    def add_operation(self, op):
        """Registra una operación para poder deshacerla."""
        if not self.is_active:
            raise RuntimeError("No se pueden registrar operaciones en transacción terminada")
        self.undo_log.append(op)

    # --- Representación ---

    def __repr__(self):
        return f"Transaction(id={self.tx_id}, state={self.state.value})"

    def __str__(self):
        return (f"TX#{self.tx_id} [{self.state.value}] "
                f"locks={len(self.locks_held)} ops={len(self.undo_log)}")