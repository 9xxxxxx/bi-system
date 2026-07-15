import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO


class FileStorageError(RuntimeError):
    """Base error for content-addressed storage operations."""


class EmptyUploadError(FileStorageError):
    pass


class UploadTooLargeError(FileStorageError):
    pass


class StorageBoundaryError(FileStorageError):
    pass


class StoredBlobIntegrityError(FileStorageError):
    pass


@dataclass(frozen=True, slots=True)
class StoredBlob:
    sha256: str
    size_bytes: int
    storage_key: str
    created: bool


class LocalContentAddressedStorage:
    def __init__(self, root: Path, *, max_bytes: int, read_chunk_bytes: int = 1024 * 1024) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if read_chunk_bytes <= 0:
            raise ValueError("read_chunk_bytes must be positive")

        self.root = root.expanduser().resolve()
        self.max_bytes = max_bytes
        self.read_chunk_bytes = read_chunk_bytes

    def store(self, stream: BinaryIO, *, max_bytes: int | None = None) -> StoredBlob:
        effective_max_bytes = max_bytes or self.max_bytes
        if effective_max_bytes <= 0:
            raise ValueError("max_bytes override must be positive")
        temporary_directory = self.root / ".tmp"
        temporary_directory.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w+b",
                prefix="upload-",
                suffix=".part",
                dir=temporary_directory,
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                digest = hashlib.sha256()
                size_bytes = 0

                while chunk := stream.read(self.read_chunk_bytes):
                    size_bytes += len(chunk)
                    if size_bytes > effective_max_bytes:
                        msg = f"Upload exceeds the {effective_max_bytes} byte limit"
                        raise UploadTooLargeError(msg)
                    digest.update(chunk)
                    temporary_file.write(chunk)

                if size_bytes == 0:
                    raise EmptyUploadError("Upload is empty")

                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            sha256 = digest.hexdigest()
            storage_key = self._storage_key(sha256)
            final_path = self.path_for(storage_key)
            final_path.parent.mkdir(parents=True, exist_ok=True)

            if final_path.exists():
                if (
                    final_path.stat().st_size != size_bytes
                    or self._file_sha256(final_path) != sha256
                ):
                    raise StoredBlobIntegrityError(
                        "Stored blob does not match its content address",
                    )
                temporary_path.unlink()
                temporary_path = None
                created = False
            else:
                os.replace(temporary_path, final_path)
                temporary_path = None
                created = True

            return StoredBlob(
                sha256=sha256,
                size_bytes=size_bytes,
                storage_key=storage_key,
                created=created,
            )
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def path_for(self, storage_key: str) -> Path:
        relative_path = Path(storage_key)
        if (
            not storage_key
            or "\\" in storage_key
            or ":" in storage_key
            or relative_path.is_absolute()
            or relative_path.drive
            or any(part in {".", ".."} for part in relative_path.parts)
        ):
            raise StorageBoundaryError("Storage key is outside the configured root")

        resolved_path = (self.root / relative_path).resolve()
        try:
            resolved_path.relative_to(self.root)
        except ValueError as exc:
            raise StorageBoundaryError("Storage key is outside the configured root") from exc

        return resolved_path

    @staticmethod
    def _storage_key(sha256: str) -> str:
        return PurePosixPath("sha256", sha256[:2], sha256[2:4], sha256).as_posix()

    def _file_sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file_handle:
            while chunk := file_handle.read(self.read_chunk_bytes):
                digest.update(chunk)
        return digest.hexdigest()
