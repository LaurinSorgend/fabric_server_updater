from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
from rich.progress import Progress, TaskID


async def download_file(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    expected_sha512: str,
    progress: Progress,
    task_id: TaskID,
) -> Path:
    tmp = dest.with_suffix(dest.suffix + ".tmp")

    try:
        hasher = hashlib.sha512()
        total = 0

        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            content_length = int(resp.headers.get("content-length", 0))
            if content_length:
                progress.update(task_id, total=content_length)

            with tmp.open("wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    f.write(chunk)
                    hasher.update(chunk)
                    total += len(chunk)
                    progress.advance(task_id, len(chunk))

        actual = hasher.hexdigest()
        if expected_sha512 and actual != expected_sha512:
            tmp.unlink(missing_ok=True)
            raise ValueError(
                f"Hash mismatch for {dest.name}:\n"
                f"  expected: {expected_sha512}\n"
                f"  got:      {actual}"
            )

        tmp.rename(dest)
        return dest

    except Exception:
        tmp.unlink(missing_ok=True)
        raise
