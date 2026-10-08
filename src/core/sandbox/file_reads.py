"""沙箱二进制文件的有界读取。"""

from __future__ import annotations


def read_binary(sandbox, path: str, *, max_bytes: int = 20 * 1024 * 1024) -> bytes:
    # execd 的 limit 查询参数走文本截取流程，会破坏 XLSX 等二进制文件。
    # 不传 offset/limit，在客户端限制流的大小，保持原始字节且避免无界下载。
    stream = sandbox.files.read_bytes_stream(path, chunk_size=64 * 1024)
    content = bytearray()
    try:
        for chunk in stream:
            if len(content) + len(chunk) > max_bytes:
                raise OverflowError(f"文件超过读取上限 {max_bytes} 字节")
            content.extend(chunk)
    finally:
        close = getattr(stream, "close", None)
        if close:
            close()
    return bytes(content)
