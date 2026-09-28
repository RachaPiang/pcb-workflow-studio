"""Public HTTPS PDF retrieval. No credentials, proxies or private-network access."""
import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urlparse, urljoin

from .importers import MAX_UPLOAD, inspect_file
from .schemas import DatasheetSource
from .cancellation import check_cancelled, JobCancelled
from .storage import digest


def public_target(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("เอกสารต้องเป็น HTTPS สาธารณะ ไม่มีรหัสผ่านหรือพอร์ตพิเศษ")
    addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError("ไม่อนุญาต URL ที่ชี้เครือข่ายภายใน")
    return parsed, addresses[0]


def fetch_pdf(url):
    started = time.monotonic()
    for _ in range(5):
        check_cancelled()
        parsed, address = public_target(url)
        # Pin the checked public address while retaining hostname TLS verification.
        connection = http.client.HTTPSConnection(parsed.hostname, timeout=15, context=ssl.create_default_context())
        connection.sock = ssl.create_default_context().wrap_socket(
            socket.create_connection((address, 443), timeout=15), server_hostname=parsed.hostname)
        try:
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
            connection.request("GET", target, headers={"User-Agent": "PCB-Workflow-Studio/0.2", "Accept": "application/pdf"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise ValueError("เอกสาร redirect ไม่สมบูรณ์")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError(f"ดาวน์โหลดเอกสาร HTTP {response.status}")
            if int(response.getheader("Content-Length", "0")) > MAX_UPLOAD:
                raise ValueError("เอกสารเกิน 20 MB")
            chunks, length = [], 0
            while True:
                check_cancelled()
                data = response.read(65536)
                if not data:
                    break
                length += len(data)
                if length > MAX_UPLOAD or time.monotonic() - started > 45:
                    raise ValueError("เอกสารเกินขนาดหรือเวลาที่กำหนด")
                chunks.append(data)
            content = b"".join(chunks)
            if not content.startswith(b"%PDF-"):
                raise ValueError("ลิงก์ไม่ได้ส่ง PDF โดยตรง กรุณาใช้ลิงก์ datasheet PDF หรือนำเข้าเอง")
            return content, url
        finally:
            connection.close()
    raise ValueError("เอกสาร redirect มากเกินไป")


def acquire_sources(project, store, progress=None):
    """Reuse originals; failed downloads remain visible and can be retried."""
    problems = []
    for index, part in enumerate(project.discovery.parts, 1):
        check_cancelled()
        if part.status != "selected":
            continue
        if progress:
            progress(f"เอกสาร {index}/{len(project.discovery.parts)}: {part.ref} {part.part_number}")
        cached = next((s for s in project.sources if (part.datasheet_url and s.url == part.datasheet_url) or
                       (s.part_number == part.part_number and s.component_refs)), None)
        if cached:
            if part.ref not in cached.component_refs:
                cached.component_refs.append(part.ref)
            continue
        if not part.datasheet_url:
            problems.append(f"{part.ref} {part.part_number}: ไม่พบลิงก์ PDF")
            continue
        failure_key = "download:" + digest(part.datasheet_url)
        if failure_key in project.pipeline_cache:
            problems.append(f"{part.ref}: ข้ามลิงก์ที่เคยดาวน์โหลดไม่ได้ · กดลองเอกสารที่ขาดอีกครั้ง หรือนำเข้า PDF เอง")
            continue
        try:
            data, final_url = fetch_pdf(part.datasheet_url)
            item = inspect_file(part.ref + "-datasheet.pdf", "datasheet", data, research_pdf=True)
            if not item.summary.get("supported"):
                raise ValueError("PDF ไม่มีข้อความที่อ่านได้ ต้อง OCR หรือนำเข้าเอกสารอื่น")
            source = DatasheetSource(file_id=item.id, title=f"{part.manufacturer} {part.part_number}",
                revision="Downloaded; verify document revision", url=part.datasheet_url,
                pages=item.summary.pop("pages"), sha256=item.sha256,
                component_refs=[part.ref], part_number=part.part_number)
            item.summary["download_url"] = final_url
            store.put_original(project.id, data)
            project.files.append(item)
            project.sources.append(source)
        except JobCancelled:
            raise
        except (ValueError, OSError, http.client.HTTPException) as exc:
            project.pipeline_cache[failure_key] = str(exc)[:220]
            problems.append(f"{part.ref} {part.part_number}: {str(exc)[:220]}")
    return problems
