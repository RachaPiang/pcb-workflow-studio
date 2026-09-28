# PCB Workflow Studio

แอป AI Automation สำหรับงาน PCB แบบ local บน Windows: คุณป้อนโจทย์ ตรวจคำถาม ตรวจหลักฐาน อนุมัติแต่ละขั้น แล้วนำผลไปทำงานใน EasyEDA ด้วยตนเอง

**ระบบรันได้ทั้งแบบ Offline และ AI provider ที่ใช้ OpenAI-compatible Chat Completions API** โหมด Offline สร้างร่างระดับสัญญาณและตรวจข้อมูลตามกฎ ไม่ใช่โมเดล AI และไม่เดาเลขขาหรือ footprint

## เปิดใช้งานบน Windows

ครั้งแรก: ติดตั้ง Python 3.11 ขึ้นไป ดาวน์โหลดหรือ clone repository นี้ แล้วเปิด **Install PCB Studio.cmd** เพื่อสร้าง `.venv` และติดตั้ง dependencies

1. ดับเบิลคลิก **Start PCB Studio.cmd**
2. เปิดแอปที่ **http://127.0.0.1:8765** ถ้าเบราว์เซอร์ไม่เปิดอัตโนมัติ
3. ปิดระบบด้วย **Stop PCB Studio.cmd** การปิดแท็บอย่างเดียวไม่หยุดเซิร์ฟเวอร์

ต้องใช้อินเทอร์เน็ตสำหรับดาวน์โหลด dependencies การพัฒนารอบนี้ทดสอบจริงด้วย Python 3.14.5 บน Windows

ตัว launcher เปิด server ในพื้นหลังบน loopback เท่านั้น มี log ที่ `data/server.log` และใช้พอร์ต 8765 ถ้าพอร์ตถูกใช้โดยโปรแกรมอื่นจะไม่หยุดโปรแกรมนั้นให้อัตโนมัติ

## ลอง MCU Sensor Board 4-layer

สำหรับโหมด AI: เขียนบรีฟแล้วกด **ให้ AI แนะนำแบบจากบรีฟ** ระบบจะเสนอค่าที่อ่านจากบรีฟและค่าที่แนะนำพร้อมเหตุผล กด **ใช่ ใช้ค่านี้**, **ไม่ใช้ค่านี้** หรือ **ยอมรับข้อเสนอที่รอทั้งหมด** ได้ หากไม่เลือกให้กด AI อีกครั้งเพื่อขอทางเลือกใหม่ รายละเอียดที่แก้เองอยู่ในส่วนพับ และแสดงคำถามจำเป็นไม่เกิน 3 ข้อต่อรอบ ค่าที่เลือกไว้แล้วจะไม่ถูก AI เขียนทับ การยอมรับข้อเสนอจะบันทึก Requirements แต่ยังไม่อนุมัติ Gate

1. กด **ลอง MCU Sensor Board 4-layer** ที่หน้าเริ่มต้น หรือสร้างโปรเจกต์เอง
2. หน้า Requirements จะแสดงข้อมูลที่ยังขาด เช่น MCU, กระแส, USB, โรงงาน และขนาดบอร์ด
3. ตอบด้วยข้อมูลจริง หรือกด **ใส่ค่าทดลอง 4-layer** เพื่อทดสอบซอฟต์แวร์ ตัวอย่างนี้ไม่ใช่ reference design
4. กด **บันทึก Requirements** แล้วตรวจและกด **อนุมัติ Requirements** ระบุชื่อและเหตุผล
5. กลับภาพรวม กด **รัน Research → BOM → Review**
6. ดู **BOM และการเชื่อมต่อ** จะได้ BOM เบื้องต้นและตารางสัญญาณ ถ้ายังไม่มีหลักฐาน physical pin จะแสดง `— / Unresolved` และบล็อก Gate ที่เกี่ยวข้อง
7. ไป **ประวัติและ Export** ดาวน์โหลด ZIP หรือ Markdown / CSV / JSON แต่ละไฟล์
8. ปิดและเปิดแอปใหม่ เลือกโปรเจกต์เดิมเพื่อทำต่อ ข้อมูลเก็บอัตโนมัติเมื่อกดบันทึกหรือจบขั้นตอน

