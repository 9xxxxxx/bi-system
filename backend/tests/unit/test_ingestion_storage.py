from io import BytesIO
from pathlib import Path

import pytest
from bi_system.ingestion.storage import (
    EmptyUploadError,
    LocalContentAddressedStorage,
    StorageBoundaryError,
    StoredBlobIntegrityError,
    UploadTooLargeError,
)


class GuardedStream(BytesIO):
    def __init__(self, content: bytes, maximum_read_size: int) -> None:
        super().__init__(content)
        self.maximum_read_size = maximum_read_size
        self.read_sizes: list[int] = []

    def read(self, size: int | None = -1) -> bytes:
        recorded_size = -1 if size is None else size
        self.read_sizes.append(recorded_size)
        if size is None or size < 0 or size > self.maximum_read_size:
            raise AssertionError(f"Unbounded read requested: {size}")
        return super().read(size)


def test_storage_streams_to_content_addressed_path(tmp_path: Path) -> None:
    content = b"city,value\nbeijing,10\n" * 100
    stream = GuardedStream(content, maximum_read_size=64)
    storage = LocalContentAddressedStorage(
        tmp_path / "uploads", max_bytes=10_000, read_chunk_bytes=64
    )

    blob = storage.store(stream)

    assert blob.created is True
    assert blob.size_bytes == len(content)
    assert blob.storage_key == (f"sha256/{blob.sha256[:2]}/{blob.sha256[2:4]}/{blob.sha256}")
    assert storage.path_for(blob.storage_key).read_bytes() == content
    assert stream.read_sizes
    assert max(stream.read_sizes) == 64


def test_storage_reuses_duplicate_content(tmp_path: Path) -> None:
    storage = LocalContentAddressedStorage(tmp_path / "uploads", max_bytes=1_000)

    first = storage.store(BytesIO(b"same content"))
    second = storage.store(BytesIO(b"same content"))

    assert first.created is True
    assert second.created is False
    assert second.sha256 == first.sha256
    assert second.storage_key == first.storage_key
    assert len(list((tmp_path / "uploads" / "sha256").rglob(first.sha256))) == 1


def test_storage_detects_corrupt_existing_blob(tmp_path: Path) -> None:
    storage = LocalContentAddressedStorage(tmp_path / "uploads", max_bytes=1_000)
    first = storage.store(BytesIO(b"expected"))
    storage.path_for(first.storage_key).write_bytes(b"corrupt!")

    with pytest.raises(StoredBlobIntegrityError, match="content address"):
        storage.store(BytesIO(b"expected"))

    assert list((tmp_path / "uploads" / ".tmp").iterdir()) == []


def test_storage_rejects_empty_upload_and_removes_temporary_file(tmp_path: Path) -> None:
    storage = LocalContentAddressedStorage(tmp_path / "uploads", max_bytes=1_000)

    with pytest.raises(EmptyUploadError, match="empty"):
        storage.store(BytesIO())

    assert list((tmp_path / "uploads" / ".tmp").iterdir()) == []


def test_storage_rejects_oversized_upload_and_removes_temporary_file(tmp_path: Path) -> None:
    storage = LocalContentAddressedStorage(
        tmp_path / "uploads",
        max_bytes=5,
        read_chunk_bytes=2,
    )

    with pytest.raises(UploadTooLargeError, match="5 byte limit"):
        storage.store(BytesIO(b"123456"))

    assert list((tmp_path / "uploads" / ".tmp").iterdir()) == []


@pytest.mark.parametrize("storage_key", ["../secret", "/absolute/path", "C:\\secret"])
def test_storage_rejects_paths_outside_root(tmp_path: Path, storage_key: str) -> None:
    storage = LocalContentAddressedStorage(tmp_path / "uploads", max_bytes=1_000)

    with pytest.raises(StorageBoundaryError, match="outside"):
        storage.path_for(storage_key)