โปรเจกต์ตัวอย่างที่ทดสอบไว้ในเครื่องมีคำว่า “ตัวอย่าง” และข้อความระบุว่าเป็น software test ประวัติการกดอนุมัติในการทดสอบใช้ชื่อ “Software UI test” ไม่ใช่การอนุมัติทางวิศวกรรมของคุณ หลังทดสอบจะถอน approval ที่ใช้ทดสอบออก โดยเก็บผลร่างไว้ให้เปิดดู

## เชื่อม AI หรือ Codex

กด **ตั้งค่า AI provider** ในแถบซ้าย แล้วเลือกหนึ่งในสามโหมด:

- **Codex session** — ใช้ session ที่ Codex CLI บนเครื่อง login อยู่แล้ว เหมาะกับการทดลองโดยไม่สร้าง API key ใหม่
- **OpenAI API** — ใช้ Platform API key หรือ endpoint ที่เข้ากันได้ เช่น Ollama / LM Studio
- **Offline** — ไม่ส่งข้อมูลออกและไม่ใช้โมเดล

โหมด **Codex session** ในเวอร์ชันนี้ใช้คำสั่ง `codex exec` ที่ติดตั้งอยู่ในเครื่องผ่าน subprocess แบบ ephemeral, `read-only`, และส่ง prompt ของ Agent เพียงครั้งเดียว ตัวเชื่อมกำหนด `CODEX_HOME` ไปยังโฟลเดอร์มาตรฐานของผู้ใช้เพื่อให้ Codex หา session ได้ แต่ไม่อ่านหรือคัดลอก `~/.codex/auth.json`, ไม่ส่ง token เข้าเว็บ PCB และไม่มีสิทธิ์เขียนไฟล์ใน workspace หาก Codex CLI ยังไม่ login หรือหา executable ไม่พบ ระบบจะแจ้ง error และไม่บันทึกผลลัพธ์บางส่วน

การใช้ Codex session ต้องมี Codex CLI ติดตั้งและ login ในเครื่องก่อน ตรวจสอบได้ด้วย `codex login status` หากยังไม่ login ให้รัน `codex login` แล้วเปิดแอปใหม่ คำสั่งนี้ใช้สิทธิ์ของบัญชี/เวิร์กสเปซ Codex ที่ login อยู่ ไม่ใช่โควตา Offline และไม่ใช่การเชื่อมต่อ API key แบบเดียวกับ OpenAI Platform

กด **ตั้งค่า AI provider** ในแถบซ้าย:

- เลือก Codex session หรือ AI
- ใส่ API base URL ที่ลงท้าย `/v1` ตามบริการนั้น เช่น `http://localhost:11434/v1` สำหรับบริการโมเดลในเครื่องที่เปิด API แบบเข้ากันได้
- ใส่ชื่อโมเดลที่ติดตั้งหรือมีสิทธิ์ใช้งาน
- ใส่ API key ถ้าบริการนั้นต้องใช้

การตั้งค่าจากหน้าจออยู่ในหน่วยความจำจนหยุด server เท่านั้น API key ไม่ถูกบันทึกใน SQLite, snapshot, export หรือ log ของแอป เมื่อเลือก AI หรือ Codex และกดรัน ระบบจะส่งเฉพาะ Requirements / ข้อความจาก PDF / structured outputs ที่ Agent นั้นต้องใช้ไปยังบริการที่เลือก **การเลือก cloud AI หรือ Codex session จึงทำให้ข้อความบางส่วนออกจากเครื่อง** รุ่นนี้ไม่ส่งภาพหรือไฟล์ binary ให้โมเดล

ตั้งค่าเริ่มต้นผ่าน environment variables ได้ โดยกำหนดใน PowerShell ก่อนเปิด launcher:

```powershell
$env:PCB_AI_BASE_URL = 'http://localhost:11434/v1'
$env:PCB_AI_MODEL = 'your-installed-model-name'
# สำหรับบริการที่ต้องใช้ key ให้กำหนด PCB_AI_API_KEY ใน environment ของคุณ
.\.venv\Scripts\python.exe launch.py
```

รองรับเฉพาะบริการ OpenAI-compatible ที่มี `/chat/completions` และตอบข้อความ JSON ตาม schema ชื่อโมเดลและขีดจำกัดขึ้นอยู่กับบริการ ไม่ได้ติดตั้งโมเดล local มาให้ และยังไม่ได้ทดสอบกับบัญชี AI จริงเนื่องจากไม่มี API key การทดสอบ adapter ใช้ HTTP mock โดยตรวจ contract, schema, HTTP error handling และการไม่เปิดเผย key เอกสาร API ที่เข้ากันได้: [Ollama](https://docs.ollama.com/api/openai-compatibility), [LM Studio](https://lmstudio.ai/docs/developer/openai-compat/tools)

เปลี่ยน provider ที่ใช้ protocol อื่นได้โดย implement `Provider.generate()` ใน `pcb_assistant/provider.py` โดยไม่ต้องเปลี่ยน data schema หรือ approval engine

## ค้นชิ้นส่วนอัตโนมัติและลดการเรียก AI

ใน Codex session ปุ่มค้นชิ้นส่วนจะเปิด live web search และเก็บจำนวน search events ไว้ใน Agent run ระบบเสนอรุ่นจริง/ผู้ผลิต/package/ลิงก์ให้เลือกก่อน จากนั้นดาวน์โหลด PDF สาธารณะและเก็บต้นฉบับไว้ใช้ซ้ำ หากบางเว็บปฏิเสธการดาวน์โหลด ให้เลือกชิ้นส่วนนั้นในช่อง **Datasheet ใช้กับชิ้นส่วน** ตอนนำเข้า PDF เอง

Research เลือกเฉพาะหน้าที่เกี่ยวกับขา/package/วงจรใช้งานภายใต้งบบริบท เมื่อไม่มีข้อมูลเปลี่ยนจะใช้ Research และ Circuit เดิม การตรวจตามกฎไม่เรียก AI ส่วน AI Review เป็นปุ่มแยก หน้าเว็บแสดงขั้นตอนปัจจุบันและป้องกันกดงานซ้ำ ระหว่างงานล้มเหลวจะเก็บผลขั้นก่อนหน้าไว้ทำต่อ

เลขขาที่มีข้อความหลักฐานสามารถแสดงเป็นร่างได้ก่อน human confirmation; เลขขาหรือข้อกล่าวอ้างที่ไม่มีหลักฐานจะถูกตัดออกและแจ้งใน Unresolved การผ่าน Gate ยังคงต้องยืนยันหลักฐาน ตัวนับ usage รุ่นใหม่ไม่นับข้อมูลเก่าที่อาจเคยลงซ้ำ และบันทึกทุกการเรียกแยกกันรวมรอบล้มเหลวที่ทราบ usage

## จาก datasheet ไป physical pin

1. นำเข้า **Datasheet PDF** พร้อมชื่อเอกสาร รุ่น และ URL ถ้ามี หน้าอ้างอิงเป็น **ลำดับหน้า PDF เริ่มที่ 1** ไม่ใช่เลขหน้าที่พิมพ์ในเอกสารเสมอไป
2. รัน Research หรือเพิ่มข้อเท็จจริงด้วยตัวเองในหน้า **Datasheet และหลักฐาน**
3. ข้อเท็จจริงต้องมี Reference เช่น U1, ชนิดข้อมูล, ข้อสรุป, source ID, หน้า และข้อความอ้างอิงตรงกับข้อความที่แยกได้ สำหรับชนิด `pin` ต้องมี `pin_number` และ `pin_name`
4. ระบบตรวจว่าหน้าและข้อความอ้างอิงมีอยู่จริง แต่ **ไม่ได้พิสูจน์ว่าข้อสรุปตีความถูก** คุณต้องดาวน์โหลดและตรวจต้นฉบับ โดยเฉพาะตาราง pinout และ package
5. กด **ตรวจต้นฉบับและยืนยัน** ข้อเท็จจริงจึงเป็น Confirmed พร้อมชื่อผู้ตรวจ การแก้ข้อเท็จจริงจะถอนการยืนยันของข้อที่แก้และล้างร่างวงจร
6. กด **สร้าง BOM จาก Research ปัจจุบัน** เพื่อใช้ข้อเท็จจริงที่ยืนยันแล้ว โดยไม่รันการสกัดเอกสารซ้ำ
7. ปรับ Circuit JSON ได้ด้วยตัวเอง ตัวเลขขาร่างต้องอ้าง `fact.id` ของ component นั้น และต้องเป็น Confirmed ก่อนผ่านการอนุมัติ โดยชื่อและเลขขาทั้งสองปลายต้องตรงกับหลักฐาน Footprint และช่วงแรงดันต้องมีหลักฐานชนิดที่เกี่ยวข้อง
8. จัดการรายการ `unresolved` ใน Research/Circuit หลังแก้ประเด็นจริงแล้ว ระบบจะบล็อก Connections Gate ตราบที่รายการเหล่านี้ยังไม่ว่าง

Confirmed ของข้อเท็จจริงไม่เท่ากับวงจรถูกต้องทั้งหมด ผลจาก Circuit Agent ยังคงเป็น Inferred/Unresolved จนคุณตรวจและอนุมัติ Gate

## EasyEDA และการตรวจหลังออกแบบ

MVP **ไม่แก้ EasyEDA source** และไม่มี EasyEDA API automation:

| ไฟล์ | สิ่งที่ทำได้จริง |
|---|---|
| EasyEDA JSON | อ่าน JSON structure / จำนวน shapes และเก็บต้นฉบับ; ยังไม่แปล shape strings เป็น connectivity |
| BOM CSV | อ่าน reference / quantity / part number / footprint และเทียบกับร่างที่อนุมัติ |
| Normalized netlist JSON | เทียบ endpoints ของทุก net และรายงาน missing/extra/mismatched nets |
| Schematic / PCB PNG, JPEG | แสดงภาพเพื่อให้มนุษย์ตรวจ; ยังไม่มี AI vision review |
| Normalized DRC JSON | ตรวจ `completed`, tool, revision, issues; Critical/Error บล็อก Gate |
| Gerber ZIP | ตรวจ archive path, ขนาด, layer inventory และ signatures ขั้นพื้นฐาน; ไม่วิเคราะห์ geometry |
| ไฟล์อื่น / CPL | เก็บต้นฉบับสำหรับ manufacturing checklist |

ตัวอย่างรูปแบบกลางอยู่ใน `examples/` ข้อมูลในนั้นเป็น synthetic fixtures ไม่ใช่วงจรจริง Format ที่ไม่รู้จักจะถูกระบุ Unsupported ไม่ถือว่าผ่าน ตรวจ Gerber รองรับ inventory อัตโนมัติของ 1/2/4 layers; ชั้นอื่นต้องพัฒนา parser เพิ่ม

เมื่อมีไฟล์แล้วกด **ตรวจไฟล์ทั้งหมด** จะได้ Review, Manufacturing checklist และ Bring-up plan ตรวจ manual checklist ของ Schematic, PCB และ Release พร้อมชื่อ/เหตุผล ก่อนอนุมัติ Gate ตามลำดับ

รายการชื่อไฟล์เดียวกันและชนิดเดียวกันที่นำเข้าใหม่จะทำให้ไฟล์เก่า inactive โดยไม่ลบต้นฉบับ ชื่ออื่นยัง active ได้พร้อมกัน แต่ละไฟล์ active จะถูกตรวจทั้งหมด สามารถกด “พักไฟล์นี้” สำหรับไฟล์เก่าที่ไม่ได้ใช้ ไฟล์ datasheet เก็บถาวรเป็นหลักฐาน

## Approval และเวอร์ชัน

Gates: Requirements → Components → Connections → Schematic → PCB → Manufacturing release

- ไม่มี Agent ใดเข้าถึงปุ่มอนุมัติหรือ storage โดยตรง
- อนุมัติต้องมีชื่อ เหตุผล และ evidence hash ตรงกับข้อมูลปัจจุบัน
- Critical ในรายงานที่เกี่ยวข้องข้ามไม่ได้ Error ที่เกี่ยวข้องต้องแก้ ไม่มีปุ่ม waive เพื่อบังคับผ่าน
- เปลี่ยน Requirements: ยกเลิกทุก Gate และล้างผลอนุพันธ์
- เปลี่ยน Research / datasheet: ยกเลิก Components และขั้นถัดไป
- เปลี่ยนวงจร: ยกเลิก Components หรือ Connections ตามข้อมูลที่เปลี่ยน
- เปลี่ยนชุดไฟล์นำเข้า: ยกเลิก Schematic และขั้นถัดไปอย่างระมัดระวัง แม้ไฟล์นั้นเป็น PCB
- แก้ manual check: ยกเลิก approval ตั้งแต่ Gate นั้นเป็นต้นไป
- ถอนได้จากรายการ **การอนุมัติที่ใช้อยู่** โดยไม่ลบประวัติ
- ย้อน snapshot จะสร้างเวอร์ชันใหม่ ไม่มี approval หรือ manual check เดิมติดมาด้วย
- เปิดหลายแท็บได้ แต่ถ้ามีการบันทึกจากแท็บอื่นก่อน ระบบจะตอบ conflict และให้โหลดใหม่ ไม่เขียนทับเงียบ ๆ

## ข้อมูลในเครื่องและ backup

```text
data/
  projects.sqlite3      # current documents + immutable version snapshots
  projects/<id>/originals/<sha256>  # original bytes, never edited by the app
  server.log
```

SQLite เป็นแหล่งข้อมูลหลัก snapshot บันทึกใน transaction เดียวกับเวอร์ชันล่าสุด ผลลัพธ์ Markdown/CSV/JSON สร้างจาก snapshot ที่เลือกเมื่อ Export จึงไม่ต้องซิงก์ไฟล์กลางที่อาจเขียนค้าง

ZIP export มี `project.json`, `requirements.*`, `datasheet_sources.json`, `research.json`, `circuit.json`, `bom.csv`, `pins.csv`, `pin_connections.csv`, `design_constraints.json`, `review_report.md`, `approvals.json`, `file_versions.json`, `agent_runs.json`, `usage_report.json`, `manufacturing_checklist.md`, `bringup_test_plan.md` และ original files

หน้า Overview จะแสดงจำนวนครั้งเรียก, input/output/total tokens (เมื่อ provider ส่ง usage กลับมา), model, reasoning effort, เวลา และค่าใช้จ่าย API โดยประมาณต่อ Agent run ส่วน Codex session ใช้โควตาบัญชี Codex จึงไม่ตีเป็นดอลลาร์ในแอป ค่า API คำนวณจากราคา model ที่เลือกและเป็นเพียง estimate

Export ZIP เป็นเอกสารส่งต่อ/ตรวจ ไม่ใช่ restore-backup แบบ one-click ใน MVP หากต้องการย้ายแอปหรือสำรองเพื่อเปิดทำงานต่อครบทุกเวอร์ชัน ให้ **หยุด server ก่อน แล้ว copy โฟลเดอร์ `data` ทั้งโฟลเดอร์** ไปเก็บไว้ กำหนด `PCB_DATA_DIR` เพื่อเลือกตำแหน่งข้อมูลอื่นได้

CSV ป้องกันสูตรจากข้อความที่ขึ้นต้นด้วย `=`, `+`, `-`, `@` และเว็บ escape เนื้อหาที่แสดง ไม่โหลด script/CDN ภายนอก local writes ต้องมี session token และ same origin แอปเป็น single-user local tool ไม่ใช่ระบบ multi-user authentication หรือ audit log ที่ป้องกันเจ้าของเครื่องแก้ฐานข้อมูลได้

## Architecture และโครงสร้างโค้ด

ถ้าต้องการใช้ผ่าน Discord, Telegram หรือ OpenClaw ดู [แนวทาง Channel Architecture](docs/CHANNEL_ARCHITECTURE.md) ระบบเหล่านี้ควรเป็น channel adapter ที่เรียก Orchestrator/API ชุดเดียวกับเว็บ ไม่ใช่สร้าง Agent ชุดใหม่แยกกัน

```text
Browser UI (HTML/CSS/JS)
        ↓ local FastAPI + schema validation + version conflict checks
Main Orchestrator / approval gates / evidence hashes
        ├─ Requirements Agent
        ├─ Datasheet Research Agent
        ├─ Circuit/BOM Agent
        ├─ Review Agent + deterministic checks
        └─ Manufacturing/Test Agent
        ↓                         ↓
Provider protocol          SQLite snapshots + original files
(offline / Codex session / compatible API) ↓
                           Markdown / CSV / JSON export
```

เลือก Python เพื่ออ่านและ debug ง่าย, FastAPI เพื่อแยก API กับ UI และทดสอบได้ตรงจุด, Pydantic เพื่อกำหนดสัญญาข้อมูลและปฏิเสธ field ที่ไม่รู้จัก, SQLite เพราะไม่ต้องตั้ง database service, และ JavaScript ธรรมดาเพื่อลดขั้น build / Node dependency ไม่ใช้ LangChain

- `schemas.py`: Project, Requirement, Component, DatasheetSource, Fact, Pin, Net, Connection, BOMItem, DesignConstraint, ReviewFinding, Approval, FileVersion, TestStep
- `agents.py`: input/output ของ Agent ทั้ง 5 และการตรวจหลักฐาน
- `orchestrator.py`: workflow, gate order, invalidation, run audit
- `provider.py`: provider protocol + OpenAI-compatible adapter
- `storage.py`: SQLite transaction / snapshots / original files
- `importers.py`: parsers และ comparison logic
- `exports.py`: downloadable artifacts
- `api.py`: HTTP endpoints, uploads, human decisions
- `static/`: Thai UI ไม่มี build step
- `tests/`: behavior, API, adapter และ importer tests

เอกสารเทคโนโลยีที่ใช้อ้างอิง: [FastAPI uploads](https://fastapi.tiangolo.com/tutorial/request-files/), [FastAPI TestClient](https://fastapi.tiangolo.com/reference/testclient/), [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/), [pypdf text extraction limitations](https://github.com/py-pdf/pypdf/blob/main/docs/user/extract-text.md)

## เพิ่ม Agent ในอนาคต

1. สร้าง Pydantic output schema ที่มี field ชัดเจน; ห้ามเปิด field สำหรับ approval
2. สร้าง class ที่มี `name` และ `run()` รับเฉพาะ Requirements/หลักฐาน/artifacts ที่ต้องใช้ ไม่ส่ง Project ทั้งก้อนหรือ API key ให้ Agent
3. ถ้าใช้ AI เรียก `provider.generate(name, instructions, bounded_context, OutputSchema)` แล้วตรวจ output ด้วยโปรแกรมอีกครั้ง
4. เพิ่มการเรียกใน Orchestrator หลัง preconditions ที่เหมาะสม เรียก `record()` เพื่อเก็บ input/output hash
5. เพิ่ม field ใน Project และกำหนดว่า input อะไรเปลี่ยนแล้วต้อง invalidate output/approval ไหน อัปเดต `evidence_hash()`
6. เพิ่ม UI/API และ export ที่จำเป็น
7. เขียน behavior test สำหรับผลสำเร็จ, missing evidence, critical finding และ invalidation

ถ้าจะเพิ่มการเขียน EasyEDA ในอนาคต ต้องออกแบบ preview, diff, backup และปุ่ม Human approval สำหรับการเขียนแยกต่างหาก ไม่ใช้ approval ของการอ่านแทน

## ทดสอบและ debug

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --check pcb_assistant/static/app.js
```

Node ใช้ตรวจไวยากรณ์ระหว่างพัฒนาเท่านั้น ไม่จำเป็นสำหรับผู้เปิดใช้งาน แอปเริ่มด้วย `serve.py` ผ่าน launcher ถ้าต้องการดู log แบบ foreground ให้หยุดตัวเดิมก่อน แล้วรัน:

```powershell
.\.venv\Scripts\python.exe serve.py
```

API schema ที่ `/docs` ใช้อ่านได้ การทดลองเขียนผ่านเครื่องมือภายนอกต้องอ่าน token จาก `/api/bootstrap` และใส่ header `X-PCB-Token` UI ใส่ให้อัตโนมัติ

ขีดจำกัด: PDF ที่นำเข้าเองไม่เกิน 200 หน้า; การดาวน์โหลดอัตโนมัติรองรับถึง 1,000 หน้าและอ่านเฉพาะส่วนต้น/ท้ายของเอกสารขนาดใหญ่ตามที่ระบุในคู่มือ; 20 MB, ข้อความรวม 1 ล้านตัวอักษร; ไม่มี OCR ข้อความแต่ละหน้าเก็บไม่เกิน 30,000 ตัวอักษรและ AI เลือกหน้าที่เกี่ยวข้องไม่เกิน 3,500 ต่อหน้า/48,000 รวม ค่าตารางที่แยกผิดต้องตรวจต้นฉบับหรือใช้เอกสาร OCR ที่ตรวจแล้ว Manual checklist ไม่แทนการวิเคราะห์ SI/PI, thermal, EMC หรือมาตรฐานความปลอดภัยเฉพาะงาน
